// ПРОВЕРКА ПО СЛЕПЫМ ЗОНАМ.
//
// У площадки поверх ролика лежит своя обвязка: сверху шапка, справа
// колонка лайков, снизу никнейм с описанием и музыкой, по бокам края,
// которые обрежутся. Текст, попавший туда, зритель либо не прочтёт,
// либо не увидит вовсе.
//
// Компоненты и так расставляют текст по этим числам. Но кегль зависит
// от длины слова, а строки заголовка придумывает модель — значит есть
// чему разъехаться. Здесь каждый монтаж проверяется до рендера, и то,
// что не влезает, ужимается.

import {SAFE, SUB, TITLE} from './style.js';
import {fitScale} from './fit.js';

// Свободная полоса по ширине: от обрезаемого края слева до колонки
// кнопок справа. Ровно та же, по которой ужимает себя сама плашка.
const BAND = (1 - SAFE.icons.width) - SAFE.side;

// Прикидка ширины набранного текста в долях кадра.
const CHAR_W = {caps: 0.74, lower: 0.62, other: 0.36};

const widthOf = (text, size, uppercase) => {
	const s = uppercase ? String(text).toUpperCase() : String(text);
	let units = 0;
	for (const ch of s) {
		if (/[A-ZА-ЯЁ0-9]/.test(ch)) units += CHAR_W.caps;
		else if (/[a-zа-яё]/.test(ch)) units += CHAR_W.lower;
		else units += CHAR_W.other;
	}
	return units * size;
};

// Свободная полоса по горизонтали — между обрезаемым краем и колонкой
// кнопок. Выше колонки она шире, ниже — уже.
const band = (topY) => {
	const left = SAFE.side;
	const right = topY >= SAFE.icons.from ? 1 - SAFE.icons.width : 1 - SAFE.side;
	return {left, right, width: right - left};
};

// Проверка одной строки: влезает ли она по ширине и не свисает ли вниз,
// в подпись под роликом.
const fits = ({text, size, topY, uppercase, frameW, frameH}) => {
	const {width} = band(topY);
	const overWidth = widthOf(text, size, uppercase) / frameW - width;
	// Высота строки примерно равна кеглю: для проверки на нижнюю границу
	// этого хватает, точная метрика шрифта тут ничего не меняет.
	const bottom = topY + size / frameH;
	const overBottom = bottom - (1 - SAFE.bottom);

	return {
		ok: overWidth <= 0 && overBottom <= 0 && topY >= SAFE.top,
		overWidth,
		overBottom,
	};
};

// Плашка перед проверкой ужимается — ровно так же, как её ужимает сам
// компонент. Иначе проверка ругалась бы на строки, которые на экране
// прекрасно помещаются.
const titleScale = (lines) =>
	fitScale(
		lines.map((line) => {
			const badge = line.pieces[0]?.kind === 'badge';
			const tier = badge ? TITLE.badge : TITLE.big;
			return {
				text: line.pieces.map((p) => p.text).join(' '),
				size: tier.size,
				uppercase: tier.uppercase,
				padding: badge ? 0.5 : 0,
			};
		}),
		BAND
	);

// Строку, которая не влезает даже после ужатия, укорачиваем по словам.
// Обрезать по буквам нельзя: обрубок читается как опечатка.
export const fitTitle = (title, {width = 1080} = {}) => {
	if (!title?.lines?.length) return title;

	const lines = title.lines.map((line) => ({...line, pieces: line.pieces.map((p) => ({...p}))}));

	for (let guard = 0; guard < 12; guard++) {
		const scale = titleScale(lines) * width;
		const over = lines
			.map((line, i) => {
				const badge = line.pieces[0]?.kind === 'badge';
				const tier = badge ? TITLE.badge : TITLE.big;
				const text = line.pieces.map((p) => p.text).join(' ');
				const w = widthOf(text, tier.size * titleScale(lines), tier.uppercase);
				return {i, over: w / width - BAND, words: text.split(/\s+/).length};
			})
			.filter((x) => x.over > 0 && x.words > 1)
			.sort((a, b) => b.over - a.over)[0];

		if (!over) break;

		// Убираем последнее слово самой широкой строки и считаем заново.
		const line = lines[over.i];
		const piece = line.pieces[line.pieces.length - 1];
		piece.text = piece.text.split(/\s+/).slice(0, -1).join(' ');
		if (!piece.text) line.pieces.pop();
	}

	return {...title, lines: lines.filter((l) => l.pieces.length)};
};

// Главная проверка. Возвращает список нарушений — пустой, если всё
// внутри рамки. Ничего не меняет: решение принимает вызывающий.
export const checkSafeArea = (plan, {width = 1080, height = 1920} = {}) => {
	const problems = [];

	const title = plan?.title;
	if (title?.lines?.length) {
		// Плашка идёт сверху и набирается крупно — она рискует больше всех.
		// Плашка растёт вверх от опорной линии на груди, а не от верха кадра.
		//
		// Опора та же, что в компоненте, вместе со сдвигом на многострочной
		// плашке: считать по другой означало бы проверять не то, что видит
		// зритель.
		const top = (TITLE?.anchorY ?? 0.575) - Math.max(0, title.lines.length - 2) * 0.045;
		for (const [i, line] of title.lines.entries()) {
			const text = line.pieces.map((p) => p.text).join(' ');
			const tier = line.pieces[0]?.kind === 'badge' ? TITLE.badge : TITLE.big;
			const size = tier.size * titleScale(title.lines);
			// Строки идут вверх от опоры: первая выше всех.
			const topY = top - ((title.lines.length - i) * size * 1.06) / height;
			const verdict = fits({text, size, topY, uppercase: true, frameW: width, frameH: height});
			if (!verdict.ok) {
				problems.push({
					что: 'строка плашки',
					текст: text,
					ширеНа: Number((verdict.overWidth * 100).toFixed(1)),
					нижеНа: Number((verdict.overBottom * 100).toFixed(1)),
				});
			}
		}
	}

	// Субтитры: ширину компонент ограничивает сам, но высота зависит от
	// того, куда встал текст — на груди или выше, поверх врезки.
	for (const topY of [SUB.topY, SUB.onCardTopY]) {
		const size = SUB.accent.size * (SUB.growTo ?? 1);
		if (topY + size / height > 1 - SAFE.bottom) {
			problems.push({
				что: 'субтитр',
				текст: `кегль ${Math.round(size)} на высоте ${topY}`,
				нижеНа: Number(((topY + size / height - (1 - SAFE.bottom)) * 100).toFixed(1)),
			});
		}
	}

	return problems;
};

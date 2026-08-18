// СУБТИТРЫ.
//
// Четыре манеры на выбор — какую взять, решает модель под содержание
// ролика. Раньше манера была одна на всё, и любой ролик выглядел
// одинаково, чем бы он ни был.
//
//   по-слову  В кадре ровно одно слово — то, что звучит сейчас. Слово
//             под голосом читается само, глаз не бегает по строке и не
//             читает наперёд. Но длинную мысль такая подача дробит.
//
//   по-фразе  Реплика целиком. Спокойнее и легче читается — для
//             рассуждения, где важен ход мысли, а не удар.
//
//   караоке   Реплика висит, произносимое слово подсвечено. Даёт и
//             прочитать фразу, и следить за голосом.
//
//   крупно    Два-три слова во весь кадр. Работает только на рубленых
//             фразах: длинную не вместит.
//
// Тайминги везде из распознавания: у каждого слова своя секунда.

import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {SAFE, SUB} from './style.js';
import {MANNER} from './manner.js';

// Прикидка ширины без замеров в DOM — чтобы длинные слова вроде
// «БЕСПРОЦЕНТНЫХ» сами ужимались и не резались о края кадра.
const CHAR_W = {caps: 0.74, lower: 0.62, other: 0.36};

const estimateWidth = (text, tier, size) => {
	const s = tier.uppercase ? text.toUpperCase() : text;
	let units = 0;
	for (const ch of s) {
		if (/[A-ZА-ЯЁ0-9]/.test(ch)) units += CHAR_W.caps;
		else if (/[a-zа-яё]/.test(ch)) units += CHAR_W.lower;
		else units += CHAR_W.other;
	}
	return units * size;
};

// ── сколько группа живёт на экране ───────────────────────────
// Короткие служебные слова звучат по десятой доле секунды. Показывать
// их столько же — мельтешение, которое глаз не успевает прочесть.
const MIN_HOLD = 0.26;
// Пауза длиннее этой — конец мысли: экран пустеет, а не тянет слово.
const MAX_HOLD = 0.9;

// Появление и уход. Значения нарочно маленькие: на вертикальном видео
// длинные переходы читаются как задержка, а не как плавность.
const IN = 0.13;
const OUT = 0.1;

// Сколько слов показывать разом в манере «крупно». Больше трёх во весь
// кадр не влезает, меньше двух — то же самое, что по слову.
const BIG_WORDS = 3;

// Сколько строк разрешено занимать группе. Одно слово — одна строка,
// фразе нужно место, но не полкадра: ниже начинается подпись площадки.
const LINES = {'по-слову': 1, 'крупно': 2, 'по-фразе': 3, 'караоке': 3};

// ── что показывать разом ─────────────────────────────────────
// В зависимости от манеры группа — это одно слово, кусок реплики или
// реплика целиком.
const groupsOf = (chunks, subs) => {
	if (subs === 'по-фразе' || subs === 'караоке') {
		return chunks.filter((c) => c.words?.length).map((chunk) => ({words: chunk.words}));
	}

	const flat = chunks.flatMap((chunk) => chunk.words ?? []);
	if (subs === 'крупно') {
		// Режем по репликам, а не сквозняком: иначе в одну группу попадут
		// хвост одной мысли и начало другой.
		const out = [];
		for (const chunk of chunks) {
			const words = chunk.words ?? [];
			for (let i = 0; i < words.length; i += BIG_WORDS) {
				out.push({words: words.slice(i, i + BIG_WORDS)});
			}
		}
		return out;
	}

	return flat.map((word) => ({words: [word]}));
};

// Границы показа. Группа держится до следующей, но не дольше, чем
// молчание после неё, — иначе текст висит над уже пустой речью.
const timeline = (chunks, subs) => {
	const groups = groupsOf(chunks, subs).filter((g) => g.words.length);

	return groups.map((group, i) => {
		const first = group.words[0];
		const last = group.words[group.words.length - 1];
		const next = groups[i + 1]?.words[0];
		const natural = Math.max(last.end, first.start + MIN_HOLD);

		return {
			words: group.words,
			from: first.start,
			until: next
				? Math.min(Math.max(next.start, first.start + MIN_HOLD), last.end + MAX_HOLD)
				: natural + 0.35,
		};
	});
};

// Кегль под группу: самое длинное слово должно влезать в строку, а вся
// группа — в отведённое число строк. Берём меньшее из двух.
//
// Ширину каждого слова считаем по тому ярусу, которым его и нарисуют.
// Подсвеченное слово идёт заглавными, а заглавные заметно шире строчных:
// если мерить всю группу базовым ярусом, подсвеченное слово вылезает за
// край кадра и ему срезает первую букву.
const fitSize = (words, tierOf, maxPx, maxLines) => {
	const widths = words.map((w) => {
		const tier = tierOf(w);
		// Приводим к общему кеглю: рисуем все слова одним размером, значит
		// и мерить их надо в одном масштабе.
		return (estimateWidth(w.word ?? w.text, tier, tier.size) / tier.size);
	});

	const base = tierOf(words[0]).size;
	const longest = Math.max(...widths);
	const total = widths.reduce((a, b) => a + b, 0) + 0.32 * Math.max(0, words.length - 1);

	const byWord = maxPx / Math.max(0.01, longest);
	const byAll = (maxPx * maxLines) / Math.max(0.01, total);

	return Math.min(base * SUB.growTo, Math.max(base * SUB.minFit, Math.min(byWord, byAll)));
};

export const Subtitles = ({chunks, time, fromSeconds, isAccent, brollAt, look, manner}) => {
	useCurrentFrame();
	const {width, height} = useVideoConfig();

	const subs = manner?.subs ?? MANNER.subs;
	const groups = timeline(chunks, subs);
	const group = groups.find((g) => time >= g.from && time < g.until);
	if (!group) return null;

	// Оформление у каждого ролика своё: палитра, высота строки, шрифт.
	// Без него берётся стиль-кит — так студия открывается как раньше.
	const accentTier = look
		? {...SUB.accent, gradient: look.palette.accent, font: look.font.accent}
		: SUB.accent;
	const baseTier = look ? {...SUB.base, font: look.font.base} : SUB.base;

	// Каким ярусом рисуется каждое слово. В караоке подсвечено то, что
	// звучит прямо сейчас; в остальных манерах — то, что модель отметила
	// акцентом. Эта же функция идёт в расчёт кегля, поэтому измеренное и
	// нарисованное не расходятся.
	const litNow = (word, i) =>
		time >= word.start &&
		(i === group.words.length - 1 || time < group.words[i + 1].start);

	const tierOf = (word) => {
		const i = group.words.indexOf(word);
		const lit = subs === 'караоке' ? litNow(word, i) : isAccent(word.start);
		return lit ? accentTier : baseTier;
	};

	// Высота выбирается по началу группы: если под ней врезка, текст
	// уходит выше, чтобы не сесть на чужую картинку.
	const topY = brollAt(group.from) ? SUB.onCardTopY : (look?.layout.topY ?? SUB.topY);

	// Меряем не по текущему кадру, а по худшему.
	//
	// В караоке подсветка едет по словам, и если считать кегль по тому,
	// что подсвечено сейчас, фраза меняла бы размер на каждом слове —
	// текст дёргался бы весь ролик. Поэтому считаем так, будто заглавным
	// станет каждое слово: размер получается один на всю жизнь группы и
	// заведомо влезает.
	const measure = subs === 'караоке' ? () => accentTier : tierOf;

	const maxPx = width * SUB.maxWidth;
	const size = fitSize(group.words, measure, maxPx, LINES[subs] ?? 1);

	const life = group.until - group.from;
	const enter = Math.min(IN, life / 3);
	const leave = Math.min(OUT, life / 3);

	// Приход и уход считаем по времени, а не пружиной: группа живёт доли
	// секунды, и пружина не успевает дойти до покоя — получается дёрганье.
	const appear = interpolate(time, [group.from, group.from + enter], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const fade = interpolate(time, [group.until - leave, group.until], [1, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	const opacity = Math.min(appear, fade);
	// Всплывает снизу и слегка растёт — движение читается как «сказано»,
	// а не как «выехала плашка». Фраза целиком поднимается меньше:
	// большой блок, ползущий вверх, читается тяжело.
	const single = group.words.length === 1;
	const rise = interpolate(appear, [0, 1], [single ? SUB.riseFrom : SUB.riseFrom * 0.45, 0]);
	const scale = interpolate(appear, [0, 1], [single ? 0.88 : 0.96, 1]);

	const paintOf = (t) =>
		t.gradient
			? {
					backgroundImage: t.gradient,
					WebkitBackgroundClip: 'text',
					backgroundClip: 'text',
					WebkitTextFillColor: 'transparent',
					color: 'transparent',
				}
			: {color: t.color};

	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				top: height * topY,
				// центрируем по видимой части кадра, а не по кадру целиком:
				// справа колонка кнопок, и текст должен стоять по центру того,
				// что зритель реально видит
				transform: `translateX(${(SAFE.centerX - 0.5) * width}px)`,
				display: 'flex',
				justifyContent: 'center',
				filter: SUB.shadow,
			}}
		>
			<div
				style={{
					display: 'flex',
					flexWrap: 'wrap',
					justifyContent: 'center',
					alignItems: 'baseline',
					columnGap: size * 0.26,
					rowGap: size * 0.1,
					maxWidth: maxPx,
					transform: `translateY(${rise}px) scale(${scale})`,
					transformOrigin: 'center bottom',
					opacity,
				}}
			>
				{group.words.map((word, i) => {
					const text = word.word ?? word.text;

					// Караоке: подсвечено то слово, которое звучит прямо
					// сейчас. Остальные приглушены — иначе фраза читается
					// как одна ровная строка и следить не за чем.
					const now = subs === 'караоке' && litNow(word, i);
					const wordTier = subs === 'караоке' ? (now ? accentTier : baseTier) : tierOf(word);
					const dim = subs === 'караоке' && !now ? 0.45 : 1;

					return (
						<span
							key={`${word.start}-${i}`}
							style={{
								display: 'inline-block',
								fontFamily: wordTier.font,
								fontWeight: wordTier.weight,
								fontSize: size,
								letterSpacing: '-0.01em',
								whiteSpace: 'nowrap',
								opacity: dim,
								...paintOf(wordTier),
							}}
						>
							{wordTier.uppercase ? String(text).toUpperCase() : text}
						</span>
					);
				})}
			</div>
		</div>
	);
};

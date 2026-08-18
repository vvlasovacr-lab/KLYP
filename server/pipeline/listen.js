// СЛУШАЕМ ИСХОДНИК.
//
// Раньше здесь стоял отдельный монтажный движок на Python. Он делал
// много всего: сцены, речевой монтаж, движения камеры, подбор врезок,
// вёрстку субтитров. Но к готовому ролику из этого не доходило ничего:
// картинку рисуют наши компоненты, разметку придумывает модель, паузы
// срезаются раньше него. От движка оставались только слова с таймингами
// — и те он получал нашим же ключом.
//
// Здесь эти слова берутся напрямую. Всё, что нужно дальше по трубе, —
// расшифровка, разбитая на реплики.

import {transcribe} from './transcribe.js';

// Длинная реплика неудобна и модели, и вёрстке: в одну строку не влезет,
// а по смыслу дробится. Режем там, где человек и сам сделал бы паузу —
// на точке, вопросе или после долгой тишины.
const MAX_WORDS = 9;
const MAX_SECONDS = 4.5;

const ENDING = /[.!?…]$/;

// ВЫДУМАННЫЕ РЕПЛИКИ.
//
// На музыке, шуме и тишине распознавание не молчит — оно подставляет то,
// что чаще всего встречалось в обучении. В русских роликах это подписи
// переводчиков и концовки с ютуба: «Субтитры сделал DimaTorzok»,
// «Редактор субтитров А.Синецкая», «Спасибо за просмотр». Человек их не
// говорил, но в расшифровку они попадают как настоящая речь — и дальше
// уезжают в субтитры готового ролика.
//
// Ловится это надёжно: набор фраз небольшой и повторяется дословно.
// Проверяем всю реплику целиком, а не отдельные слова, — «субтитры» само
// по себе слово нормальное, и вырезать его везде нельзя.
const INVENTED = [
	/^субтитры\b.*(сделал|делал|создавал|подготовил)/i,
	/dimatorzok/i,
	/^(редактор|корректор)\s+субтитров/i,
	/^субтитры\s+(и\s+)?перевод/i,
	/amara\.org/i,
	/^(спасибо за просмотр|продолжение следует|подписывайтесь на канал)/i,
	/^(thanks for watching|subtitles by|please subscribe)/i,
	/^музыка$/i,
	/^\(?(музыка|аплодисменты|смех)\)?[.!]?$/i,
];

const invented = (text) => {
	const line = String(text ?? '').trim();
	if (!line) return true;
	return INVENTED.some((rule) => rule.test(line));
};

const split = (chunks) => {
	const out = [];

	for (const chunk of chunks) {
		let buffer = [];

		const flush = () => {
			if (!buffer.length) return;
			out.push({
				start: buffer[0].start,
				end: buffer[buffer.length - 1].end,
				type: 'NORMAL',
				words: buffer,
			});
			buffer = [];
		};

		for (const word of chunk.words) {
			buffer.push(word);
			const long = buffer.length >= MAX_WORDS;
			const slow = buffer[buffer.length - 1].end - buffer[0].start >= MAX_SECONDS;
			if (ENDING.test(String(word.text ?? '').trim()) || long || slow) flush();
		}

		flush();
	}

	return out;
};

// План в том виде, в каком его ждёт перевод разметки. Поля, которые
// заполнял движок, остаются пустыми — их содержимое всё равно строилось
// нами или моделью:
//
//   speechEdit — паузы уже срезаны из файла до этого шага
//   camera     — ритм склеек считается по акцентам
//   broll      — врезки выбирает модель по смыслу речи
//   face       — никем не читалось
export const shape = (scenes, duration) => ({
	scenes,
	source: {duration},
	output: {duration},
	speechEdit: {timeline: [], hook: null},
	camera: [],
	broll: [],
	face: null,
});

export const listen = async (file) => {
	const heard = await transcribe(file);

	const all = split(heard.chunks ?? []);

	// Выдуманное убираем до всего остального: иначе оно уедет и в
	// расшифровку на вычитку, и в субтитры, и в заголовок.
	const real = all.filter(
		(scene) => !invented(scene.words.map((w) => w.text).join(' '))
	);

	const dropped = all.length - real.length;
	if (dropped) {
		console.log(`  распознавание: убрано выдуманных реплик ${dropped} из ${all.length}`);
	}

	const scenes = real.map((scene) => ({
		start: scene.start,
		end: scene.end,
		type: scene.type,
		layout: {position: 'lower'},
		words: scene.words.map((word) => ({
			word: word.text,
			start: word.start,
			end: word.end,
		})),
	}));

	return {
		montage: shape(scenes, heard.duration),
		provider: heard.provider ?? 'silence',
		words: heard.words ?? 0,
		ms: heard.ms ?? 0,
		error: heard.error ?? null,
	};
};

// ПРАВКА РАСШИФРОВКИ.
//
// Распознавание ошибается на именах, названиях и аббревиатурах: «ООшка»
// приезжает как «уОшка», и дальше эта ошибка расходится по всему ролику
// — в субтитры, в заголовок, в выбор врезок. На потоке это дороже всего:
// клиент платит второй ролик за то, чтобы починить одно слово.
//
// Поэтому текст показывается до монтажа и его можно поправить. Здесь
// исправленная строка возвращается обратно в слова с таймингами.
//
// Слов после правки может стать больше или меньше: человек склеивает
// «пол года» в «полгода» или разбивает слипшееся. Когда счёт сошёлся,
// тайминги садятся один в один. Когда нет — реплика делится по длине
// слов: длинное слово звучит дольше короткого, и на глаз это не
// расходится, потому что реплика и так меньше пяти секунд.
const spread = (words, from, to) => {
	const weights = words.map((w) => Math.max(1, w.length));
	const total = weights.reduce((a, b) => a + b, 0);
	const span = Math.max(0.05, to - from);

	let at = from;
	return words.map((word, i) => {
		const end = i === words.length - 1 ? to : at + (span * weights[i]) / total;
		const piece = {word, start: Number(at.toFixed(3)), end: Number(end.toFixed(3))};
		at = end;
		return piece;
	});
};

export const retext = (scene, text) => {
	const words = String(text ?? '').trim().split(/\s+/).filter(Boolean);

	// Реплику вычистили целиком — значит человек считает, что этих слов в
	// ролике нет. Пустую реплику дальше по трубе не пускаем.
	if (!words.length) return null;

	const was = Array.isArray(scene.words) ? scene.words : [];

	// Счёт сошёлся — меняем только написание, тайминги родные.
	if (words.length === was.length) {
		return {...scene, words: was.map((w, i) => ({...w, word: words[i]}))};
	}

	return {...scene, words: spread(words, scene.start, scene.end)};
};

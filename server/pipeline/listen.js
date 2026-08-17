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
export const listen = async (file) => {
	const heard = await transcribe(file);

	const scenes = split(heard.chunks ?? []).map((scene) => ({
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
		montage: {
			scenes,
			source: {duration: heard.duration},
			output: {duration: heard.duration},
			speechEdit: {timeline: [], hook: null},
			camera: [],
			broll: [],
			face: null,
		},
		provider: heard.provider ?? 'silence',
		words: heard.words ?? 0,
		ms: heard.ms ?? 0,
		error: heard.error ?? null,
	};
};

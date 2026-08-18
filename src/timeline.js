// МОНТАЖНЫЙ ПЛАН РОЛИКА.
//
// Раньше разметка жила в accents.js / broll.js / cuts.json — то есть была
// намертво привязана к одному конкретному видео. Теперь она приходит
// в пропсах, а эти файлы остались только как образец для студии.
//
// Здесь план приводится к рабочему виду и превращается в набор функций
// «что происходит в этот момент времени». Компоненты спрашивают
// у плана, а не импортируют разметку напрямую.

import {ACCENTS, SHOUTS} from './accents.js';
import {BROLL} from './broll.js';
import staticCuts from './cuts.json';

// План может прийти неполным — модель ошибается, шаблон чего-то
// не заполнил. Пустой список лучше падения на рендере.
const list = (value) => (Array.isArray(value) ? value : []);

export const emptyPlan = {
	accents: [],
	broll: [],
	shouts: [],
	cuts: [],
	title: null,
};

// Разметка из статических файлов — тот самый образцовый ролик.
// Используется в студии, когда план не передан.
export const demoPlan = {
	accents: ACCENTS,
	broll: BROLL,
	shouts: SHOUTS,
	cuts: staticCuts,
	title: null, // берётся из TITLE в стиль-ките
};

// Строки плашки принимаются в двух видах: со списком частей
// и плоские. Второй приводим к первому, чтобы компонент знал один формат.
const normalizeTitle = (title) => {
	if (!title || !Array.isArray(title.lines)) return null;
	return {
		...title,
		lines: title.lines.map((line, i) =>
			Array.isArray(line.pieces)
				? line
				: {dx: line.dx ?? 0, pieces: [{kind: line.kind ?? 'big', text: line.text ?? ''}]}
		),
	};
};

export const readPlan = (plan) => {
	const p = plan && typeof plan === 'object' ? plan : demoPlan;

	// Интервалы обязаны идти по возрастанию: cutAt ищет последнюю
	// метку до текущего момента и полагается на порядок.
	const cuts = list(p.cuts).slice().sort((a, b) => a.t - b.t);
	const accents = list(p.accents);
	const broll = list(p.broll).slice().sort((a, b) => a.from - b.from);
	const shouts = list(p.shouts);
	// Слова, которые надо увести на второй план: связки, вводные,
	// «ну вот», «то есть». В эталоне они идут заметно мельче сути.
	const quiet = list(p.quiet);

	return {
		title: normalizeTitle(p.title),

		// слово попадает в акцент, если его начало внутри интервала
		isAccent: (time) => accents.some(([from, to]) => time >= from && time < to),

		isQuiet: (time) => quiet.some(([from, to]) => time >= from && time < to),


		// моменты, на которых камера делает наезд
		accentStarts: accents.map(([from]) => from),

		brollAt: (time) => broll.find((b) => time >= b.from && time < b.to) ?? null,

		shoutAt: (time) => shouts.find((s) => time >= s.from && time < s.to) ?? null,

		// последняя склейка не позже текущего момента
		cutAt: (time) => {
			let found = null;
			for (const c of cuts) {
				if (c.t <= time + 0.0001) found = c;
				else break;
			}
			return found;
		},

		// сырые списки нужны звуковой дорожке
		raw: {accents, broll, shouts, cuts},
	};
};

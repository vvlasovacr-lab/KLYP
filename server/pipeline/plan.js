// Шаг 2: разметка ролика — что подсветить, где врезка, какая плашка.
//
// Работает без модели. Смысловое слово находится по признакам, которые
// видно прямо в тексте: цифра, длина, пауза перед словом, восклицание.
// Это даёт большую часть качества за ноль стоимости — модель понадобится
// позже и только там, где правила не справляются.
//
// Когда появится ANTHROPIC_API_KEY, здесь включится модельный плановщик.
// Формат ответа тот же, рендер разницы не заметит.

import {hasModel} from '../config.js';

// ── шаблоны монтажа ───────────────────────────────────────────
// Отличаются плотностью событий: сколько акцентов и врезок на минуту.
export const TEMPLATES = [
	{
		code: 'expose', title: 'Разоблачение',
		hint: 'Жёсткий заход, тревожные врезки, красные цифры',
		accentGap: 3.0, brollGap: 7, brollLen: 2.6, cutGap: 2.4, palette: 'wine',
	},
	{
		code: 'breakdown', title: 'Разбор',
		hint: 'Спокойный ритм, выписки и таблицы, много цифр',
		accentGap: 4.5, brollGap: 11, brollLen: 3.0, cutGap: 3.5, palette: 'steel',
	},
	{
		code: 'hook', title: 'Хук',
		hint: 'Взрыв на первой секунде, плашка, быстрая смена',
		accentGap: 2.4, brollGap: 6, brollLen: 2.2, cutGap: 1.9, palette: 'amber',
	},
	{
		code: 'case', title: 'Кейс',
		hint: 'Счётчики, растущий график, до и после',
		accentGap: 3.2, brollGap: 9, brollLen: 2.8, cutGap: 2.8, palette: 'green',
	},
	{
		code: 'warmup', title: 'Прогрев',
		hint: 'Мягкие переходы, тёплый свет, длинные планы',
		accentGap: 5.5, brollGap: 14, brollLen: 3.2, cutGap: 4.5, palette: 'sand',
	},
	{
		code: 'myths', title: 'Мифы',
		hint: 'Контраст, пункты по одному, финальный вывод',
		accentGap: 3.4, brollGap: 10, brollLen: 2.6, cutGap: 3.0, palette: 'violet',
	},
	{
		code: 'offer', title: 'Оффер',
		hint: 'Короткий, выкрик в кавычках, призыв в конце',
		accentGap: 2.6, brollGap: 7, brollLen: 2.4, cutGap: 2.2, palette: 'wine',
	},
];

export const findTemplate = (code) =>
	TEMPLATES.find((t) => t.code === code) ?? TEMPLATES[0];

// ── библиотека врезок ─────────────────────────────────────────
// Клип подбирается по словам в реплике. Файлы лежат в public/broll/.
// Добавляешь клип — дописываешь строку, больше ничего.
export const BROLL_LIBRARY = [
	{file: 'declined.mp4', keys: ['отказ', 'не проход', 'карт', 'терминал', 'оплат', 'банк', 'списа']},
	{file: 'cash-counter.mp4', keys: ['деньг', 'наличн', 'платёж', 'платеж', 'сумм', 'рубл', 'тысяч', 'зарплат']},
	{file: 'chart-red.mp4', keys: ['процент', 'ставк', 'долг', 'график', 'рост', 'растёт', 'кредит', 'переплат']},
	{file: 'shopping.mp4', keys: ['покупк', 'магазин', 'трат', 'шопинг', 'купи', 'потрат', 'вещи']},
	{file: 'scroll-feed.mp4', keys: ['телефон', 'лент', 'чат', 'соцсет', 'подписчик', 'комьюнити', 'сообществ', 'канал']},
	{file: 'signing.mp4', keys: ['договор', 'документ', 'подпис', 'юрист', 'банкротств', 'суд', 'услови']},
];

// ── разбор текста ─────────────────────────────────────────────

const clean = (s) => String(s).toLowerCase().replace(/[^\p{L}\p{N}%]/gu, '');
const letters = (s) => String(s).replace(/[^\p{L}\p{N}]/gu, '').length;

// Служебные слова никогда не выносим крупным планом: подсветка
// предлога выглядит как ошибка вёрстки, а не как акцент.
const STOP = new Set(
	`и а но да или же бы ли не ни в во на за под над при про с со к ко у о об обо из от до для без через между
	 что чтобы как когда если то это этот эта эти тот та те так вот уже ещё там тут
	 я ты он она оно мы вы они мне тебе ему ей нам вам им меня тебя его её нас вас их
	 кто кого кому те тех тем свой своя мой твой наш ваш был была было были есть быть
	 очень просто только даже тоже`.split(/\s+/)
);

const HAS_DIGIT = /[0-9%]/;

// Насколько слово тянет на смысловое.
const scoreWord = (word, prevWord) => {
	const w = clean(word.text);
	if (!w || STOP.has(w)) return 0;

	let score = 0;

	// Цифра почти всегда и есть суть: «80%», «145 тысяч», «три ошибки»
	if (HAS_DIGIT.test(word.text)) score += 60;

	// Длинное слово несёт больше смысла, чем короткое
	const len = letters(word.text);
	if (len >= 11) score += 34;
	else if (len >= 8) score += 22;
	else if (len >= 6) score += 12;
	else if (len <= 3) score -= 14;

	// Пауза перед словом — человек сам его выделил голосом
	if (prevWord) {
		const pause = word.start - prevWord.end;
		if (pause > 0.45) score += 30;
		else if (pause > 0.25) score += 16;
	}

	// Восклицание или вопрос рядом — эмоциональная точка
	if (/[!?]/.test(word.text)) score += 24;

	// Слова-усилители: рядом с ними обычно стоит вывод
	if (/^(никогда|всегда|никто|нельзя|обязательно|главн|важн|запомн)/.test(w)) score += 26;

	return score;
};

// Отбор акцентов: сначала по весу, потом прореживание по времени.
// Без прореживания подсветка сливается и перестаёт работать.
const pickAccents = (chunks, tpl, duration) => {
	const all = [];
	let prev = null;

	for (const chunk of chunks) {
		for (const word of chunk.words) {
			if (!word.text) continue;
			const score = scoreWord(word, prev);
			if (score > 0) all.push({word, score});
			prev = word;
		}
	}

	// порог отсекает середнячков: подсвечивать половину слов бессмысленно
	const strong = all.filter((x) => x.score >= 18).sort((a, b) => b.score - a.score);

	const taken = [];
	for (const {word} of strong) {
		if (taken.some((t) => Math.abs(t.start - word.start) < tpl.accentGap)) continue;
		taken.push(word);
		if (taken.length >= Math.ceil(duration / tpl.accentGap)) break;
	}

	return taken
		.sort((a, b) => a.start - b.start)
		.map((w) => [
			Number(w.start.toFixed(2)),
			Number((w.start + 0.02).toFixed(2)),
			w.text,
		]);
};

// ── врезки ────────────────────────────────────────────────────

// Ищет в реплике слово из словаря и возвращает подходящий клип.
const matchClip = (chunk, library) => {
	const words = chunk.words.map((w) => clean(w.text)).filter(Boolean);
	for (const item of library) {
		// сравнение по началу слова, а не по подстроке всей реплики:
		// иначе ключ «рост» срабатывает внутри «просто»
		if (words.some((w) => item.keys.some((k) => w.startsWith(k)))) {
			return item.file;
		}
	}
	return null;
};

const pickBroll = ({chunks, library, tpl, duration}) => {
	if (!library.length) return [];

	const shots = [];
	let lastEnd = -Infinity;

	for (const chunk of chunks) {
		// первые секунды заняты титульной плашкой, последние — призывом
		if (chunk.start < 4 || chunk.start > duration - 4) continue;
		if (chunk.start - lastEnd < tpl.brollGap) continue;

		const file = matchClip(chunk, library);
		if (!file) continue;

		const from = Number(chunk.start.toFixed(2));
		const to = Number(Math.min(from + tpl.brollLen, duration - 1).toFixed(2));
		if (to - from < 1.2) continue;

		shots.push({from, to, file, startFrom: 0});
		lastEnd = to;
	}

	return shots;
};

// ── склейки ───────────────────────────────────────────────────
// Вход и выход каждой врезки — обязательные метки. Между ними
// добавляем ритмические, чтобы кадр не застаивался.
const buildCuts = ({broll, tpl, duration}) => {
	const cuts = [];

	for (const shot of broll) {
		cuts.push({t: Number(shot.from.toFixed(2)), kind: 'broll'});
		cuts.push({t: Number(shot.to.toFixed(2)), kind: 'back'});
	}

	const inBroll = (t) => broll.some((b) => t >= b.from - 0.3 && t <= b.to + 0.3);
	for (let t = tpl.cutGap; t < duration - 1; t += tpl.cutGap) {
		if (inBroll(t)) continue;
		cuts.push({t: Number(t.toFixed(2)), kind: 'base'});
	}

	return cuts.sort((a, b) => a.t - b.t);
};

// ── титульная плашка ──────────────────────────────────────────
// Длинные слова идут крупным планом, короткие — на красные бейджи.
// Так строка не расползается и держит ритм оригинала.
const buildTitle = (title, duration) => {
	const words = String(title || 'Новый ролик').split(/\s+/).filter(Boolean).slice(0, 8);
	const lines = [];
	let buf = [];

	// Бейджи слегка разъезжаются в стороны — ровная колонка выглядит
	// мёртвой, а сдвиг даёт строю живость.
	const DX = [0, 78, -10, -72];

	const flush = (kind) => {
		if (!buf.length) return;
		lines.push({
			dx: DX[lines.length] ?? 0,
			pieces: [{kind, text: buf.join(' ')}],
		});
		buf = [];
	};

	for (const w of words) {
		buf.push(w);
		const long = buf.join(' ').length;
		if (long >= 11) flush(lines.length % 2 === 0 ? 'big' : 'badge');
	}
	flush(lines.length % 2 === 0 ? 'big' : 'badge');

	return {
		in: 0.15,
		out: Math.min(3.5, Math.max(2, duration * 0.08)),
		lines: lines.slice(0, 4),
	};
};

// ── слово-выкрик ──────────────────────────────────────────────
// Ищем призыв в конце: «напиши слово ЧАТ», «пиши КЕЙС».
// Без явного призыва выкрик не ставим — он был бы шумом.
const CALL = /^(напиш|пиши|пишите|ставь|отправ|жми)/;
const MARKER = /^(слово|кодовое)$/;

const pickShout = (chunks, duration) => {
	// Призыв всегда в конце: ищем только в последней трети.
	const tail = chunks.filter((c) => c.start > duration * 0.6);
	const words = tail.flatMap((c) => c.words).filter((w) => w.text);

	const take = (w) => [{
		from: Number(w.start.toFixed(2)),
		to: Number((w.start + 1.1).toFixed(2)),
		text: w.text.toUpperCase().replace(/[^\p{L}\p{N}]/gu, ''),
	}];

	const next = (from) => {
		for (let j = from; j < words.length; j++) {
			const c = clean(words[j].text);
			if (!c || STOP.has(c) || MARKER.test(c) || CALL.test(c)) continue;
			if (c.length < 3) continue;
			return words[j];
		}
		return null;
	};

	// Сначала прямое указание: «…слово ЧАТ». Оно точнее любого другого
	// признака, поэтому проверяется первым.
	for (let i = 0; i < words.length - 1; i++) {
		if (MARKER.test(clean(words[i].text))) {
			const w = next(i + 1);
			if (w) return take(w);
		}
	}

	// Иначе первое значимое слово после призыва.
	for (let i = 0; i < words.length - 1; i++) {
		if (CALL.test(clean(words[i].text))) {
			const w = next(i + 1);
			if (w) return take(w);
		}
	}

	return [];
};

// ── сборка ────────────────────────────────────────────────────

const planByTemplate = ({chunks, duration, template, title, marks, library}) => {
	const tpl = findTemplate(template);

	const broll = pickBroll({chunks, library: library ?? [], tpl, duration});
	let accents = pickAccents(chunks, tpl, duration);
	const shouts = pickShout(chunks, duration);

	// Метки правок снимают подсветку: там, где клиент отметил проблему,
	// чаще всего мешает именно она.
	for (const m of marks ?? []) {
		const at = Number(m.at_sec);
		accents = accents.filter((a) => Math.abs(a[0] - at) >= 1.2);
	}

	// Под выкриком обычные титры не показываются — акценты там лишние.
	for (const s of shouts) {
		accents = accents.filter((a) => a[0] < s.from || a[0] >= s.to);
	}

	return {
		version: 1,
		provider: 'rules',
		template: tpl.code,
		palette: tpl.palette,
		duration,
		title: buildTitle(title, duration),
		chunks,
		accents,
		broll,
		shouts,
		cuts: buildCuts({broll, tpl, duration}),
	};
};

export const buildPlan = async (input) => {
	if (hasModel()) {
		const {planByModel} = await import('./plan-model.js').catch(() => ({}));
		if (planByModel) return planByModel(input);
	}
	return planByTemplate(input);
};

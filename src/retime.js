// ПЕРЕСБОРКА РЕПЛИК.
// Whisper режет речь как попало: строка висит, когда человек говорит дальше,
// а обрывается посреди мысли — «И большинство попадает в». Здесь строки
// собираются по смысловым швам: по знакам препинания, по паузам в речи
// и так, чтобы на конце строки не оставался предлог или союз.
// Оригинальный chunks.json не трогается: всё считается на лету.

import {TIMING} from './style.js';

// слова, которые не должны оставаться в конце строки —
// они тянут за собой следующее и без него не читаются
const HANGING = new Set(
	`и а но да или же бы ли не ни в во на за под над при про с со к ко у о об обо из от до для без через между
	 что чтобы как когда если то это этот эта эти тот та те мой твой свой наш ваш
	 я ты он она оно мы вы они мне тебе ему ей нам вам им меня тебя его её нас вас их
	 кто кого кому те тех тем`.split(/\s+/)
);

// новая мысль почти всегда начинается с большой буквы —
// склеивать её с хвостом предыдущей нельзя
const STARTS_PHRASE = (word) => /^[А-ЯЁA-Z]/.test(word?.text ?? '');

const ENDS_SENTENCE = /[.!?…]["»)]?$/;
const ENDS_CLAUSE = /[,;:—–-]$/;

const clean = (s) => s.toLowerCase().replace(/[^\p{L}\p{N}-]/gu, '');
const letters = (s) => s.replace(/[^\p{L}\p{N}]/gu, '').length || 1;

// сколько слово звучит на самом деле, а не сколько ему приписал whisper
const realEnd = (word) => {
	const natural = Math.max(TIMING.minWord, letters(word.text) * TIMING.perLetter);
	return Math.min(word.end, word.start + natural);
};

// насколько хорош разрыв после слова с индексом i
const seamScore = (words, i, lineLength) => {
	const last = words[i];
	const next = words[i + 1];
	let score = 0;

	if (ENDS_SENTENCE.test(last.text)) score += 120;
	else if (ENDS_CLAUSE.test(last.text)) score += 45;
	if (last.lastInChunk) score += 25;

	// следующее слово с большой буквы — там начинается новая мысль
	if (STARTS_PHRASE(next)) score += 85;

	// пауза в речи — самый честный шов
	if (next) score += Math.min(35, Math.max(0, next.start - last.end) * 120);

	// обрывать мысль на предлоге нельзя
	if (next && HANGING.has(clean(last.text))) score -= 90;

	// и держим строку близкой к целевой длине,
	// но перебор лучше, чем повисший предлог
	const over = Math.max(0, lineLength - TIMING.maxWords);
	score -= Math.abs(lineLength - TIMING.maxWords) * 7 + over * 11;

	return score;
};

export const retime = (chunks) => {
	const words = [];
	chunks.forEach((chunk) =>
		chunk.words.forEach((w, wi) =>
			words.push({...w, lastInChunk: wi === chunk.words.length - 1})
		)
	);

	const lines = [];
	let i = 0;

	while (i < words.length) {
		// докуда вообще можно тянуть строку — с запасом,
		// чтобы было куда уехать от плохого шва
		let span = 0;
		while (i + span < words.length && span < TIMING.maxWords + TIMING.stretch) {
			const w = words[i + span];
			if (span > 0 && realEnd(w) - words[i].start > TIMING.maxDur) break;
			// новая мысль начинается — предыдущую строку сюда не тянем
			if (span > 0 && STARTS_PHRASE(w)) break;
			span++;
			if (ENDS_SENTENCE.test(w.text)) break; // конец фразы — дальше не идём
		}
		span = Math.max(1, span);

		// и где внутри этого куска шов удачнее всего
		let take = span;
		let best = -Infinity;
		for (let len = 1; len <= span; len++) {
			const score = seamScore(words, i + len - 1, len);
			if (score > best) {
				best = score;
				take = len;
			}
		}

		const group = words.slice(i, i + take);
		lines.push({
			start: group[0].start,
			end: realEnd(group[group.length - 1]) + TIMING.tail,
			words: group,
			hardEnd: ENDS_SENTENCE.test(group[group.length - 1].text),
		});
		i += take;
	}

	// строка не должна налезать на следующую
	for (let i = 0; i < lines.length - 1; i++) {
		lines[i].end = Math.min(lines[i].end, lines[i + 1].start);
	}

	// огрызок в одно короткое слово мигает — клеим к соседней,
	// но никогда через конец фразы
	const merged = [];
	for (const line of lines) {
		const prev = merged[merged.length - 1];
		const short = line.end - line.start < TIMING.minShow;
		const fits =
			prev &&
			!prev.hardEnd &&
			!STARTS_PHRASE(line.words[0]) && // новая мысль — клеить нельзя
			line.end - prev.start <= TIMING.mergeDur &&
			prev.words.length + line.words.length <= TIMING.mergeWords &&
			prev.end >= line.start;
		if (short && fits) {
			prev.words = [...prev.words, ...line.words];
			prev.end = line.end;
			prev.hardEnd = line.hardEnd;
		} else {
			merged.push({...line});
		}
	}

	// начало новой мысли назад приклеить нельзя — тогда клеим его вперёд,
	// иначе «Кстати» мелькнёт на десятую долю секунды и пропадёт
	const joined = [];
	for (let i = 0; i < merged.length; i++) {
		const cur = merged[i];
		const next = merged[i + 1];
		const short = cur.end - cur.start < TIMING.minShow;
		const fits =
			next &&
			!cur.hardEnd &&
			cur.words.length + next.words.length <= TIMING.maxWords + TIMING.stretch &&
			next.end - cur.start <= TIMING.mergeDur;
		if (short && fits) {
			joined.push({...next, start: cur.start, words: [...cur.words, ...next.words]});
			i++;
		} else {
			joined.push(cur);
		}
	}

	// то, что склеить не вышло, просто держим на экране подольше
	for (let i = 0; i < joined.length; i++) {
		const limit = i + 1 < joined.length ? joined[i + 1].start : Infinity;
		joined[i].end = Math.min(
			limit,
			Math.max(joined[i].end, joined[i].start + TIMING.minShow)
		);
	}

	return joined;
};

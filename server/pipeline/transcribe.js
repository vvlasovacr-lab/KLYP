// Шаг 1: расшифровка речи с пословными таймингами.
//
// Провайдер выбирается переменной SPEECH_PROVIDER:
//   openai | groq | custom — сервис распознавания. Все трое говорят
//              на одном протоколе, различаются адресом и моделью,
//              поэтому код у них общий (см. SPEECH_PRESETS в config).
//   silence  — фолбэк без ключа. Находит границы реплик по паузам,
//              но текста не знает: субтитры выйдут пустыми.
//
// Все возвращают один формат, поэтому дальше по пайплайну разницы нет:
//   { duration, chunks: [{start, end, words: [{text, start, end}]}],
//     provider, words, ms }

import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {config, hasSpeech} from '../config.js';

const run = promisify(execFile);

export const probeDuration = async (file) => {
	const {stdout} = await run('ffprobe', [
		'-v', 'error',
		'-show_entries', 'format=duration',
		'-of', 'default=noprint_wrappers=1:nokey=1',
		file,
	]);
	return Number(String(stdout).trim()) || 0;
};

// ── подготовка аудио ──────────────────────────────────────────
// Видео весит десятки мегабайт, а у распознавания лимит на размер
// запроса. Вытаскиваем моно-дорожку 16 кГц в mp3: часовая запись
// укладывается в пару десятков мегабайт без потери разборчивости.
const extractAudio = async (videoFile) => {
	const out = path.join(os.tmpdir(), `speech-${process.pid}-${Date.now()}.mp3`);
	await run('ffmpeg', [
		'-v', 'error', '-y',
		'-i', videoFile,
		'-vn',                    // видео не нужно
		'-ac', '1',               // моно
		'-ar', '16000',           // распознаванию больше не требуется
		'-b:a', '64k',
		out,
	], {maxBuffer: 1024 * 1024 * 16});
	return out;
};

// ── провайдер: распознавание ──────────────────────────────────

// Часть сервисов не отдаёт пословные тайминги — только фразы.
// Тогда раскидываем слова внутри фразы пропорционально их длине:
// подсветка станет грубее, но текст на экране будет.
const wordsFromSegments = (segments) => {
	const out = [];

	for (const seg of segments ?? []) {
		const from = Number(seg.start);
		const to = Number(seg.end);
		const parts = String(seg.text ?? '').trim().split(/\s+/).filter(Boolean);
		if (!parts.length || !Number.isFinite(from) || !Number.isFinite(to)) continue;

		const weights = parts.map((p) => Math.max(1, p.length));
		const total = weights.reduce((a, b) => a + b, 0);

		let cursor = from;
		parts.forEach((text, i) => {
			const span = ((to - from) * weights[i]) / total;
			out.push({text, start: cursor, end: cursor + span});
			cursor += span;
		});
	}

	return out;
};

const byService = async (videoFile) => {
	const audio = await extractAudio(videoFile);

	try {
		const stat = await fs.stat(audio);
		const limitMb = config.speech.maxAudioMb;
		if (stat.size > limitMb * 1024 * 1024) {
			throw new Error(
				`Дорожка ${(stat.size / 1048576).toFixed(1)} МБ — больше лимита ${limitMb} МБ ` +
				`у провайдера ${config.speech.provider}. Нужно резать длинные записи на части.`
			);
		}

		const form = new FormData();
		form.append('file', new Blob([await fs.readFile(audio)], {type: 'audio/mpeg'}), 'speech.mp3');
		form.append('model', config.speech.model);
		form.append('response_format', 'verbose_json');
		// Без этого вернутся только фразы, а нам нужно каждое слово:
		// на пословных таймингах держится вся подсветка.
		if (config.speech.wordTimestamps) {
			form.append('timestamp_granularities[]', 'word');
		}
		if (config.speech.language) form.append('language', config.speech.language);

		const res = await fetch(config.speech.url, {
			method: 'POST',
			headers: {Authorization: `Bearer ${config.speech.apiKey}`},
			body: form,
		});

		const text = await res.text();
		if (!res.ok) {
			throw new Error(
				`${config.speech.provider} ответил ${res.status}: ${text.slice(0, 300)}`
			);
		}

		let data;
		try {
			data = JSON.parse(text);
		} catch {
			throw new Error(`${config.speech.provider} вернул не JSON: ${text.slice(0, 200)}`);
		}

		const raw = Array.isArray(data.words) && data.words.length
			? data.words
			: wordsFromSegments(data.segments);

		const words = raw
			.map((w) => ({
				text: String(w.word ?? w.text ?? '').trim(),
				start: Number(w.start),
				end: Number(w.end),
			}))
			.filter((w) => w.text && Number.isFinite(w.start) && Number.isFinite(w.end));

		if (!words.length) {
			throw new Error(`${config.speech.provider} не вернул ни одного слова`);
		}

		return {
			duration: Number(data.duration) || (await probeDuration(videoFile)),
			words,
			fullText: String(data.text ?? ''),
		};
	} finally {
		await fs.unlink(audio).catch(() => {});
	}
};

// Слова склеиваются в реплики по паузам. Дальше retime.js всё равно
// пересоберёт строки по смысловым швам, поэтому здесь достаточно
// грубой группировки — лишь бы не одна реплика на весь ролик.
const groupWords = (words, gap = 0.45) => {
	const chunks = [];
	let buf = [];

	const flush = () => {
		if (!buf.length) return;
		chunks.push({
			start: buf[0].start,
			end: buf[buf.length - 1].end,
			words: buf,
		});
		buf = [];
	};

	for (const w of words) {
		const prev = buf[buf.length - 1];
		if (prev && w.start - prev.end > gap) flush();
		buf.push(w);
	}
	flush();
	return chunks;
};

// ── провайдер: границы речи по громкости ──────────────────────
const findSilences = async (file) => {
	let out = '';
	try {
		const {stderr} = await run('ffmpeg', [
			'-v', 'info',
			'-i', file,
			'-af', 'silencedetect=noise=-30dB:d=0.35',
			'-f', 'null', '-',
		], {maxBuffer: 1024 * 1024 * 32});
		out = stderr;
	} catch (err) {
		out = err.stderr ?? '';
	}

	const silences = [];
	const re = /silence_start:\s*([\d.]+)|silence_end:\s*([\d.]+)/g;
	let m;
	let open = null;
	while ((m = re.exec(out))) {
		if (m[1] !== undefined) open = Number(m[1]);
		else if (open !== null) {
			silences.push([open, Number(m[2])]);
			open = null;
		}
	}
	return silences;
};

const bySilence = async (file) => {
	const duration = await probeDuration(file);
	const silences = await findSilences(file);

	const speech = [];
	let cursor = 0;
	for (const [from, to] of silences) {
		if (from - cursor > 0.4) speech.push([cursor, from]);
		cursor = to;
	}
	if (duration - cursor > 0.4) speech.push([cursor, duration]);
	if (!speech.length) speech.push([0, duration]);

	const chunks = [];
	for (const [from, to] of speech) {
		const len = to - from;
		const parts = Math.max(1, Math.round(len / 0.9));
		const step = len / parts;
		for (let i = 0; i < parts; i++) {
			const s = from + i * step;
			const e = s + step;
			chunks.push({
				start: Number(s.toFixed(2)),
				end: Number(e.toFixed(2)),
				words: [{text: '', start: Number(s.toFixed(2)), end: Number(e.toFixed(2))}],
			});
		}
	}
	return {duration, chunks, provider: 'silence', fullText: '', words: 0};
};

// ── публичный вход ────────────────────────────────────────────
// Возвращает ещё и метрики: сколько заняло и сколько слов вышло.
// Без них себестоимость ролика не посчитать.
export const transcribe = async (file) => {
	const started = Date.now();
	const done = (out, error = null) => ({...out, ms: Date.now() - started, error});

	if (!hasSpeech()) return done(await bySilence(file));

	try {
		const {duration, words, fullText} = await byService(file);
		return done({
			duration,
			chunks: groupWords(words),
			provider: config.speech.provider,
			fullText,
			words: words.length,
		});
	} catch (err) {
		// Ролик важнее текста: если распознавание отвалилось, собираем
		// без субтитров, но собираем. Причину пишем в лог и в базу.
		const message = String(err?.message ?? err);
		console.error(`  распознавание (${config.speech.provider}) не сработало: ${message}`);
		return done(await bySilence(file), message);
	}
};

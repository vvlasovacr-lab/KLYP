// Определение речи по звуку.
// Нужно, чтобы субтитр гас там, где человек реально замолчал,
// а не там, где whisper дорисовал границу слова.

import {execFileSync} from 'node:child_process';
import {readFileSync, unlinkSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const WIN = 0.02; // шаг анализа, сек

// огибающая громкости в dB с шагом WIN
export const envelope = (videoPath) => {
	const raw = join(tmpdir(), `vad-${process.pid}.raw`);
	execFileSync('ffmpeg', [
		'-v', 'error', '-y', '-i', videoPath,
		'-ac', '1', '-ar', '16000', '-f', 's16le', raw,
	]);
	const buf = readFileSync(raw);
	unlinkSync(raw);

	const sr = 16000;
	const step = Math.round(sr * WIN);
	const n = Math.floor(buf.length / 2 / step);
	const db = [];
	for (let i = 0; i < n; i++) {
		let sum = 0;
		for (let j = 0; j < step; j++) {
			const v = buf.readInt16LE((i * step + j) * 2) / 32768;
			sum += v * v;
		}
		db.push(10 * Math.log10(sum / step + 1e-12));
	}
	return db;
};

const percentile = (sorted, p) => sorted[Math.floor(sorted.length * p)];

// маска «здесь есть речь» по шагу WIN
export const voiceMask = (db, {smooth = 0.12, over = 9, bridge = 0.22} = {}) => {
	// микропаузы между слогами не должны читаться как тишина —
	// поэтому берём максимум по скользящему окну
	const r = Math.round(smooth / WIN);
	const peak = db.map((_, i) => {
		let m = -99;
		for (let j = Math.max(0, i - r); j <= Math.min(db.length - 1, i + r); j++) {
			if (db[j] > m) m = db[j];
		}
		return m;
	});

	const sorted = [...peak].sort((a, b) => a - b);
	const floor = percentile(sorted, 0.08); // шумовой пол
	const threshold = floor + over;

	const mask = peak.map((x) => (x > threshold ? 1 : 0));

	// сшиваем разрывы короче bridge — это дыхание, а не пауза
	const gap = Math.round(bridge / WIN);
	for (let i = 0; i < mask.length; i++) {
		if (mask[i]) continue;
		let j = i;
		while (j < mask.length && !mask[j]) j++;
		if (j - i <= gap && i > 0 && j < mask.length) {
			for (let k = i; k < j; k++) mask[k] = 1;
		}
		i = j - 1;
	}
	return {mask, threshold, floor, win: WIN};
};

export const WIN_SEC = WIN;

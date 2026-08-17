// ГЛАЗА.
//
// Модель читала только расшифровку — то есть монтировала вслепую. Она не
// знала, где в кадре человек, куда он смотрит, где пусто, когда меняет
// позу. Из-за этого текст всегда падал в одно и то же место, а склейки
// ставились по ритму речи, а не по картинке.
//
// Здесь из ролика вынимаются несколько кадров и уходят в запрос вместе с
// текстом. Проверял на живом ролике: по шести кадрам модель сказала, что
// низ занят руками и стулом, а свободен верх над головой — то есть ровно
// там, куда мы текст не ставили.

import {spawn} from 'node:child_process';
import fs from 'node:fs/promises';
import path from 'node:path';

// Кадры нужны не для красоты, а чтобы понять композицию. Ширины в 384
// точки хватает: видно позу, жест и свободное место, а весит один кадр
// около четырнадцати килобайт.
const WIDTH = 384;

// Один кадр на каждые шесть секунд. Реже — пропустим смену позы, чаще —
// платим за одинаковые картинки.
const EVERY = 6;
const MOST = 10;

const grab = (source, at, target) =>
	new Promise((resolve) => {
		const ff = spawn('ffmpeg', [
			'-v', 'error', '-y',
			'-ss', String(at), '-i', source,
			'-frames:v', '1', '-vf', `scale=${WIDTH}:-2`,
			'-q:v', '6', target,
		]);
		ff.on('close', (code) => resolve(code === 0));
		ff.on('error', () => resolve(false));
	});

export const eyes = async (source, duration, dir) => {
	if (!duration || duration < 2) return [];

	const many = Math.max(3, Math.min(MOST, Math.round(duration / EVERY)));
	const shots = [];

	await fs.mkdir(dir, {recursive: true});

	for (let i = 0; i < many; i++) {
		// Отступаем от самого начала и конца: там часто размытый кадр
		// или уже уехавшая склейка.
		const at = ((i + 0.5) / many) * duration;
		const file = path.join(dir, `кадр-${i}.jpg`);

		if (!(await grab(source, at, file))) continue;

		const bytes = await fs.readFile(file).catch(() => null);
		if (!bytes?.length) continue;

		shots.push({at: Number(at.toFixed(1)), base64: bytes.toString('base64')});
	}

	return shots;
};

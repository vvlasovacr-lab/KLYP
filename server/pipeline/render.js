// Шаг 3: рендер. Запускает Remotion из соседней папки src/ —
// те же компоненты, что крутятся в студии, никакой отдельной копии.

import fs from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {config} from './../config.js';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..', '..');

// Remotion печатает прогресс в stderr. Вытаскиваем проценты,
// чтобы клиент в мини-аппе видел не спиннер, а полосу.
const PROGRESS = /(\d{1,3})%/;

// Remotion читает медиа только из public и при сборке копирует эту папку
// в свой бандл — символическая ссылка на файл вне проекта до него не
// доходит. Поэтому на время рендера кладём в public настоящую копию
// и убираем её сразу после.
const stageSource = async (sourcePath, videoId) => {
	const dir = path.join(ROOT, 'public', 'uploads');
	await fs.mkdir(dir, {recursive: true});

	const ext = path.extname(sourcePath) || '.mp4';
	const name = `${videoId}${ext}`;
	const staged = path.join(dir, name);

	await fs.copyFile(sourcePath, staged);
	const {size} = await fs.stat(staged);
	return {relative: `uploads/${name}`, staged, bytes: size};
};

const sizeOf = async (file) => {
	try {
		const {size} = await fs.stat(file);
		return size;
	} catch {
		return null;
	}
};

export const renderVideo = async ({video, plan, onProgress}) => {
	const startedAt = Date.now();

	const outDir = path.join(config.storage.root, 'out', String(video.user_id));
	await fs.mkdir(outDir, {recursive: true});

	const {relative: sourceRel, staged, bytes: sourceBytes} = await stageSource(
		video.source_path,
		video.id
	);

	const outFile = path.join(outDir, `${video.id}.mp4`);
	const propsFile = path.join(outDir, `${video.id}.props.json`);

	// Пропсы кладём файлом: длинный JSON в аргументах командной строки
	// упирается в лимит на длину команды.
	await fs.writeFile(
		propsFile,
		JSON.stringify({
			chunks: plan.chunks,
			plan,
			// путь относительно public — под ним лежит ссылка на исходник
			source: sourceRel,
			fromSeconds: 0,
			// длительность задаёт длину композиции — без неё рендер
			// обрежется по длине образцового ролика
			durationInSeconds: Number(video.duration_sec) || plan.duration || 0,
		}),
		'utf8'
	);

	const args = [
		'remotion', 'render',
		'src/index.jsx',
		'Full',
		outFile,
		`--props=${propsFile}`,
		'--log=error',
	];

	// Черновик: меньше кадр — быстрее и дешевле.
	if (video.preview_only) {
		args.push(`--scale=${config.render.previewScale}`);
		args.push('--jpeg-quality=70');
	}

	try {
	await new Promise((resolve, reject) => {
		const child = spawn('npx', args, {cwd: ROOT, env: process.env});

		const killer = setTimeout(() => {
			child.kill('SIGKILL');
			reject(new Error(`Рендер не уложился в ${config.render.timeoutMin} минут`));
		}, config.render.timeoutMin * 60_000);

		let tail = '';
		const watch = (buf) => {
			const text = String(buf);
			tail = (tail + text).slice(-4000);
			const m = text.match(PROGRESS);
			if (m) onProgress?.(Math.min(99, Number(m[1])));
		};

		child.stdout.on('data', watch);
		child.stderr.on('data', watch);

		child.on('error', (err) => {
			clearTimeout(killer);
			reject(err);
		});
		child.on('close', (code) => {
			clearTimeout(killer);
			if (code === 0) resolve();
			else reject(new Error(`Remotion упал (код ${code}): ${tail.slice(-600)}`));
		});
	});

	} finally {
		// копия исходника не нужна ни при успехе, ни при падении
		await fs.unlink(staged).catch(() => {});
	}

	// Обложка для плитки в мини-аппе
	const poster = path.join(outDir, `${video.id}.jpg`);
	await new Promise((resolve) => {
		const ff = spawn('ffmpeg', [
			'-v', 'error', '-y',
			'-ss', '1.2', '-i', outFile,
			'-frames:v', '1', '-vf', 'scale=360:-1',
			poster,
		]);
		ff.on('close', () => resolve());
		ff.on('error', () => resolve());
	});

	await fs.unlink(propsFile).catch(() => {});

	return {
		outFile,
		poster,
		ms: Date.now() - startedAt,
		sourceBytes,
		outputBytes: await sizeOf(outFile),
	};
};

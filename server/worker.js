// Воркер очереди.
//
// Задачи берутся через SKIP LOCKED, поэтому несколько воркеров можно
// запускать без координатора — они честно поделят очередь.
// На Railway это либо тот же контейнер (WORKER_IN_PROCESS=1), либо
// отдельный сервис с той же базой.

import fs from 'node:fs/promises';
import path from 'node:path';
import {randomBytes} from 'node:crypto';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {q, one, many} from './db.js';
import {config} from './config.js';
import {runEngine, cleanupEngineRun} from './pipeline/engine.js';
import {addCredits} from './users.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

// Движок работает в своей папке, а хранить ролик нужно там же, где всё
// остальное: рядом с постером, под сроком хранения и уборщиком.
// Переносим результат к себе и убираем за движком.
const collectResult = async ({video, run}) => {
	const outDir = path.join(config.storage.root, 'out', String(video.user_id));
	await fs.mkdir(outDir, {recursive: true});

	const outFile = path.join(outDir, `${video.id}.mp4`);
	await fs.rename(run.outFile, outFile).catch(async () => {
		// rename не работает через границу тома — тогда копируем
		await fs.copyFile(run.outFile, outFile);
	});

	const poster = path.join(outDir, `${video.id}.jpg`);
	await makePoster(outFile, poster);

	// Данные, по которым рисовалась картинка, переносим к результату:
	// рабочую папку движка сейчас снесёт уборка, а по ним потом
	// разбираются, почему на экране вышло не то.
	await fs.copyFile(
		path.join(run.dir, 'output', `${video.id}.props.json`),
		path.join(outDir, `${video.id}.props.json`)
	).catch(() => {});

	const sourceBytes = await sizeOf(video.source_path);
	await cleanupEngineRun(run.dir);

	return {outFile, poster, sourceBytes};
};

// Обложка для плитки в мини-аппе.
const makePoster = (video, poster) =>
	new Promise((resolve) => {
		const ff = spawn('ffmpeg', [
			'-v', 'error', '-y',
			'-ss', '1.2', '-i', video,
			'-frames:v', '1', '-vf', 'scale=360:-1',
			poster,
		]);
		ff.on('close', () => resolve());
		ff.on('error', () => resolve());
	});

const sizeOf = async (file) => {
	try {
		const {size} = await fs.stat(file);
		return size;
	} catch {
		return null;
	}
};

let notify = async () => {}; // подменяется ботом при старте
export const setNotifier = (fn) => { notify = fn; };

// ── измерения ─────────────────────────────────────────────────
// Всё, что нужно для расчёта себестоимости, пишется одной строкой
// в лог и одной строкой в базу. В логе — чтобы увидеть сразу,
// в базе — чтобы посчитать за месяц.
const sec = (ms) => (ms / 1000).toFixed(1);
const mb = (bytes) => (bytes == null ? '—' : `${(bytes / 1048576).toFixed(1)}МБ`);

// Ссылка на скачивание живёт вместе с роликом: в чат её отдаёт бот,
// а initData туда не подставить.
const makeShareToken = () => randomBytes(18).toString('base64url');

const setStage = (jobId, stage, progress) =>
	q('UPDATE jobs SET stage = $2, progress = $3 WHERE id = $1', [jobId, stage, progress]);

const takeJob = async () => {
	const {rows} = await q(
		`UPDATE jobs SET status = 'running', locked_at = NOW(), attempts = attempts + 1
		 WHERE id = (
		   SELECT id FROM jobs
		   WHERE status = 'queued' AND run_after <= NOW()
		   ORDER BY id
		   FOR UPDATE SKIP LOCKED
		   LIMIT 1
		 )
		 RETURNING *`
	);
	return rows[0] ?? null;
};

const process1 = async (job) => {
	const video = await one('SELECT * FROM videos WHERE id = $1', [job.video_id]);
	if (!video) throw new Error('Ролик исчез из базы');

	await q("UPDATE videos SET status = 'running', updated_at = NOW() WHERE id = $1", [video.id]);

	// Исходник мог сгореть по сроку хранения — тогда монтировать нечего,
	// и честнее сказать об этом сразу, чем падать внутри рендера.
	if (video.source_deleted_at) {
		throw new Error('Исходник удалён по сроку хранения — загрузи видео заново');
	}

	await setStage(job.id, 'Готовлю материал', 4);

	// Весь монтаж делает движок: распознавание, речевой монтаж, разметка,
	// вёрстка субтитров, рендер и оценка качества. Наше дело — очередь,
	// хранение и доставка.
	const run = await runEngine({
		video,
		onStage: (label, at) => setStage(job.id, label, at),
		onProgress: (p) => setStage(job.id, 'Рендер', p),
	});

	await setStage(job.id, 'Сохраняю', 98);
	const {outFile, poster, sourceBytes} = await collectResult({video, run});

	const token = makeShareToken();
	const duration = Number(run.quality?.duration) || Number(video.duration_sec) || 0;
	const score = run.quality?.final_score ?? run.quality?.overall_score ?? null;

	await q(
		`UPDATE videos SET status = 'ready', output_path = $2, poster_path = $3,
		 render_ms = $4, source_bytes = $5, output_bytes = $6,
		 share_token = COALESCE(share_token, $7),
		 keep_until = NOW() + ($8 || ' days')::interval,
		 duration_sec = $9, plan = $10, speech_provider = $11,
		 error = NULL, updated_at = NOW()
		 WHERE id = $1`,
		[video.id, outFile, poster, run.ms,
		 sourceBytes, run.outputBytes, token, config.storage.outputKeepDays,
		 duration, JSON.stringify(run.quality ?? {}), run.speechProvider]
	);
	await q(
		"UPDATE jobs SET status = 'done', progress = 100, stage = 'Готово', finished_at = NOW() WHERE id = $1",
		[job.id]
	);

	// Исходник больше не нужен: он держится ровно столько, сколько
	// живёт окно правок. При SOURCE_KEEP_DAYS=0 удаляем прямо сейчас.
	if (config.storage.sourceKeepDays <= 0) {
		await dropSource(video);
	}

	const cut = run.speech
		? ` · срезано ${(Number(run.speech.removed_duration) || 0).toFixed(1)}с речи`
		: '';

	console.log(
		`  ролик ${video.id} · готов · ${Number(duration).toFixed(1)}с` +
		` · речь ${run.speechProvider}${cut}` +
		` · монтаж ${sec(run.ms)}с` +
		` · качество ${score === null ? '—' : Number(score).toFixed(2)}` +
		` · вход ${mb(sourceBytes)} · выход ${mb(run.outputBytes)}`
	);

	// Свежий снимок: в notify нужны share_token и размер файла.
	const ready = await one('SELECT * FROM videos WHERE id = $1', [video.id]);
	await notify(video.user_id, {type: 'ready', video: ready ?? video});
};

const failJob = async (job, err) => {
	const message = String(err?.message ?? err).slice(0, 900);
	console.error(
		`  ролик ${job.video_id} · упал (попытка ${job.attempts}/2) · ${message}`
	);

	// Две попытки: рендер иногда падает от нехватки памяти,
	// и повтор на свободной машине проходит.
	if (job.attempts < 2) {
		await q(
			`UPDATE jobs SET status = 'queued', run_after = NOW() + interval '40 seconds',
			 error = $2, fail_reason = COALESCE(fail_reason, $2) WHERE id = $1`,
			[job.id, message]
		);
		return;
	}

	await q(
		`UPDATE jobs SET status = 'failed', error = $2,
		 fail_reason = COALESCE(fail_reason, $2), finished_at = NOW() WHERE id = $1`,
		[job.id, message]
	);
	await q("UPDATE videos SET status = 'failed', error = $2 WHERE id = $1", [
		job.video_id,
		message,
	]);

	// Ролик не получился — возвращаем списанный кредит. Клиент не должен
	// платить за нашу ошибку.
	const video = await one('SELECT * FROM videos WHERE id = $1', [job.video_id]);
	if (video) {
		await addCredits(video.user_id, Number(video.cost), 'Возврат за неудачный рендер', String(video.id));
		await notify(video.user_id, {type: 'failed', video, message});
	}
};

let running = 0;
let stopped = false;

const tick = async () => {
	if (stopped || running >= config.render.concurrency) return;

	const job = await takeJob().catch((e) => {
		console.error('  очередь недоступна:', e.message);
		return null;
	});
	if (!job) return;

	running++;
	try {
		await process1(job);
	} catch (err) {
		await failJob(job, err).catch(() => {});
	} finally {
		running--;
	}
};

export const startWorker = () => {
	console.log(`  воркер запущен, параллельно: ${config.render.concurrency}`);
	const loop = setInterval(() => { tick(); }, 3000);
	return () => { stopped = true; clearInterval(loop); };
};

// Возвращает подвисшие задачи в очередь: если контейнер перезапустили
// посреди рендера, задача осталась бы в running навсегда.
export const requeueStale = async () => {
	const {rowCount} = await q(
		`UPDATE jobs SET status = 'queued', locked_at = NULL
		 WHERE status = 'running' AND locked_at < NOW() - interval '45 minutes'`
	);
	if (rowCount) console.log(`  вернул в очередь зависших задач: ${rowCount}`);
};

// ── уборка диска ──────────────────────────────────────────────
// Том оплачивается каждый месяц, а файлы копятся навсегда. Здесь
// живёт весь срок хранения: исходники сносятся после окна правок,
// готовые ролики — по истечении keep_until. Карточка в базе остаётся,
// чтобы клиент видел, что ролик был, и понимал, почему файла нет.

const dropSource = async (video) => {
	if (video.source_path) {
		await fs.unlink(video.source_path).catch(() => {});
	}
	await q(
		'UPDATE videos SET source_deleted_at = NOW() WHERE id = $1 AND source_deleted_at IS NULL',
		[video.id]
	);
};

// Обложку оставляем: она весит десятки килобайт, но без неё плитка
// в библиотеке превращается в серый прямоугольник.
const dropOutput = async (video) => {
	if (video.output_path) await fs.unlink(video.output_path).catch(() => {});
	await q(
		`UPDATE videos SET output_deleted_at = NOW(), status = 'expired',
		 share_token = NULL, updated_at = NOW() WHERE id = $1`,
		[video.id]
	);
};

export const sweepStorage = async () => {
	const keepSource = Math.max(0, config.storage.sourceKeepDays);

	// Исходники готовых роликов: окно правок закрылось.
	// Правки ссылаются на тот же файл, поэтому берём только те,
	// у которых нет активных детей в очереди.
	const sources = await many(
		`SELECT v.* FROM videos v
		 WHERE v.status IN ('ready','failed','expired')
		   AND v.source_path IS NOT NULL
		   AND v.source_deleted_at IS NULL
		   AND v.updated_at < NOW() - ($1 || ' days')::interval
		   AND NOT EXISTS (
		     SELECT 1 FROM videos c
		     WHERE c.parent_id = v.id AND c.status IN ('queued','running')
		   )
		 LIMIT 200`,
		[keepSource]
	);
	for (const video of sources) await dropSource(video);

	// Готовые ролики с истёкшим сроком хранения.
	const outputs = await many(
		`SELECT * FROM videos
		 WHERE status = 'ready'
		   AND output_path IS NOT NULL
		   AND output_deleted_at IS NULL
		   AND keep_until IS NOT NULL AND keep_until < NOW()
		 LIMIT 200`
	);
	for (const video of outputs) await dropOutput(video);

	if (sources.length || outputs.length) {
		console.log(
			`  уборка: исходников ${sources.length}, просроченных роликов ${outputs.length}`
		);
	}
	return {sources: sources.length, outputs: outputs.length};
};

export const startSweeper = () => {
	const everyMs = Math.max(5, config.storage.sweepMinutes) * 60_000;
	console.log(
		`  уборщик: исходники ${config.storage.sourceKeepDays === 0 ? 'сразу после монтажа' : `через ${config.storage.sourceKeepDays} дн.`}` +
		`, ролики ${config.storage.outputKeepDays} дн.`
	);

	const run = () => { sweepStorage().catch((e) => console.error('  уборка:', e.message)); };
	const timer = setInterval(run, everyMs);
	// Первый проход не сразу: на старте важнее поднять очередь.
	setTimeout(run, 60_000).unref?.();
	return () => clearInterval(timer);
};

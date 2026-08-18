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
import {runEngine, prepare, cleanupEngineRun, cleanupStaged} from './pipeline/engine.js';
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

	// Прокси, свои врезки и музыка лежат в public — Remotion читает только
	// оттуда. Ролик готов, и держать их дальше незачем.
	const freed = await cleanupStaged(video.id);
	if (freed > 1048576) console.log(`  ролик ${video.id} · освобождено ${mb(freed)} после рендера`);

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

// ── склейка дублей ────────────────────────────────────────────
// Клиент снял подводку, основную часть и концовку разными файлами, а
// ролик хочет один. Склеиваем их встык до монтажа — дальше по трубе
// идёт привычный единственный исходник.
//
// Пересжатие обязательно: дубли сняты в разное время, у них разное
// разрешение, частота кадров и звук. Без приведения к общему виду склейка
// либо рассыпается, либо теряет звук на втором куске.
const glue = (parts, target) =>
	new Promise((resolve, reject) => {
		const args = ['-v', 'error', '-y'];
		for (const file of parts) args.push('-i', file);

		// Каждый кусок вписываем в общий кадр 1080×1920, пустое поле —
		// чёрным. Так горизонтальный дубль встанет рядом с вертикальным
		// и никого не растянет.
		const steps = parts
			.map((_, i) =>
				`[${i}:v]scale=1080:1920:force_original_aspect_ratio=decrease,` +
				`pad=1080:1920:(ow-iw)/2:(oh-ih)/2,setsar=1,fps=30[v${i}];` +
				`[${i}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo[a${i}]`
			)
			.join(';');

		const chain = parts.map((_, i) => `[v${i}][a${i}]`).join('');

		args.push(
			'-filter_complex', `${steps};${chain}concat=n=${parts.length}:v=1:a=1[v][a]`,
			'-map', '[v]', '-map', '[a]',
			'-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
			'-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '160k',
			'-movflags', '+faststart', target
		);

		const ff = spawn('ffmpeg', args);
		let tail = '';
		ff.stderr.on('data', (b) => { tail = (tail + String(b)).slice(-400); });
		ff.on('close', (code) => (code === 0 ? resolve(target) : reject(new Error(tail || `ffmpeg ${code}`))));
		ff.on('error', reject);
	});

// Журнал последнего падения. Лежит отдельно от рабочей папки, которую
// сносит уборка, и весит килобайты.
const keepLog = async (dir, videoId) => {
	const from = path.join(dir, 'render.log');
	const text = await fs.readFile(from, 'utf8').catch(() => null);
	if (!text) return;

	const to = path.join(config.storage.root, 'logs');
	await fs.mkdir(to, {recursive: true});
	await fs.writeFile(path.join(to, `${videoId}.log`), text.slice(-20000), 'utf8');
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

// Несколько дублей — сначала в один файл, потом всё как обычно.
const mergeParts = async (job, video) => {
	const parts = Array.isArray(video.sources) ? video.sources : null;
	if (!parts || parts.length < 2) return video.source_path;

	// Дубли уже склеены на первом шаге — в source_path лежит общий файл
	// без пауз. Склеить исходники заново значило бы выбросить и склейку,
	// и вычитанный к ней текст.
	if (video.transcript?.scenes?.length) return video.source_path;

	await setStage(job.id, 'Склеиваю дубли', 3);
	const glued = path.join(
		path.dirname(video.source_path), `${path.parse(video.source_path).name}-склейка.mp4`
	);

	try {
		const at = Date.now();
		await glue(parts, glued);
		console.log(
			`  ролик ${video.id} · склеено дублей ${parts.length} за ${sec(Date.now() - at)}с`
		);
		return glued;
	} catch (err) {
		// Склейка не вышла — берём первый дубль, а не отказываем: клиент
		// уже ждёт результат.
		console.error(`  ролик ${video.id} · склейка не удалась: ${String(err.message).slice(0, 160)}`);
		return video.source_path;
	}
};

// ПЕРВЫЙ ШАГ — ТОЛЬКО ПОСЛУШАТЬ.
//
// Ролик из пакета за это не списывается: человек ещё ничего не получил,
// он только увидит, что мы расслышали, и поправит ошибки. Монтаж начнёт
// уже он сам — отдельной кнопкой.
const listenOnly = async (job, video) => {
	if (video.source_deleted_at) {
		throw new Error('Исходник удалён по сроку хранения — загрузи видео заново');
	}

	video.source_path = await mergeParts(job, video);

	const heard = await prepare({
		video,
		onStage: (label, at) => setStage(job.id, label, at),
	});

	await q(
		`UPDATE videos SET status = 'listened', source_path = $2, transcript = $3,
		 duration_sec = $4, speech_provider = $5, error = NULL, updated_at = NOW()
		 WHERE id = $1`,
		[
			video.id,
			heard.source,
			JSON.stringify(heard.transcript),
			Number(heard.transcript.duration || video.duration_sec || 0).toFixed(2),
			heard.transcript.provider,
		]
	);
	await q(
		"UPDATE jobs SET status = 'done', progress = 100, stage = 'Текст готов', finished_at = NOW() WHERE id = $1",
		[job.id]
	);

	console.log(
		`  ролик ${video.id} · текст готов за ${sec(heard.ms)}с` +
		` · реплик ${heard.transcript.scenes.length} · ждёт вычитки`
	);

	const listened = await one('SELECT * FROM videos WHERE id = $1', [video.id]);
	await notify(video.user_id, {type: 'listened', video: listened ?? video});
};

const process1 = async (job) => {
	const video = await one('SELECT * FROM videos WHERE id = $1', [job.video_id]);
	if (!video) throw new Error('Ролик исчез из базы');

	// Два вида работы в одной очереди: послушать перед вычиткой и
	// смонтировать после неё. Отличаются состоянием ролика.
	const onlyListen = video.status === 'listening';

	await q("UPDATE videos SET status = 'running', updated_at = NOW() WHERE id = $1", [video.id]);

	if (onlyListen) return await listenOnly(job, video);

	// Исходник мог сгореть по сроку хранения — тогда монтировать нечего,
	// и честнее сказать об этом сразу, чем падать внутри рендера.
	if (video.source_deleted_at) {
		throw new Error('Исходник удалён по сроку хранения — загрузи видео заново');
	}

	// Правка: клиент отметил моменты в готовом ролике и написал, что не
	// так. Метки уходят в монтаж — без них пересборка выдала бы ровно то
	// же самое, и клиент зря потратил бы ролик из пакета.
	const marks = video.parent_id
		? await many(
			'SELECT at_sec, note FROM marks WHERE video_id = $1 ORDER BY at_sec',
			[video.id]
		)
		: [];

	if (marks.length) {
		console.log(`  ролик ${video.id} · правка ${video.parent_id} · меток ${marks.length}`);
	}

	video.source_path = await mergeParts(job, video);

	await setStage(job.id, 'Готовлю материал', 4);

	// Весь монтаж делает движок: распознавание, речевой монтаж, разметка,
	// вёрстка субтитров, рендер и оценка качества. Наше дело — очередь,
	// хранение и доставка.
	const run = await runEngine({
		video: {...video, marks, parent: video.parent_id ?? null},
		onStage: (label, at) => setStage(job.id, label, at),
		onProgress: (p) => setStage(job.id, 'Рендер', p),
	});

	await setStage(job.id, 'Сохраняю', 98);
	const {outFile, poster, sourceBytes} = await collectResult({video, run});

	const token = makeShareToken();
	const duration = Number(video.duration_sec) || 0;

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
		 duration, JSON.stringify({words: run.words ?? 0, speech: run.speech ?? null}), run.speechProvider]
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
		? ` · срезано пауз ${run.speech.pauses} на ${(Number(run.speech.removed_duration) || 0).toFixed(1)}с`
		: '';

	console.log(
		`  ролик ${video.id} · готов · ${Number(duration).toFixed(1)}с` +
		` · речь ${run.speechProvider}${cut}` +
		` · монтаж ${sec(run.ms)}с` +
		` · слов ${run.words ?? 0}` +
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
	//
	// Упасть можно и до списания: на шаге, где мы только слушаем запись,
	// с пакета ещё ничего не снято. Там cost равен нулю, и «возврат»
	// выдал бы человеку ролик из воздуха.
	const video = await one('SELECT * FROM videos WHERE id = $1', [job.video_id]);
	if (video) {
		if (Number(video.cost) > 0) {
			await addCredits(video.user_id, Number(video.cost), 'Возврат за неудачный рендер', String(video.id));
		}
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
		// Рабочая папка весит сотни мегабайт — её надо снести. Но журнал
		// рендера сохраняем: без него причина падения теряется вместе с
		// папкой, и остаётся только гадать.
		const dir = path.join(config.storage.root, 'engine', String(job.video_id));
		await keepLog(dir, job.video_id).catch(() => {});
		await cleanupEngineRun(dir).catch(() => {});
		await cleanupStaged(job.video_id).catch(() => {});
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

// Недокачанные куски. Клиент мог закрыть приложение на середине —
// такой огрызок никому не нужен, но место занимает.
const sweepUploads = async () => {
	const dir = path.join(config.storage.root, 'upload');
	let files = [];
	try {
		files = await fs.readdir(dir);
	} catch {
		return 0;
	}

	const old = Date.now() - 6 * 3600 * 1000;
	let removed = 0;
	for (const name of files) {
		const file = path.join(dir, name);
		const stat = await fs.stat(file).catch(() => null);
		if (stat && stat.mtimeMs < old) {
			await fs.rm(file, {force: true}).catch(() => {});
			removed++;
		}
	}
	return removed;
};

// Рабочие папки движка: всё, что не принадлежит роликам в работе.
// Каждая весит сотни мегабайт, и без уборки диск кончается за сутки.
const sweepEngineDirs = async () => {
	const root = path.join(config.storage.root, 'engine');
	let dirs = [];
	try {
		dirs = await fs.readdir(root);
	} catch {
		return 0;
	}

	const busy = await many(
		"SELECT video_id FROM jobs WHERE status IN ('queued','running')"
	);
	const keep = new Set(busy.map((row) => String(row.video_id)));

	let removed = 0;
	for (const name of dirs) {
		if (keep.has(name)) continue;
		await fs.rm(path.join(root, name), {recursive: true, force: true}).catch(() => {});
		removed++;
	}
	return removed;
};

// Сколько места осталось на томе. Node показывает диск всей машины,
// а нам важен именно смонтированный том: он в разы меньше и кончается
// первым.
const freeSpace = async () => {
	try {
		const {bavail, bsize, blocks} = await fs.statfs(config.storage.root);
		return {free: bavail * bsize, total: blocks * bsize};
	} catch {
		return null;
	}
};

// Аварийная уборка. Когда на томе почти нет места, ждать срока хранения
// поздно: следующий заказ упадёт ещё на копировании исходника. Сносим
// самое старое и самое тяжёлое, пока не освободится запас.
//
// Порядок не случаен: сперва исходники — они весят больше всего и нужны
// только для правок. Готовые ролики трогаем в последнюю очередь: за них
// клиент заплатил.
const freeUpSpace = async () => {
	const space = await freeSpace();
	if (!space) return 0;

	// Запас не может быть больше самого тома. На маленьком томе полтора
	// гигабайта свободными не удержать никогда — уборщик стирал бы всё
	// подряд, включая оплаченные ролики, и никогда не останавливался.
	const want = Math.min(config.storage.minFreeBytes, space.total * 0.25);
	if (space.free >= want) return 0;

	console.warn(
		`  на томе осталось ${(space.free / 1073741824).toFixed(1)} ГБ из ` +
		`${(space.total / 1073741824).toFixed(1)} — освобождаю место`
	);

	let dropped = 0;

	for (const [what, rows] of [
		['исходник', await many(
			`SELECT * FROM videos
			 WHERE source_path IS NOT NULL AND source_deleted_at IS NULL
			   AND status IN ('ready','failed','expired')
			 ORDER BY updated_at ASC LIMIT 100`
		)],
		['ролик', await many(
			`SELECT * FROM videos
			 WHERE status = 'ready' AND output_path IS NOT NULL
			   AND output_deleted_at IS NULL
			 ORDER BY updated_at ASC LIMIT 100`
		)],
	]) {
		for (const video of rows) {
			const now = await freeSpace();
			if (!now || now.free >= want) return dropped;
			await (what === 'исходник' ? dropSource(video) : dropOutput(video));
			dropped++;
		}
	}

	return dropped;
};

// Забытые прокси в public. Лежат не на томе, а в файловой системе
// контейнера, где места меньше всего, — поэтому подметаем их отдельно
// и по времени, а не по состоянию ролика в базе.
const STAGED_HOURS = 6;

const sweepStaged = async () => {
	const dir = path.join(ROOT, 'public', 'uploads');
	const files = await fs.readdir(dir).catch(() => []);
	const old = Date.now() - STAGED_HOURS * 3600_000;
	let gone = 0;

	for (const name of files) {
		const file = path.join(dir, name);
		const stat = await fs.stat(file).catch(() => null);
		if (!stat?.isFile() || stat.mtimeMs > old) continue;
		await fs.rm(file, {force: true}).catch(() => {});
		gone++;
	}

	return gone;
};

export const sweepStorage = async () => {
	const keepSource = Math.max(0, config.storage.sourceKeepDays);
	const engineDirs = await sweepEngineDirs();
	const halfDone = await sweepUploads();

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

	// Прокси, оставшиеся от прерванных рендеров. Обычно их убирает сам
	// воркер, но контейнер может умереть посреди работы — тогда файл
	// останется навсегда. Рендер не длится и часа, поэтому всё, что
	// старше шести, — заведомо мусор.
	const stagedLeft = await sweepStaged();

	// Расшифровка, к которой никто не вернулся. Человек загрузил ролик,
	// увидел текст и закрыл приложение — ролик из пакета не списан, а
	// исходник лежит и занимает место. Через сутки убираем файл, карточку
	// оставляем с внятной причиной.
	const abandoned = await many(
		`UPDATE videos SET status = 'expired',
		   error = 'Расшифровка не подтверждена за сутки — загрузи видео заново'
		 WHERE status = 'listened' AND updated_at < NOW() - interval '24 hours'
		 RETURNING *`
	);
	for (const video of abandoned) await dropSource(video);

	// Срок хранения — это про порядок, а не про выживание. Если места
	// нет прямо сейчас, сносим самое старое, не дожидаясь срока.
	const forced = await freeUpSpace();

	if (sources.length || outputs.length || engineDirs || forced || halfDone || abandoned.length || stagedLeft) {
		console.log(
			`  уборка: исходников ${sources.length}, просроченных роликов ${outputs.length},` +
			` рабочих папок ${engineDirs}` +
			(stagedLeft ? `, забытых прокси ${stagedLeft}` : '') +
			(abandoned.length ? `, брошенных расшифровок ${abandoned.length}` : '') +
			(halfDone ? `, брошенных загрузок ${halfDone}` : '') +
			(forced ? `, аварийно ${forced}` : '')
		);
	}
	return {sources: sources.length, outputs: outputs.length, engineDirs, forced, abandoned: abandoned.length};
};

export const startSweeper = () => {
	const everyMs = Math.max(5, config.storage.sweepMinutes) * 60_000;
	console.log(
		`  уборщик: исходники ${config.storage.sourceKeepDays === 0 ? 'сразу после монтажа' : `через ${config.storage.sourceKeepDays} дн.`}` +
		`, ролики ${config.storage.outputKeepDays} дн.`
	);

	const run = () => { sweepStorage().catch((e) => console.error('  уборка:', e.message)); };
	const timer = setInterval(run, everyMs);
	// Первый проход почти сразу: после перезапуска на диске могли остаться
	// рабочие папки от прерванных монтажей, и места может не быть уже сейчас.
	setTimeout(run, 5_000).unref?.();
	return () => clearInterval(timer);
};

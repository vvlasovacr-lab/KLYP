// Мост к монтажному движку.
//
// Движок живёт в engine/ и написан на Python: он сам распознаёт речь,
// режет паузы, раскладывает монтаж, считает вёрстку субтитров по метрикам
// шрифта, зовёт Remotion и в конце выставляет оценку качества.
//
// Отсюда он выглядит как одна функция: дай исходник — получи ролик.
// Конфигурация ему подсовывается временным файлом, чтобы каждый заказ
// работал в своей папке и заказы не мешали друг другу.

import fs from 'node:fs/promises';
import {existsSync} from 'node:fs';
import path from 'node:path';
import {spawn, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {config, hasSpeech} from './../config.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const ENGINE = path.join(ROOT, 'engine');

// Стадии движка → человеческий текст и доля прогресса.
// Движок печатает их в свой лог, а клиент в мини-аппе видит полосу.
const STAGES = [
	{key: 'ANALYZING', label: 'Слушаю речь', at: 8},
	{key: 'EPISODE_EXTRACTION', label: 'Выбираю куски', at: 18},
	{key: 'SPEECH_EDIT', label: 'Убираю паузы', at: 26},
	{key: 'DIRECTING', label: 'Раскладываю монтаж', at: 34},
	{key: 'EXECUTING', label: 'Расставляю акценты', at: 42},
	{key: 'RENDERING', label: 'Рендер', at: 48},
	{key: 'QUALITY_CHECK', label: 'Проверяю качество', at: 97},
];

// Стадии движок пишет не в stdout, а в свой журнал задачи. Читаем его
// на ходу: иначе клиент видит «Рендер» с первой секунды и до конца.
const watchStages = (dir, onStage) => {
	let seen = new Set();
	let stageAt = 0;

	const timer = setInterval(async () => {
		try {
			const jobs = path.join(dir, 'work', 'jobs');
			const entries = await fs.readdir(jobs);
			if (!entries.length) return;

			const log = path.join(jobs, entries[entries.length - 1], 'logs', 'job.log');
			const text = await fs.readFile(log, 'utf8');

			for (const stage of STAGES) {
				if (seen.has(stage.key)) continue;
				if (!text.includes(`[${stage.key}]`)) continue;
				seen.add(stage.key);
				if (stage.at > stageAt) {
					stageAt = stage.at;
					onStage?.(stage.label, stage.at);
				}
			}
		} catch {
			// журнала ещё нет или задача только создаётся — не беда
		}
	}, 1000);

	timer.unref?.();
	return () => clearInterval(timer);
};

// Папку задачи ищем на диске, а не в выводе: строка лога может прийти
// разорванной между чанками, а папка всегда одна и та же.
const findWorkspace = async (dir) => {
	try {
		const jobs = path.join(dir, 'work', 'jobs');
		const entries = await fs.readdir(jobs);
		return entries.length ? path.join(jobs, entries[entries.length - 1]) : null;
	} catch {
		return null;
	}
};

// Движку нужен свой Python. Локально это venv рядом с движком, на сервере —
// то, что положил образ. Имя там не всегда python3: nix ставит python3.12,
// и жёстко зашитое «python3» молча не находится.
let pythonPath = null;

const python = () => {
	if (pythonPath) return pythonPath;
	if (process.env.PYTHON_BIN) return (pythonPath = process.env.PYTHON_BIN);

	const candidates = [
		path.join(ENGINE, '.venv', 'bin', 'python'),
		'python3',
		'python3.12',
		'python3.11',
		'python',
	];

	for (const candidate of candidates) {
		// абсолютный путь проверяем на месте, имя — через which
		if (candidate.includes('/')) {
			if (existsSync(candidate)) return (pythonPath = candidate);
			continue;
		}
		const found = spawnSync('which', [candidate], {encoding: 'utf8'});
		if (found.status === 0 && found.stdout.trim()) {
			return (pythonPath = found.stdout.trim());
		}
	}

	throw new Error(
		'Python не найден. Движок монтажа написан на Python — без него монтаж невозможен. ' +
		'Проверь, что образ его ставит, или задай PYTHON_BIN.'
	);
};

// Движку нужен свой config.json: пути к заказу, стиль, лимиты.
// Всё, чего мы не переопределяем, берётся из engine/config.json.
//
// Файл обязан лежать именно в engine/: движок считает папку конфига своим
// корнем и ищет рядом style_profiles.json, font_profiles.json, corrections.json
// и остальные словари. Пути заказа при этом абсолютные — они уходят
// в наше хранилище, а не в папку движка.
// Движок всегда считает вёрстку под полный кадр 1080×1920. Уменьшать
// канву для черновика нельзя: он проверяет, влезает ли текст в отведённые
// поля, и на маленькой канве отказывается верстать вовсе. Черновик мельчает
// уже на рендере — ключом --scale, вёрстки это не касается.
const writeConfig = async ({video, dir}) => {
	const base = JSON.parse(await fs.readFile(path.join(ENGINE, 'config.json'), 'utf8'));

	const merged = {
		...base,
		input_dir: path.join(dir, 'input'),
		output_dir: path.join(dir, 'output'),
		work_dir: path.join(dir, 'work'),
		logs_dir: path.join(dir, 'logs'),
		// ассеты общие для всех заказов: врезки, звуки, шрифты
		assets_dir: path.join(ENGINE, 'assets'),
		profile: video.template ? templateToProfile(video.template) : 'AUTO',
		remotion: {
			...base.remotion,
			// проект Remotion тоже общий — он не зависит от заказа
			project_dir: path.join(ENGINE, 'remotion'),
		},
	};

	const file = path.join(ENGINE, `config.job-${video.id}.json`);
	await fs.writeFile(file, JSON.stringify(merged, null, 2), 'utf8');
	return file;
};

// Наши шаблоны монтажа → стилевые профили движка.
// Кодов у нас больше, поэтому близкие сводим к одному профилю.
const PROFILE_BY_TEMPLATE = {
	// REELS_DENSE — наш профиль поверх AGGRESSIVE_RED: пороги ниже,
	// подсветка чаще, акценты золотом. Ближе к референсу, на который
	// мы равнялись, чем спокойный заводской профиль.
	expose: 'REELS_DENSE',
	hook: 'REELS_DENSE',
	offer: 'REELS_DENSE',
	breakdown: 'CLEAN_YELLOW',
	case: 'CLEAN_YELLOW',
	myths: 'CLEAN_YELLOW',
	warmup: 'PODCAST',
};

export const templateToProfile = (code) => PROFILE_BY_TEMPLATE[code] ?? 'AUTO';

// Манифест шрифтов помнит абсолютный путь к папке, где его собрали.
// После деплоя путь другой, и движок отказывается верстать текст.
// Пересобираем один раз за запуск процесса, если путь разъехался.
let fontsChecked = false;

const ensureFonts = async () => {
	if (fontsChecked) return;
	fontsChecked = true;

	const dir = path.join(ENGINE, 'assets', 'fonts');
	const manifest = path.join(dir, 'font_manifest.json');

	try {
		const current = JSON.parse(await fs.readFile(manifest, 'utf8'));
		if (path.resolve(current.root ?? '') === path.resolve(dir) && current.summary?.parsed > 0) {
			return;
		}
	} catch {
		// манифеста нет — соберём с нуля
	}

	console.log('  пересобираю манифест шрифтов движка');

	const result = await new Promise((resolve) => {
		const child = spawn(
			python(),
			['-m', 'shortsai.font_inventory', dir, '--output', manifest],
			{cwd: ENGINE, env: process.env}
		);

		let tail = '';
		const watch = (buf) => { tail = (tail + String(buf)).slice(-500); };
		child.stdout.on('data', watch);
		child.stderr.on('data', watch);

		child.on('close', (code) => resolve({code, tail}));
		child.on('error', (err) => resolve({code: -1, tail: err.message}));
	});

	// Молча проглотить нельзя: без манифеста движок откажется верстать текст,
	// и клиент увидит невнятное «rejected by font manifest» вместо причины.
	if (result.code !== 0) {
		throw new Error(
			`Не удалось собрать манифест шрифтов (код ${result.code}): ${result.tail.slice(-300)}`
		);
	}

	const built = await fs.readFile(manifest, 'utf8').then(JSON.parse).catch(() => null);
	const parsed = built?.summary?.parsed ?? 0;
	if (!parsed) {
		throw new Error(
			`Манифест шрифтов собрался пустым. Проверь, что файлы шрифтов лежат в ${dir}`
		);
	}
	console.log(`  шрифтов в манифесте: ${parsed}`);
};

// ── наш рендер ────────────────────────────────────────────────
// Remotion читает медиа только из public и при сборке копирует эту папку
// в свой бандл, поэтому исходник кладём туда настоящей копией и убираем
// сразу после.
const renderOurs = async ({video, source, montage, dir, onProgress}) => {
	const uploads = path.join(ROOT, 'public', 'uploads');
	await fs.mkdir(uploads, {recursive: true});

	const ext = path.extname(source) || '.mp4';
	const staged = path.join(uploads, `${video.id}${ext}`);
	await fs.copyFile(source, staged);

	const outDir = path.join(dir, 'output');
	await fs.mkdir(outDir, {recursive: true});
	const outFile = path.join(outDir, `${video.id}.mp4`);
	const propsFile = path.join(outDir, `${video.id}.props.json`);

	// План движка переводим в наш формат: сцены становятся репликами,
	// помеченные слова — акцентами, а речевой монтаж — нарезкой видео.
	const {fromEngine} = await import('../../src/fromEngine.js');
	const {chunks, plan, speech, duration} = fromEngine(montage, {
		template: video.template || 'expose',
		font: video.font || null,
	});

	await fs.writeFile(
		propsFile,
		JSON.stringify({
			chunks,
			plan,
			speech,
			source: `uploads/${path.basename(staged)}`,
			fromSeconds: 0,
			durationInSeconds: duration,
		}),
		'utf8'
	);

	const args = [
		'remotion', 'render', 'src/index.jsx', 'Full', outFile,
		`--props=${propsFile}`,
		'--log=error',
		// Сервер слабее рабочей машины: кадр с видео и шрифтами может
		// собираться дольше стандартных тридцати секунд, и рендер падал
		// по таймауту на ровном месте.
		`--timeout=${config.render.frameTimeoutMs}`,
		`--concurrency=${config.render.concurrencyPerRender}`,
	];

	// На сервере нет видеокарты, а браузер по умолчанию всё равно идёт
	// к ней и виснет на первом же кадре с видео. swangle — отрисовка
	// на процессоре; на рабочей машине с настоящей картой она не нужна.
	if (config.render.softwareGl) args.push('--gl=swangle');

	if (video.preview_only) {
		args.push(`--scale=${config.render.previewScale}`, '--jpeg-quality=70');
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
				tail = (tail + text).slice(-6000);
				const done = text.match(/(\d{1,3})%/);
				// рендер занимает отрезок с 48% до 97%
				if (done) onProgress?.(Math.min(96, 48 + Math.round(Number(done[1]) * 0.49)));
			};

			child.stdout.on('data', watch);
			child.stderr.on('data', watch);
			child.on('error', (err) => { clearTimeout(killer); reject(err); });
			child.on('close', (code) => {
				clearTimeout(killer);
				if (code === 0) return resolve();

				// Из стека вызовов пользы нет: он про внутренности Remotion.
				// Ищем строки, которые объясняют причину.
				const meaningful = tail
					.split('\n')
					.filter((line) => /error|fail|timeout|cannot|unable|not found|denied|memory/i.test(line))
					.filter((line) => !line.trim().startsWith('at '))
					.slice(0, 4)
					.join(' | ');

				reject(new Error(
					`Рендер упал (код ${code}): ${meaningful || tail.slice(-400)}`
				));
			});
		});
	} finally {
		await fs.unlink(staged).catch(() => {});
		await fs.unlink(propsFile).catch(() => {});
	}

	return outFile;
};

export const runEngine = async ({video, onProgress, onStage}) => {
	const startedAt = Date.now();
	await ensureFonts();

	// Каждый заказ в своей папке: движок пишет туда транскрипт, планы,
	// временные файлы и готовый ролик.
	const dir = path.join(config.storage.root, 'engine', String(video.id));
	await fs.mkdir(path.join(dir, 'input'), {recursive: true});

	// Исходник кладём под именем без кириллицы и пробелов: движок
	// подставляет имя файла в пути артефактов.
	const ext = path.extname(video.source_path) || '.mp4';
	const source = path.join(dir, 'input', `source${ext}`);
	await fs.copyFile(video.source_path, source);

	const configFile = await writeConfig({video, dir});

	// --preview: движок доходит до готового плана и останавливается.
	// Рендерить будем сами — нашими компонентами, которые рисуют плашки,
	// бейджи и золото. Заодно вдвое быстрее: не рендерим дважды.
	const args = ['run.py', '--config', configFile, '--file', source, '--force', '--preview'];

	let tail = '';

	const stopStages = watchStages(dir, onStage);

	try {
	await new Promise((resolve, reject) => {
		const child = spawn(python(), args, {
			cwd: ENGINE,
			env: {
				...process.env,
				// Движок распознаёт речь тем же провайдером, что и остальной
				// сервис: ключ вписывается один раз и работает везде.
				SPEECH_PROVIDER: config.speech.provider,
				SPEECH_API_KEY: config.speech.apiKey,
				SPEECH_MODEL: config.speech.model,
				SPEECH_URL: config.speech.url,
				SPEECH_LANG: config.speech.language,
				PYTHONUNBUFFERED: '1',
			},
		});

		const killer = setTimeout(() => {
			child.kill('SIGKILL');
			reject(new Error(`Монтаж не уложился в ${config.render.timeoutMin} минут`));
		}, config.render.timeoutMin * 60_000);

		const watch = (buf) => {
			tail = (tail + String(buf)).slice(-4000);
		};

		child.stdout.on('data', watch);
		child.stderr.on('data', watch);

		child.on('error', (err) => {
			clearTimeout(killer);
			reject(new Error(`Не удалось запустить движок: ${err.message}`));
		});
		child.on('close', (code) => {
			clearTimeout(killer);
			if (code === 0) resolve();
			else reject(new Error(`Движок упал (код ${code}): ${tail.slice(-600)}`));
		});
	});

	} finally {
		stopStages();
		// Временный конфиг не нужен ни при успехе, ни при падении.
		await fs.unlink(configFile).catch(() => {});
	}

	const workspace = await findWorkspace(dir);
	if (!workspace) {
		throw new Error('Движок отработал, но папки с планом не нашлось');
	}

	const montage = await readJson(path.join(workspace, 'artifacts', 'montage_plan.json'));
	if (!montage?.scenes?.length) {
		throw new Error('Движок не собрал монтажный план');
	}

	// Рендерим сами: движок сказал, что показывать и когда, наши компоненты
	// решают, как это выглядит.
	onStage?.('Рендер', 48);
	const outFile = await renderOurs({video, source, montage, dir, onProgress});

	// Оценку качества и план речевого монтажа движок считает сам —
	// забираем их как есть, они лежат в папке задачи.
	const quality = await readJson(path.join(workspace, 'artifacts', 'quality_report.json'));
	const speech = await readJson(path.join(workspace, 'artifacts', 'speech_edit_plan.json'));

	return {
		outFile,
		dir,
		jobId: workspace ? path.basename(workspace) : null,
		ms: Date.now() - startedAt,
		outputBytes: await sizeOf(outFile),
		quality,
		speech,
		// Кто на самом деле распознавал. Без ключа движок молча уходит
		// на локальную модель, и писать в лог имя сервиса было бы враньём.
		speechProvider: hasSpeech() ? config.speech.provider : 'локальная модель',
	};
};

// Ролик и рабочие файлы движка после переноса результата не нужны.
export const cleanupEngineRun = async (dir) => {
	await fs.rm(dir, {recursive: true, force: true}).catch(() => {});
};

const exists = async (file) => {
	try {
		await fs.access(file);
		return true;
	} catch {
		return false;
	}
};

const sizeOf = async (file) => {
	try {
		const {size} = await fs.stat(file);
		return size;
	} catch {
		return null;
	}
};

const readJson = async (file) => {
	try {
		return JSON.parse(await fs.readFile(file, 'utf8'));
	} catch {
		return null;
	}
};

const findOutput = async (dir) => {
	try {
		const files = await fs.readdir(dir);
		const mp4 = files.filter((f) => f.toLowerCase().endsWith('.mp4'));
		return mp4.length ? path.join(dir, mp4[0]) : null;
	} catch {
		return null;
	}
};

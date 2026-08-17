// СБОРКА РОЛИКА.
//
// Путь один: услышать речь → отдать расшифровку модели → нарисовать
// кадры по её разметке.
//
// Раньше между расшифровкой и рисованием стоял отдельный монтажный
// движок на Python — пятьдесят восемь модулей, которые считали сцены,
// речевой монтаж, движения камеры и подбор врезок. К готовому ролику
// из этого не доходило ничего: картинку рисуют наши компоненты,
// разметку придумывает модель, паузы срезаются раньше. Оставались
// только слова с таймингами — и те он брал нашим же ключом.
//
// Движок убран. Вместе с ним ушли шесть видов поломок, Python из
// контейнера и лишний перевод из чужого формата в свой.

import fs from 'node:fs/promises';
import fsSync, {existsSync} from 'node:fs';
import path from 'node:path';
import {spawn, spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import {config, hasSpeech} from './../config.js';
import {direct} from './director.js';
import {listen} from './listen.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');

// Разметка прошлой сборки лежит рядом с готовым роликом. По ней видно,
// что именно клиент забраковал: без неё замечание «убери врезку» не с чем
// сопоставить.
const readPlan = async (userId, videoId) => {
	try {
		const file = path.join(
			config.storage.root, 'out', String(userId), `${videoId}.props.json`
		);
		const {plan, chunks} = JSON.parse(await fs.readFile(file, 'utf8'));
		return {
			title: plan?.title?.lines?.map((l) => l.pieces[0].text) ?? [],
			accents: (plan?.accents ?? []).map(([at, , text, tone]) => ({at, text, tone})),
			broll: (plan?.broll ?? []).map((b) => ({at: b.from, file: b.file})),
			words: chunks?.length ?? 0,
		};
	} catch {
		// Прошлая разметка не сохранилась — не повод отказывать в правке.
		return null;
	}
};

// ── вырезание пауз ────────────────────────────────────────────
// Паузы ищем в самом звуке, а не в расшифровке. Распознавание их
// прячет: на двухсекундной тишине оно растягивает соседнее слово с
// 9,26 до 11,48 секунды, и промежутка между словами не остаётся —
// резать движку нечего, хотя тишина есть.
//
// Режем по середине паузы, оставляя по чуть-чуть с обеих сторон. Стык
// получается «тишина к тишине» и потому не слышен: щелчок берётся
// оттуда, где обрывается звучащая волна.
const hush = (file) =>
	new Promise((resolve) => {
		const ff = spawn('ffmpeg', [
			'-hide_banner', '-i', file,
			'-af', `silencedetect=noise=${config.render.silenceDb}dB:d=${config.render.pauseSec}`,
			'-f', 'null', '-',
		]);

		let text = '';
		ff.stderr.on('data', (b) => { text += String(b); });
		ff.on('close', () => {
			const found = [];
			const re = /silence_start:\s*([\d.]+)[\s\S]*?silence_end:\s*([\d.]+)/g;
			let m;
			while ((m = re.exec(text))) found.push([Number(m[1]), Number(m[2])]);
			resolve(found);
		});
		ff.on('error', () => resolve([]));
	});

const trimPauses = async (from, to) => {
	const pauses = await hush(from);
	const keep = config.render.keepPauseSec;

	// Куски, которые остаются. По краям паузы оставляем немного тишины —
	// без неё речь начиналась бы впритык и звучала бы рублено.
	const parts = [];
	let at = 0;
	let cut = 0;

	for (const [start, end] of pauses) {
		if (end - start < keep * 2 + 0.1) continue;
		parts.push([at, start + keep]);
		cut += end - start - keep * 2;
		at = end - keep;
	}

	if (!parts.length || cut < 0.3) return null;

	// Отбор кадров по времени, а не вырезка кусков с последующей склейкой:
	// склейка опирается на метки времени в файле, а они у снятого телефоном
	// видео бывают неровными — и тогда обрезка молча не срабатывает.
	const ranges = parts
		.map(([x, y]) => `between(t,${x.toFixed(3)},${y.toFixed(3)})`)
		.concat(`gte(t,${at.toFixed(3)})`)
		.join('+');

	await new Promise((resolve, reject) => {
		const ff = spawn('ffmpeg', [
			'-v', 'error', '-y', '-i', from,
			'-filter_complex',
			`[0:v]select='${ranges}',setpts=N/FRAME_RATE/TB[v];` +
			`[0:a]aselect='${ranges}',asetpts=N/SR/TB[a]`,
			'-map', '[v]', '-map', '[a]',
			'-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20', '-pix_fmt', 'yuv420p',
			'-r', '30', '-c:a', 'aac', '-b:a', '160k', '-movflags', '+faststart', to,
		]);
		let tail = '';
		ff.stderr.on('data', (b) => { tail = (tail + String(b)).slice(-300); });
		ff.on('close', (code) => (code === 0 ? resolve() : reject(new Error(tail || `ffmpeg ${code}`))));
		ff.on('error', reject);
	});

	return {cut, pauses: parts.length};
};

const makeProxy = ({source, target, preview}) =>
	new Promise((resolve, reject) => {
		// Черновик всё равно уедет в 486×864 — незачем таскать полный кадр
		const scale = preview ? 'scale=-2:960' : 'scale=-2:1920';

		const ff = spawn('ffmpeg', [
			'-v', 'error', '-y',
			'-i', source,
			'-vf', scale,
			'-c:v', 'libx264',
			'-preset', 'ultrafast',
			// каждый кадр ключевой: декодер не ищет опорные и не ждёт
			'-g', '1',
			'-bf', '0',
			'-crf', preview ? '26' : '20',
			'-pix_fmt', 'yuv420p',
			'-c:a', 'aac', '-b:a', '128k',
			'-movflags', '+faststart',
			target,
		]);

		let tail = '';
		ff.stderr.on('data', (buf) => { tail = (tail + String(buf)).slice(-400); });
		ff.on('error', reject);
		ff.on('close', (code) =>
			code === 0 ? resolve() : reject(new Error(`Не удалось подготовить исходник: ${tail}`))
		);
	});

// ── наш рендер ────────────────────────────────────────────────
// Remotion читает медиа только из public и при сборке копирует эту папку
// в свой бандл, поэтому исходник кладём туда настоящей копией и убираем
// сразу после.
const renderOurs = async ({video, source, montage, dir, onProgress, onStage}) => {
	const uploads = path.join(ROOT, 'public', 'uploads');
	await fs.mkdir(uploads, {recursive: true});

	const staged = path.join(uploads, `${video.id}.mp4`);
	await makeProxy({source, target: staged, preview: video.preview_only});

	const outDir = path.join(dir, 'output');
	await fs.mkdir(outDir, {recursive: true});
	const outFile = path.join(outDir, `${video.id}.mp4`);
	const propsFile = path.join(outDir, `${video.id}.props.json`);

	// План движка переводим в наш формат: сцены становятся репликами,
	// помеченные слова — акцентами, а речевой монтаж — нарезкой видео.
	const {fromEngine} = await import('../../src/fromEngine.js');

	// Что подсветить, куда поставить врезку и каким заголовком открыть —
	// решает модель: она читает расшифровку целиком и понимает, о чём речь.
	// Без ключа или при сбое возвращается пусто, и разметка собирается
	// по правилам, как раньше.
	onStage?.('Придумываю монтаж', 44);
	// Свои врезки клиента переносим туда же, откуда Remotion берёт видео.
	const ownClips = [];
	for (const [i, file] of (video.clips ?? []).entries()) {
		const name = `clip-${video.id}-${i}${path.extname(file) || '.mp4'}`;
		const ok = await fs.copyFile(file, path.join(uploads, name)).then(() => true).catch(() => false);
		if (ok) ownClips.push(`uploads/${name}`);
	}

	const rough = fromEngine(montage, {template: video.template || 'expose'});

	// Если это правка — показываем модели прежнюю разметку и замечания
	// клиента к ней. Без прежней она пересоберёт ролик с нуля и заодно
	// поменяет то, к чему претензий не было.
	const previous = video.parent ? await readPlan(video.user_id, video.parent) : null;

	const director = await direct({
		chunks: rough.chunks,
		duration: rough.duration,
		marks: video.marks ?? [],
		previous,
		brief: video.brief ?? '',
	});

	if (director) {
		console.log(
			`  режиссёр: ${director.accents?.length ?? 0} акцентов,` +
			` ${director.broll?.length ?? 0} врезок, жанр ${director.template}` +
			` · ${(director.ms / 1000).toFixed(1)}с` +
			` · ${director.usage.in}+${director.usage.out} токенов`
		);
	}

	const {chunks, plan, speech, duration} = fromEngine(montage, {
		template: video.template || 'expose',
		font: video.font || null,
		director,
		ownClips,
	});

	if (ownClips.length) {
		console.log(`  ролик ${video.id} · своих врезок ${ownClips.length}`);
	}

	// Свои материалы клиента — музыка и врезки — кладутся туда же, откуда
	// Remotion берёт видео: он умеет читать только из своей папки.
	let music = null;
	if (video.music) {
		const name = `music-${video.id}${path.extname(video.music) || '.mp3'}`;
		await fs.copyFile(video.music, path.join(uploads, name)).catch(() => {});
		music = {file: `uploads/${name}`, volume: 0.16};
	}

	await fs.writeFile(
		propsFile,
		JSON.stringify({
			chunks,
			plan,
			speech,
			music,
			source: `uploads/${path.basename(staged)}`,
			fromSeconds: 0,
			durationInSeconds: duration,
		}),
		'utf8'
	);

	const args = [
		'remotion', 'render', 'src/index.jsx', 'Full', outFile,
		`--props=${propsFile}`,
		'--log=verbose',
		// Сервер слабее рабочей машины: кадр с видео и шрифтами может
		// собираться дольше стандартных тридцати секунд, и рендер падал
		// по таймауту на ровном месте.
		`--timeout=${config.render.frameTimeoutMs}`,
		// Remotion поднимает свой сервер, чтобы отдавать браузеру видео
		// и шрифты. По умолчанию он берёт 3000 — тот самый, где уже сидит
		// наше приложение. Запросы за кадрами уходили к нам, мы отвечали
		// «не найдено», и рендер вставал на первом же кадре с видео.
		`--port=${config.render.remotionPort}`,
		// Кэш распакованных кадров. Без предела он растёт под половину
		// памяти, а её размер Remotion берёт у всей машины, не у нашего
		// контейнера: на 322 гигабайтах хоста кэш съедал наши считанные
		// гигабайты, и рендер деградировал с двух секунд на кадр до сорока.
		`--offthreadvideo-cache-size-in-bytes=${config.render.videoCacheBytes}`,
	];

	// Число потоков задаём, только если попросили явно: сам Remotion
	// определяет доступные ядра точнее нас.
	if (config.render.concurrencyPerRender) {
		args.push(`--concurrency=${config.render.concurrencyPerRender}`);
	}

	// На сервере нет видеокарты, а браузер по умолчанию всё равно идёт
	// к ней и виснет на первом же кадре с видео. swangle — отрисовка
	// на процессоре; на рабочей машине с настоящей картой она не нужна.
	if (config.render.softwareGl) args.push('--gl=swangle');

	if (video.preview_only) {
		args.push(`--scale=${config.render.previewScale}`, '--jpeg-quality=70');
	} else {
		// Кадр рисуем в 1080×1920, отдаём в 720×1280 — именно так весят
		// ролики, которые реально выкладывают: полтора-два мегабита вместо
		// восьми. На вертикальном экране разницы не видно, а файл вчетверо
		// легче: быстрее уходит клиенту и быстрее сохраняется в телефон.
		// Площадка всё равно пережмёт его по-своему.
		args.push(`--scale=${config.render.deliverScale}`, `--crf=${config.render.crf}`);
	}

	try {
		await new Promise((resolve, reject) => {
			const child = spawn('npx', args, {cwd: ROOT, env: process.env});

			const killer = setTimeout(() => {
				child.kill('SIGKILL');
				reject(new Error(`Рендер не уложился в ${config.render.timeoutMin} минут`));
			}, config.render.timeoutMin * 60_000);

			// Весь вывод рендера пишем рядом с заказом. Без этого падение
			// на сервере выглядит как «что-то пошло не так», и причину
			// приходится угадывать по одной за деплой.
			const logFile = path.join(dir, 'render.log');
			let tail = '';

			const watch = (buf) => {
				const text = String(buf);
				tail = (tail + text).slice(-6000);
				fsSync.appendFileSync(logFile, text);

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
		// props оставляем: по ним видно, что именно ушло в картинку,
		// и почему на экране может не оказаться текста
	}

	return outFile;
};

export const runEngine = async ({video, onProgress, onStage}) => {
	const startedAt = Date.now();

	// Каждый заказ в своей папке: движок пишет туда транскрипт, планы,
	// временные файлы и готовый ролик.
	const dir = path.join(config.storage.root, 'engine', String(video.id));
	await fs.mkdir(path.join(dir, 'input'), {recursive: true});

	// Исходник кладём под именем без кириллицы и пробелов: движок
	// подставляет имя файла в пути артефактов.
	const ext = path.extname(video.source_path) || '.mp4';
	const source = path.join(dir, 'input', `source${ext}`);

	// Паузы срезаем до того, как движок услышит запись: дальше он считает
	// тайминги уже по укороченному звуку, и всё сходится само.
	const trimmed = await trimPauses(video.source_path, source).catch((err) => {
		console.error(`  ролик ${video.id} · паузы срезать не вышло: ${String(err.message).slice(0, 140)}`);
		return null;
	});

	if (trimmed) {
		onStage?.('Убираю паузы', 3);
		console.log(
			`  ролик ${video.id} · срезано пауз ${trimmed.pauses} на ${trimmed.cut.toFixed(1)}с`
		);
	} else {
		await fs.copyFile(video.source_path, source);
	}

	// Слушаем речь: слова с таймингами — всё, что нужно дальше.
	onStage?.('Слушаю речь', 10);
	const heard = await listen(source);

	if (!heard.montage.scenes.length) {
		throw new Error(
			heard.error
				? `Не удалось разобрать речь: ${String(heard.error).slice(0, 200)}`
				: 'В записи не нашлось речи — проверь, есть ли в файле звук'
		);
	}

	console.log(
		`  ролик ${video.id} · распознано ${heard.words} слов (${heard.provider})` +
		` за ${(heard.ms / 1000).toFixed(1)}с · реплик ${heard.montage.scenes.length}`
	);

	const montage = heard.montage;

	// Рисуем: что показать и когда — решила модель, как это выглядит —
	// решают наши компоненты.
	const outFile = await renderOurs({video, source, montage, dir, onProgress, onStage});

	return {
		outFile,
		dir,
		ms: Date.now() - startedAt,
		outputBytes: await sizeOf(outFile),
		// Сколько срезано пауз — это и есть весь речевой монтаж.
		speech: trimmed ? {removed_duration: trimmed.cut, pauses: trimmed.pauses} : null,
		words: heard.words,
		// Кто распознавал. Без ключа речь размечается по тишине, и писать
		// в лог имя сервиса было бы враньём.
		speechProvider: hasSpeech() ? config.speech.provider : 'границы по паузам',
	};
};

// Рабочая папка заказа после переноса результата не нужна.
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

// HTTP: API мини-аппа, отдача файлов, вебхуки.

import fs from 'node:fs';
import fsp from 'node:fs/promises';
import path from 'node:path';
import {pipeline} from 'node:stream/promises';
import Fastify from 'fastify';
import multipart from '@fastify/multipart';
import fstatic from '@fastify/static';

import {config, hasLava} from './config.js';
import {q, one, many, tx} from './db.js';
import {parseInitData} from './auth.js';
import {
	upsertUser, publicUser, spendCreditsIn,
	addCredits, rewardReferrer, getUser,
} from './users.js';
import {PACKAGES, findPackage} from './packages.js';
import {TEMPLATES} from './pipeline/plan.js';
import {probeDuration} from './pipeline/transcribe.js';
import {startPayment, applyWebhook, verifyWebhook} from './lava.js';

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');

// ── защита от двойного запуска ────────────────────────────────
// Два уровня. Первый — ключ идемпотентности от клиента: повторная
// отправка того же запроса возвращает уже созданный ролик, а не
// списывает второй кредит. Второй — окно на сервере: оно ловит
// двойной тап даже от клиента, который ключ не прислал.

const CREATE_COOLDOWN_SEC = Number(process.env.CREATE_COOLDOWN_SEC ?? 15);

const clientToken = (req) => {
	const raw =
		req.headers['x-request-id'] ||
		req.headers['idempotency-key'] ||
		req.body?.requestId;
	const token = String(raw ?? '').trim().slice(0, 120);
	return token || null;
};

// Уникальный индекс videos(user_id, client_token) — последняя линия
// обороны на случай, если два запроса пройдут проверку одновременно.
const isDuplicateKey = (err) => err?.code === '23505';

const byToken = (userId, token) =>
	token
		? one('SELECT * FROM videos WHERE user_id = $1 AND client_token = $2', [userId, token])
		: null;

// Ролик, поставленный секунду назад, — почти наверняка тот же самый.
const recentlyStarted = (userId) =>
	CREATE_COOLDOWN_SEC > 0
		? one(
				`SELECT id, title FROM videos
				 WHERE user_id = $1 AND status IN ('queued','running')
				   AND created_at > NOW() - ($2 || ' seconds')::interval
				 ORDER BY id DESC LIMIT 1`,
				[userId, CREATE_COOLDOWN_SEC]
			)
		: null;

export const buildApi = async ({notify}) => {
	const app = Fastify({
		logger: false,
		bodyLimit: 2 * 1024 * 1024,
		trustProxy: true,
	});

	await app.register(multipart, {
		limits: {fileSize: config.storage.maxUploadMb * 1024 * 1024, files: 1},
	});

	// Мини-апп отдаётся статикой с этого же домена — Telegram требует https,
	// а Railway его уже даёт.
	await app.register(fstatic, {
		root: path.join(ROOT, 'miniapp'),
		prefix: '/app/',
	});

	// Шрифты нужны и рендеру, и мини-аппу: в приложении кнопка выбора
	// подписана тем самым шрифтом, который выбираешь.
	await app.register(fstatic, {
		root: path.join(ROOT, 'public', 'fonts'),
		prefix: '/fonts/',
		decorateReply: false,
	});

	// Сырое тело вебхука нужно для проверки подписи: после JSON.parse
	// байты уже не те, и HMAC не сойдётся.
	app.addContentTypeParser(
		'application/json',
		{parseAs: 'string'},
		(req, body, done) => {
			req.rawBody = body;
			try {
				done(null, body ? JSON.parse(body) : {});
			} catch (err) {
				done(err);
			}
		}
	);

	// ── авторизация по initData ────────────────────────────────
	const auth = async (req, reply) => {
		const initData =
			req.headers['x-init-data'] || req.body?.initData || req.query?.initData;
		const parsed = parseInitData(initData);
		if (!parsed.ok) {
			reply.code(401).send({error: parsed.reason});
			return null;
		}
		const user = await upsertUser(parsed.user, parsed.startParam);
		req.user = user;
		return user;
	};

	// ── справочники ────────────────────────────────────────────
	// Версия сборки: без неё непонятно, доехал ли до сервера свежий код
	// или он крутит старый и чинишь ты вхолостую.
	app.get('/api/health', async () => ({
		ok: true,
		lava: hasLava(),
		speech: config.speech.provider,
		build: (process.env.RAILWAY_GIT_COMMIT_SHA || 'local').slice(0, 7),
	}));

	// Шрифты, из которых клиент выбирает в мини-аппе. Список берётся
	// из того, что реально лежит в public/fonts: положил файл — появился
	// в приложении, ничего дописывать не нужно.
	const FONT_TITLES = {
		Montserrat: 'Montserrat — универсальный',
		Unbounded: 'Unbounded — дисплейный, жирный',
		Oswald: 'Oswald — узкий, под заголовки',
		GolosText: 'Golos — спокойный, для длинного текста',
		Manrope: 'Manrope — мягкий гротеск',
		Onest: 'Onest — свежий гротеск',
		Rubik: 'Rubik — тяжёлые начертания',
		AlumniSans: 'Alumni Sans — узкий капс',
		Inter: 'Inter — нейтральный',
		Bitter: 'Bitter — с засечками',
	};

	const listFonts = async () => {
		try {
			const files = await fsp.readdir(path.join(ROOT, 'public', 'fonts'));
			return files
				.filter((f) => /\.(ttf|otf)$/i.test(f))
				.map((f) => {
					const key = f.replace(/\.(ttf|otf)$/i, '');
					return {key, title: FONT_TITLES[key] ?? key};
				});
		} catch {
			return [];
		}
	};

	app.get('/api/meta', async () => ({
		packages: PACKAGES,
		templates: TEMPLATES,
		fonts: await listFonts(),
		packageDays: config.packageDays,
		previewCost: config.render.previewCost,
		// Лимиты отдаём клиенту, чтобы он отсекал негодный файл
		// до загрузки, а не после сотни мегабайт впустую.
		maxDurationSec: config.storage.maxDurationSec,
		maxUploadMb: config.storage.maxUploadMb,
		keepDays: config.storage.outputKeepDays,
	}));

	// ── профиль ────────────────────────────────────────────────
	app.post('/api/me', async (req, reply) => {
		const user = await auth(req, reply);
		if (!user) return;

		const stats = await one(
			`SELECT
			   COUNT(*) FILTER (WHERE status IN ('ready','expired')) AS ready,
			   COUNT(*) FILTER (WHERE status IN ('queued','running')) AS active,
			   COUNT(*) FILTER (WHERE parent_id IS NOT NULL) AS edits
			 FROM videos WHERE user_id = $1`,
			[user.id]
		);

		const payments = await many(
			`SELECT package_code, amount, currency, paid_at FROM payments
			 WHERE user_id = $1 AND status = 'paid' ORDER BY paid_at DESC LIMIT 10`,
			[user.id]
		);

		return {
			user: publicUser(user),
			stats: {
				ready: Number(stats.ready),
				active: Number(stats.active),
				edits: Number(stats.edits),
			},
			payments,
			refLink: `https://t.me/${process.env.BOT_USERNAME || 'your_bot'}?start=r_${user.ref_code}`,
		};
	});

	// ── оплата ─────────────────────────────────────────────────
	app.post('/api/pay', async (req, reply) => {
		const user = await auth(req, reply);
		if (!user) return;

		const pkg = findPackage(req.body?.package);
		if (!pkg) return reply.code(400).send({error: 'Неизвестный пакет'});

		try {
			const out = await startPayment(user, pkg.code);
			return {ok: true, ...out, package: pkg};
		} catch (err) {
			req.log?.error?.(err);
			return reply.code(502).send({error: `Касса не ответила: ${err.message}`});
		}
	});

	// Заглушка оплаты, пока не подключена касса. В проде недоступна.
	app.get('/pay/mock/:id', async (req, reply) => {
		if (hasLava()) return reply.code(404).send('Недоступно');

		const payment = await one('SELECT * FROM payments WHERE id = $1', [req.params.id]);
		if (!payment) return reply.code(404).send('Платёж не найден');

		if (payment.status !== 'paid') {
			await q("UPDATE payments SET status = 'paid', paid_at = NOW() WHERE id = $1", [payment.id]);
			await addCredits(payment.user_id, payment.credits, `Пакет ${payment.package_code} (тест)`, String(payment.id));
			await rewardReferrer(payment.user_id);
			await notify(payment.user_id, {type: 'paid', payment});
		}
		reply.type('text/html; charset=utf-8').send(
			`<meta name="viewport" content="width=device-width"><body style="font-family:system-ui;background:#0B0A09;color:#F0C070;display:grid;place-items:center;height:100vh;margin:0"><div style="text-align:center"><h2>Тестовая оплата прошла</h2><p style="color:#8A7D74">Начислено роликов: ${payment.credits}. Возвращайся в бот.</p></div></body>`
		);
	});

	// ── вебхук кассы ───────────────────────────────────────────
	app.post('/webhook/lava', async (req, reply) => {
		const signature =
			req.headers['x-api-key'] ||
			req.headers['x-signature'] ||
			req.headers['signature'];

		if (!verifyWebhook(req.rawBody ?? '', signature)) {
			return reply.code(403).send({error: 'Подпись не сходится'});
		}

		try {
			const payment = await applyWebhook(req.body);
			if (payment) {
				await addCredits(
					payment.user_id,
					payment.credits,
					`Пакет ${payment.package_code}`,
					String(payment.id)
				);
				await rewardReferrer(payment.user_id);
				await notify(payment.user_id, {type: 'paid', payment});
			}
			return {ok: true};
		} catch (err) {
			console.error('вебхук Lava:', err.message);
			// 200 намеренно: иначе касса будет долбить повторами,
			// а проблема на нашей стороне и повтор её не решит.
			return reply.code(200).send({ok: false, error: err.message});
		}
	});

	// ── ролики ─────────────────────────────────────────────────
	app.post('/api/videos', async (req, reply) => {
		const user = await auth(req, reply);
		if (!user) return;

		const rows = await many(
			`SELECT v.id, v.title, v.status, v.template, v.duration_sec, v.preview_only,
			        v.created_at, v.error, v.keep_until, v.output_deleted_at,
			        v.share_token, v.output_bytes, j.progress, j.stage
			 FROM videos v
			 LEFT JOIN LATERAL (
			   SELECT progress, stage FROM jobs WHERE video_id = v.id ORDER BY id DESC LIMIT 1
			 ) j ON TRUE
			 WHERE v.user_id = $1
			 ORDER BY v.created_at DESC LIMIT 60`,
			[user.id]
		);

		return {
			videos: rows.map((v) => ({
				id: Number(v.id),
				title: v.title,
				status: v.status,
				template: v.template,
				duration: v.duration_sec ? Number(v.duration_sec) : null,
				preview: v.preview_only,
				createdAt: v.created_at,
				error: v.error,
				progress: v.progress ?? 0,
				stage: v.stage,
				poster: `/media/poster/${v.id}`,
				file: v.status === 'ready' ? `/media/video/${v.id}` : null,
				// Прямая ссылка: её же бот присылает в чат.
				download: v.share_token ? `${config.publicUrl}/dl/${v.share_token}` : null,
				size: v.output_bytes ? Number(v.output_bytes) : null,
				// До какого числа ролик лежит на диске.
				keepUntil: v.keep_until,
				expired: Boolean(v.output_deleted_at),
			})),
			// Клиенту полезно показать срок хранения до того, как ролик сгорит.
			keepDays: config.storage.outputKeepDays,
		};
	});

	// Загрузка исходника и постановка в очередь — одним запросом,
	// чтобы не плодить недоделанные черновики.
	app.post('/api/videos/create', async (req, reply) => {
		const parsed = parseInitData(req.headers['x-init-data']);
		if (!parsed.ok) return reply.code(401).send({error: parsed.reason});
		const user = await upsertUser(parsed.user, parsed.startParam);

		// Повтор того же запроса не должен стоить второго ролика.
		// Проверяем до чтения файла: незачем качать сотню мегабайт,
		// чтобы потом их выбросить.
		const token = clientToken(req);
		const already = await byToken(user.id, token);
		if (already) {
			return {ok: true, id: Number(already.id), duplicate: true};
		}

		const fields = {};
		let saved = null;

		for await (const part of req.parts()) {
			if (part.type === 'file') {
				const dir = path.join(config.storage.root, 'src', String(user.id));
				await fsp.mkdir(dir, {recursive: true});
				const ext = path.extname(part.filename || '.mp4').slice(0, 8) || '.mp4';
				saved = path.join(dir, `${Date.now()}${ext}`);
				await pipeline(part.file, fs.createWriteStream(saved));
				if (part.file.truncated) {
					await fsp.unlink(saved).catch(() => {});
					return reply.code(413).send({
						error: `Файл больше ${config.storage.maxUploadMb} МБ`,
					});
				}
			} else {
				fields[part.fieldname] = part.value;
			}
		}

		if (!saved) return reply.code(400).send({error: 'Не приложен файл видео'});

		const drop = async () => { await fsp.unlink(saved).catch(() => {}); };

		// Длительность проверяем до списания кредита: клиент не должен
		// платить за файл, который мы всё равно не возьмём в работу.
		let duration;
		try {
			duration = await probeDuration(saved);
		} catch {
			await drop();
			return reply.code(415).send({error: 'Не удалось прочитать файл — это точно видео?'});
		}

		if (!duration) {
			await drop();
			return reply.code(415).send({error: 'В файле не нашлось видеодорожки'});
		}

		const limit = config.storage.maxDurationSec;
		if (duration > limit) {
			await drop();
			return reply.code(413).send({
				error: `Видео длиной ${Math.round(duration)} с — дольше ${Math.round(limit / 60)} минут. ` +
					'Обрежь исходник и загрузи снова.',
				duration: Math.round(duration),
				limit,
			});
		}

		// Клиент без ключа идемпотентности: ловим повтор по времени.
		const token2 = token ?? clientToken(req) ?? fields.requestId ?? null;
		const dup = await byToken(user.id, token2);
		if (dup) {
			await drop();
			return {ok: true, id: Number(dup.id), duplicate: true};
		}

		if (!token2) {
			const recent = await recentlyStarted(user.id);
			if (recent) {
				await drop();
				return reply.code(409).send({
					error: 'Ролик уже поставлен в очередь несколько секунд назад. ' +
						'Дождись его или обнови список.',
					id: Number(recent.id),
					duplicate: true,
				});
			}
		}

		const preview = fields.preview === 'true' || fields.preview === '1';
		const cost = preview ? config.render.previewCost : 1;

		// Списание, карточка ролика и задача — одной транзакцией.
		// Раньше это были три отдельных запроса: упади любой из них,
		// кредит оставался списанным, а ролика не появлялось.
		let result;
		try {
			result = await tx(async (client) => {
				const spent = await spendCreditsIn(
					client, user.id, cost, preview ? 'Черновик' : 'Монтаж ролика'
				);
				if (!spent.ok) return {error: spent.reason, code: 402};

				const {rows} = await client.query(
					`INSERT INTO videos (user_id, title, status, template, brief, reference_url,
					                     source_path, preview_only, cost, client_token, duration_sec, font)
					 VALUES ($1,$2,'queued',$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING id`,
					[
						user.id,
						(fields.title || 'Новый ролик').slice(0, 120),
						fields.template || 'expose',
						(fields.brief || '').slice(0, 4000),
						(fields.reference || '').slice(0, 500),
						saved,
						preview,
						cost,
						token2,
						Number(duration.toFixed(2)),
						(fields.font || '').slice(0, 40) || null,
					]
				);
				const video = rows[0];
				await client.query('INSERT INTO jobs (video_id) VALUES ($1)', [video.id]);
				return {id: Number(video.id), credits: spent.credits};
			});
		} catch (err) {
			await drop();
			// Гонка двух одинаковых запросов: индекс не пустил второй.
			if (isDuplicateKey(err)) {
				const existing = await byToken(user.id, token2);
				if (existing) return {ok: true, id: Number(existing.id), duplicate: true};
			}
			throw err;
		}

		if (result.error) {
			await drop();
			return reply.code(result.code).send({error: result.error});
		}

		return {ok: true, id: result.id, credits: result.credits};
	});

	// Пересборка с метками правок — стоит один ролик из пакета.
	app.post('/api/videos/:id/rebuild', async (req, reply) => {
		const user = await auth(req, reply);
		if (!user) return;

		const src = await one('SELECT * FROM videos WHERE id = $1 AND user_id = $2', [
			req.params.id,
			user.id,
		]);
		if (!src) return reply.code(404).send({error: 'Ролик не найден'});

		const marks = Array.isArray(req.body?.marks) ? req.body.marks : [];
		if (!marks.length) {
			return reply.code(400).send({error: 'Нет ни одной метки — нечего менять'});
		}

		// Пересборка идёт от исходника. Если он сгорел по сроку хранения,
		// правку сделать не из чего — говорим прямо, а не падаем в рендере.
		if (src.source_deleted_at || !src.source_path) {
			const keep = config.storage.sourceKeepDays;
			return reply.code(410).send({
				error: keep > 0
					? `Исходник удалён: он хранится ${keep} дн. после монтажа. Загрузи видео заново.`
					: 'Исходники не хранятся после монтажа — загрузи видео заново.',
			});
		}

		const token = clientToken(req);
		const already = await byToken(user.id, token);
		if (already) return {ok: true, id: Number(already.id), duplicate: true};

		// Вторая правка того же ролика, пока первая ещё в работе, —
		// это почти всегда двойное нажатие.
		const active = await one(
			`SELECT id FROM videos
			 WHERE parent_id = $1 AND status IN ('queued','running')
			 ORDER BY id DESC LIMIT 1`,
			[src.id]
		);
		if (active) {
			return reply.code(409).send({
				error: 'Правка этого ролика уже собирается — дождись её.',
				id: Number(active.id),
				duplicate: true,
			});
		}

		let result;
		try {
			result = await tx(async (client) => {
				const spent = await spendCreditsIn(client, user.id, 1, 'Правка ролика', String(src.id));
				if (!spent.ok) return {error: spent.reason, code: 402};

				const {rows} = await client.query(
					`INSERT INTO videos (user_id, title, status, template, brief, source_path,
					                     parent_id, cost, client_token)
					 VALUES ($1,$2,'queued',$3,$4,$5,$6,1,$7) RETURNING id`,
					[user.id, `${src.title} · правка`, src.template, src.brief,
					 src.source_path, src.id, token]
				);
				const copy = rows[0];

				for (const m of marks.slice(0, 40)) {
					await client.query(
						'INSERT INTO marks (video_id, at_sec, note) VALUES ($1,$2,$3)',
						[copy.id, Number(m.at) || 0, String(m.note || '').slice(0, 500)]
					);
				}

				await client.query('INSERT INTO jobs (video_id) VALUES ($1)', [copy.id]);
				return {id: Number(copy.id), credits: spent.credits};
			});
		} catch (err) {
			if (isDuplicateKey(err)) {
				const existing = await byToken(user.id, token);
				if (existing) return {ok: true, id: Number(existing.id), duplicate: true};
			}
			throw err;
		}

		if (result.error) return reply.code(result.code).send({error: result.error});
		return {ok: true, id: result.id, credits: result.credits};
	});

	app.post('/api/videos/:id/delete', async (req, reply) => {
		const user = await auth(req, reply);
		if (!user) return;

		const video = await one('SELECT * FROM videos WHERE id = $1 AND user_id = $2', [
			req.params.id,
			user.id,
		]);
		if (!video) return reply.code(404).send({error: 'Ролик не найден'});

		for (const f of [video.source_path, video.output_path, video.poster_path]) {
			if (f) await fsp.unlink(f).catch(() => {});
		}
		await q('DELETE FROM videos WHERE id = $1', [video.id]);
		return {ok: true};
	});

	// ── отдача медиа ───────────────────────────────────────────
	// Ссылки короткоживущие и без токена: id последовательные, поэтому
	// проверяем владельца по initData из query.
	const sendFile = async (req, reply, column, type) => {
		const parsed = parseInitData(req.query?.initData);
		if (!parsed.ok) return reply.code(401).send({error: parsed.reason});

		const video = await one(
			`SELECT v.${column} AS file FROM videos v
			 JOIN users u ON u.id = v.user_id
			 WHERE v.id = $1 AND u.tg_id = $2`,
			[req.params.id, parsed.user.id]
		);
		if (!video?.file) return reply.code(404).send({error: 'Файл ещё не готов'});

		try {
			await fsp.access(video.file);
		} catch {
			return reply.code(404).send({error: 'Файл пропал с диска'});
		}
		return reply.type(type).send(fs.createReadStream(video.file));
	};

	app.get('/media/video/:id', (req, reply) =>
		sendFile(req, reply, 'output_path', 'video/mp4')
	);
	app.get('/media/poster/:id', (req, reply) =>
		sendFile(req, reply, 'poster_path', 'image/jpeg')
	);

	// Скачивание по токену: ссылка уходит в чат, а туда initData
	// не подставить. Токен выдаётся при готовности ролика и умирает
	// вместе с файлом по истечении срока хранения.
	app.get('/dl/:token', async (req, reply) => {
		const token = String(req.params.token || '').slice(0, 120);
		const video = await one(
			`SELECT id, title, output_path, output_deleted_at, keep_until
			 FROM videos WHERE share_token = $1`,
			[token]
		);

		if (!video || video.output_deleted_at || !video.output_path) {
			return reply.code(404).type('text/plain; charset=utf-8')
				.send('Ссылка больше не действует: срок хранения ролика истёк.');
		}

		let stat;
		try {
			stat = await fsp.stat(video.output_path);
		} catch {
			return reply.code(404).type('text/plain; charset=utf-8')
				.send('Файл не найден на диске.');
		}

		const name = `${String(video.title || 'reel').replace(/[^\p{L}\p{N}\-_ ]/gu, '').trim() || 'reel'}.mp4`;
		reply.header('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent(name)}`);
		reply.header('Accept-Ranges', 'bytes');
		reply.type('video/mp4');

		// Перемотка и докачка: без Range телефон тянет файл целиком
		// заново при каждом касании плеера.
		const range = /^bytes=(\d*)-(\d*)$/.exec(req.headers.range ?? '');
		if (range) {
			const start = range[1] ? Number(range[1]) : 0;
			const end = range[2] ? Number(range[2]) : stat.size - 1;

			if (start >= stat.size || end >= stat.size || start > end) {
				return reply.code(416).header('Content-Range', `bytes */${stat.size}`).send();
			}

			reply.code(206);
			reply.header('Content-Range', `bytes ${start}-${end}/${stat.size}`);
			reply.header('Content-Length', end - start + 1);
			return reply.send(fs.createReadStream(video.output_path, {start, end}));
		}

		reply.header('Content-Length', stat.size);
		return reply.send(fs.createReadStream(video.output_path));
	});

	app.get('/', async (req, reply) => reply.redirect('/app/'));

	return app;
};

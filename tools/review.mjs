// Прогон вычитки: загрузка → расшифровка → правка текста → монтаж.
//
//   node tools/review.mjs
//
// Проверяет главное обещание этого шага: пока человек не подтвердил
// текст, ролик из пакета не списан, а после подтверждения в монтаж
// уходит именно исправленное слово, а не то, что послышалось.
//
// Нужен работающий Postgres из DATABASE_URL и ffmpeg в PATH.

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.chdir(ROOT);

const {config} = await import(`${ROOT}/server/config.js`);
const {migrate, q, one} = await import(`${ROOT}/server/db.js`);
const {buildApi} = await import(`${ROOT}/server/api.js`);
const {startWorker, setNotifier} = await import(`${ROOT}/server/worker.js`);

const ok = [];
const bad = [];
const say = (s) => console.log(s);
const pass = (name, extra = '') => { ok.push(name); say(`  ✓ ${name}${extra ? ' — ' + extra : ''}`); };
const fail = (name, why) => { bad.push(`${name}: ${why}`); say(`  ✖ ${name} — ${why}`); };

const signInitData = (user) => {
	const params = new URLSearchParams();
	params.set('user', JSON.stringify(user));
	params.set('auth_date', String(Math.floor(Date.now() / 1000)));
	params.set('query_id', 'AAF' + crypto.randomBytes(6).toString('hex'));
	const check = [...params.entries()].map(([k, v]) => `${k}=${v}`).sort().join('\n');
	const secret = crypto.createHmac('sha256', 'WebAppData').update(config.bot.token).digest();
	params.set('hash', crypto.createHmac('sha256', secret).update(check).digest('hex'));
	return params.toString();
};

const USER = {id: 777002, first_name: 'Вычитка', username: 'e2e_review'};
const INIT = signInitData(USER);

say('\n═══ ПОДГОТОВКА ═══');
await migrate();
const old = await one('SELECT id FROM users WHERE tg_id = $1', [USER.id]);
if (old) {
	const vids = await q('SELECT source_path, output_path, poster_path FROM videos WHERE user_id = $1', [old.id]);
	for (const v of vids.rows) {
		for (const f of [v.source_path, v.output_path, v.poster_path]) {
			if (f) await fs.unlink(f).catch(() => {});
		}
	}
	await q('DELETE FROM users WHERE id = $1', [old.id]);
}
pass('база чистая, миграции применены');

const events = [];
setNotifier(async (userId, event) => { events.push({userId, ...event}); });

const app = await buildApi({notify: async (u, e) => { events.push({userId: u, ...e}); }});
await app.listen({port: 0, host: '127.0.0.1'});
const BASE = `http://127.0.0.1:${app.server.address().port}`;
const stopWorker = startWorker();
pass('сервер и воркер подняты', BASE);

const call = async (p, opts = {}) => {
	const res = await fetch(BASE + p, {...opts, headers: {'X-Init-Data': INIT, ...(opts.headers ?? {})}});
	const text = await res.text();
	let json = null;
	try { json = JSON.parse(text); } catch {}
	return {status: res.status, json, text};
};

const waitFor = async (want, limitMs = 240_000) => {
	const till = Date.now() + limitMs;
	while (Date.now() < till) {
		const v = await one('SELECT status, error FROM videos WHERE id = $1', [VIDEO]);
		if (v && want.includes(v.status)) return v;
		if (v?.status === 'failed') return v;
		await new Promise((r) => setTimeout(r, 1200));
	}
	return null;
};

let VIDEO = null;

try {
	const user = await one('SELECT id FROM users WHERE tg_id = $1', [USER.id])
		?? (await call('/api/me', {method: 'POST'}), await one('SELECT id FROM users WHERE tg_id = $1', [USER.id]));
	const {addCredits} = await import(`${ROOT}/server/users.js`);
	await addCredits(user.id, 5, 'Тестовый пакет');
	pass('начислено 5 роликов');

	// ═══ 0. ПОЛЯ СХОДЯТСЯ ═══
	//
	// Приложение шлёт поля в теле запроса, сервер переносит их по списку.
	// Забыть поле в списке — тихая поломка: клиент его отправляет, сервер
	// выбрасывает, и всё работает так, будто человек ничего не просил.
	// Именно так пропала вычитка расшифровки. Сверяем автоматически.
	say('\n═══ 0. ПОЛЯ ПРИЛОЖЕНИЯ И СЕРВЕРА ═══');

	const appText = await fs.readFile(`${ROOT}/miniapp/index.html`, 'utf8');
	const apiText = await fs.readFile(`${ROOT}/server/api.js`, 'utf8');

	const body = appText.slice(
		appText.indexOf('uploadIds: ids.slice'),
		appText.indexOf('})\n      });', appText.indexOf('uploadIds: ids.slice'))
	);
	const sent = [...body.matchAll(/^\s{10}([a-zA-Z]+):/gm)].map((m) => m[1]);

	const listed = apiText
		.slice(apiText.indexOf("for (const key of ["), apiText.indexOf('])', apiText.indexOf("for (const key of [")))
		.match(/'[a-zA-Z]+'/g)
		?.map((s) => s.replace(/'/g, '')) ?? [];

	// Три поля обрабатываются отдельно: это не текст, а ключи загрузок.
	const own = ['uploadIds', 'clipIds', 'musicId'];
	const lost = sent.filter((k) => !own.includes(k) && !listed.includes(k));

	sent.length && !lost.length
		? pass('все поля приложения принимаются сервером', sent.join(', '))
		: fail('поля разошлись', lost.length ? `сервер выбросит: ${lost.join(', ')}` : 'не смог разобрать');

	// ═══ 1. ЗАГРУЗКА БЕЗ СПИСАНИЯ ═══
	say('\n═══ 1. ЗАГРУЗКА НА ПРОСЛУШИВАНИЕ ═══');

	// Файл шлём кусками — ровно так, как это делает приложение.
	//
	// Раньше здесь стоял FormData: файл целиком одним запросом. Это другой
	// путь в сервере, и он копирует поля запроса подряд, а тот, которым
	// ходит приложение, — по списку. Из-за этого прогон не заметил, что в
	// списке забыли «review», и вычитка молча не работала у клиента, хотя
	// тест был зелёный. Проверять надо тем же путём, которым ходит человек.
	const buf = await fs.readFile('public/base.mp4');

	const begun = await call('/api/upload/begin', {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({name: 'base.mp4', size: buf.length}),
	});
	const upId = begun.json?.id;
	upId ? pass('загрузка начата', `кусками по ${((begun.json.chunk ?? 0) / 1048576).toFixed(0)} МБ`)
		: fail('начало загрузки', begun.text.slice(0, 160));

	const chunk = begun.json?.chunk ?? 8 * 1024 * 1024;
	for (let at = 0; at < buf.length; at += chunk) {
		const piece = buf.subarray(at, Math.min(at + chunk, buf.length));
		const put = await call(`/api/upload/part?id=${upId}&at=${at}`, {
			method: 'POST',
			headers: {'Content-Type': 'application/octet-stream'},
			body: piece,
		});
		if (put.status !== 200) { fail('кусок загрузки', put.text.slice(0, 160)); break; }
	}

	const made = await call('/api/videos/create', {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({
			uploadIds: [upId],
			title: 'Вычитка', template: 'expose', brief: 'проверка вычитки',
			preview: '1', review: '1',
		}),
	});
	made.status === 200 && made.json?.id && made.json?.review
		? pass('ролик принят на прослушивание', `id ${made.json.id}`)
		: fail('загрузка', `статус ${made.status}: ${made.text.slice(0, 200)}`);

	VIDEO = made.json?.id;
	if (!VIDEO) throw new Error('ролик не создался');

	const afterUpload = await one('SELECT credits FROM users WHERE id = $1', [user.id]);
	Number(afterUpload.credits) === 5
		? pass('пакет не тронут', '5 роликов на месте')
		: fail('списание раньше времени', `осталось ${afterUpload.credits}, ждали 5`);

	// ═══ 2. РАСШИФРОВКА ═══
	say('\n═══ 2. РАСШИФРОВКА ═══');

	const listened = await waitFor(['listened'], 180_000);
	listened?.status === 'listened'
		? pass('запись прослушана')
		: fail('расшифровка', listened?.error || 'не дождались');
	if (listened?.status !== 'listened') throw new Error('нет расшифровки');

	const got = await call(`/api/videos/${VIDEO}/transcript`);
	const lines = got.json?.lines ?? [];
	lines.length
		? pass('текст отдан построчно', `реплик ${lines.length}, первая: «${lines[0].text.slice(0, 46)}…»`)
		: fail('текст', got.text.slice(0, 200));

	const timed = lines.every((l) => l.end > l.start);
	timed ? pass('у каждой реплики свой тайминг') : fail('тайминги', 'есть реплики с нулевой длиной');

	events.some((e) => e.type === 'listened')
		? pass('человека позвали читать текст', 'уведомление ушло')
		: fail('уведомление', 'о готовой расшифровке не сообщили');

	// ═══ 3. ПРАВКА ═══
	say('\n═══ 3. ПРАВКА ТЕКСТА ═══');

	// Ломаем первую реплику так, как её сломало бы распознавание, и
	// проверяем, что в монтаж уедет именно наша версия.
	const MARK = 'ООшка';
	const wasFirst = lines[0].text;
	const nowFirst = wasFirst.replace(/\S+/, MARK);

	const started = await call(`/api/videos/${VIDEO}/transcript`, {
		method: 'POST',
		headers: {'Content-Type': 'application/json'},
		body: JSON.stringify({lines: [{i: 0, text: nowFirst}]}),
	});
	started.status === 200 && started.json?.edited === 1
		? pass('правка принята, монтаж запущен', `«${wasFirst.split(/\s+/)[0]}» → «${MARK}»`)
		: fail('запуск монтажа', `статус ${started.status}: ${started.text.slice(0, 200)}`);

	const afterStart = await one('SELECT credits FROM users WHERE id = $1', [user.id]);
	Number(afterStart.credits) === 4.7
		? pass('ролик списался только сейчас', '4.7 из 5')
		: fail('списание', `осталось ${afterStart.credits}, ждали 4.7`);

	const saved = await one('SELECT transcript FROM videos WHERE id = $1', [VIDEO]);
	const firstWords = saved.transcript.scenes[0].words.map((w) => w.word);
	firstWords[0] === MARK
		? pass('исправленное слово легло в расшифровку', firstWords.slice(0, 4).join(' '))
		: fail('правка не сохранилась', firstWords.slice(0, 4).join(' '));

	// Тайминги нетронутых реплик обязаны остаться прежними: иначе правка
	// одного слова разъехалась бы по всему ролику.
	const same = lines.slice(1).every((l, i) => {
		const scene = saved.transcript.scenes[i + 1];
		return scene && Math.abs(scene.start - l.start) < 0.001;
	});
	same ? pass('нетронутые реплики сохранили тайминги') : fail('тайминги', 'сдвинулись у нетронутых реплик');

	// ═══ 4. МОНТАЖ ПО ВЫВЕРЕННОМУ ТЕКСТУ ═══
	say('\n═══ 4. МОНТАЖ ═══');

	const done = await waitFor(['ready', 'failed'], 420_000);
	done?.status === 'ready'
		? pass('ролик собран по вычитанному тексту')
		: fail('монтаж', done?.error?.slice(0, 200) || 'не дождались');

	if (done?.status === 'ready') {
		const out = await one('SELECT output_path, output_bytes, plan FROM videos WHERE id = $1', [VIDEO]);
		const size = Number(out.output_bytes || 0);
		size > 100_000
			? pass('файл на месте', `${(size / 1048576).toFixed(1)} МБ`)
			: fail('файл', `${size} байт`);
	}
} catch (err) {
	fail('прогон', String(err.message ?? err).slice(0, 300));
} finally {
	stopWorker?.();
	await app.close();
}

say(`\n═══ ИТОГ: ${ok.length} сошлось, ${bad.length} нет ═══`);
for (const b of bad) say(`  ✖ ${b}`);
process.exit(bad.length ? 1 : 0);

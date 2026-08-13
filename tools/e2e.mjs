// Полный прогон: загрузка → распознавание → монтаж → рендер → выдача ссылки.
// Всё через настоящий HTTP и настоящую базу. Бот не поднимается: initData
// подписывается тем же BOT_TOKEN, а уведомления перехватываются.
//
//   npm run e2e
//
// Нужен работающий Postgres из DATABASE_URL и ffmpeg в PATH.
// Прогон занимает несколько минут: внутри настоящий рендер.
// Тестовый пользователь и его ролики удаляются в начале каждого прогона.

import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import {createReadStream} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

// Путь к проекту берётся от самого файла: скрипт должен работать
// из любой папки, в том числе на чужой машине.
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.chdir(ROOT);

const {config} = await import(`${ROOT}/server/config.js`);
const {migrate, q, one, pool} = await import(`${ROOT}/server/db.js`);
const {buildApi} = await import(`${ROOT}/server/api.js`);
const {startWorker, setNotifier, sweepStorage} = await import(`${ROOT}/server/worker.js`);

const ok = [];
const bad = [];
const say = (s) => console.log(s);
const pass = (name, extra = '') => { ok.push(name); say(`  ✓ ${name}${extra ? ' — ' + extra : ''}`); };
const fail = (name, why) => { bad.push(`${name}: ${why}`); say(`  ✖ ${name} — ${why}`); };

// ── подписанный initData, как его прислал бы Telegram ──
const signInitData = (user, ageSec = 0) => {
	const params = new URLSearchParams();
	params.set('user', JSON.stringify(user));
	params.set('auth_date', String(Math.floor(Date.now() / 1000) - ageSec));
	params.set('query_id', 'AAF' + crypto.randomBytes(6).toString('hex'));

	const check = [...params.entries()].map(([k, v]) => `${k}=${v}`).sort().join('\n');
	const secret = crypto.createHmac('sha256', 'WebAppData').update(config.bot.token).digest();
	params.set('hash', crypto.createHmac('sha256', secret).update(check).digest('hex'));
	return params.toString();
};

const USER = {id: 777001, first_name: 'Тест', last_name: 'Прогонов', username: 'e2e_tester'};
const INIT = signInitData(USER);

// ── чистка прошлого прогона ──
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

// ── поднимаем сервер и воркер ──
const events = [];
const notify = async (userId, event) => { events.push({userId, ...event}); };
setNotifier(notify);

const app = await buildApi({notify});
await app.listen({port: 0, host: '127.0.0.1'});
const BASE = `http://127.0.0.1:${app.server.address().port}`;
pass('сервер поднят', BASE);

const stopWorker = startWorker();

const call = async (path, opts = {}) => {
	const res = await fetch(BASE + path, {
		...opts,
		headers: {'X-Init-Data': INIT, ...(opts.headers ?? {})},
	});
	const text = await res.text();
	let json = null;
	try { json = JSON.parse(text); } catch {}
	return {status: res.status, json, text, headers: res.headers};
};

try {
	// ═══ 1. АВТОРИЗАЦИЯ ═══
	say('\n═══ 1. АВТОРИЗАЦИЯ ═══');

	const meta = await call('/api/meta');
	meta.json?.maxDurationSec === 180
		? pass('лимит длительности отдаётся клиенту', `${meta.json.maxDurationSec} с`)
		: fail('лимит длительности', JSON.stringify(meta.json?.maxDurationSec));

	const me = await call('/api/me', {method: 'POST'});
	me.status === 200 && me.json?.user?.name
		? pass('вход по подписи Telegram', `${me.json.user.name}, роликов ${me.json.user.credits}`)
		: fail('вход по подписи', me.text.slice(0, 120));

	// Мини-апп и сервер должны сойтись по методам: GET вместо POST
	// даёт 404, и клиент молча остаётся с пустым экраном.
	const html = await fs.readFile(`${ROOT}/miniapp/index.html`, 'utf8');
	const script = html.slice(html.indexOf('<script>\n(function'), html.indexOf('</script>', html.indexOf('<script>\n(function')));
	const used = [
		['/api/meta', 'GET'],
		['/api/me', 'POST'],
		['/api/videos', 'POST'],
		['/api/pay', 'POST'],
	];
	let mismatch = 0;
	for (const [route, method] of used) {
		if (!script.includes(route)) { fail('мини-апп не дёргает ' + route, ''); mismatch++; continue; }
		const probe = await fetch(BASE + route, {
			method,
			headers: {'X-Init-Data': INIT, 'Content-Type': 'application/json'},
			body: method === 'POST' ? '{}' : undefined,
		});
		if (probe.status === 404) { fail(`${method} ${route}`, 'сервер отвечает 404'); mismatch++; }
	}
	mismatch === 0
		? pass('все маршруты мини-аппа существуют', used.map(([r, m]) => `${m} ${r}`).join(', '))
		: fail('маршруты мини-аппа', `${mismatch} не сходятся`);

	const bad1 = await fetch(BASE + '/api/me', {
		method: 'POST',
		headers: {'X-Init-Data': INIT.replace(/user=[^&]*/, 'user=' + encodeURIComponent(JSON.stringify({...USER, id: 999})))},
	});
	bad1.status === 401
		? pass('подменённый id отбит', '401')
		: fail('подмена id', `прошла со статусом ${bad1.status}`);

	// ═══ 2. КРЕДИТЫ ═══
	say('\n═══ 2. ПАКЕТ ═══');
	const user = await one('SELECT id FROM users WHERE tg_id = $1', [USER.id]);
	const {addCredits} = await import(`${ROOT}/server/users.js`);
	await addCredits(user.id, 5, 'Тестовый пакет');
	pass('начислено 5 роликов');

	// ═══ 3. ЛИМИТ ДЛИТЕЛЬНОСТИ ═══
	say('\n═══ 3. ЛИМИТ 3 МИНУТЫ ═══');

	// Собираем ролик на 3.5 минуты из исходника — быстро, без перекодирования.
	const longFile = '/tmp/e2e-long.mp4';
	const {execFile} = await import('node:child_process');
	const {promisify} = await import('node:util');
	const run = promisify(execFile);
	await run('ffmpeg', ['-v', 'error', '-y', '-stream_loop', '4', '-i', 'public/base.mp4',
		'-t', '210', '-c', 'copy', longFile]);

	const sendFile = async (file, fields = {}, headers = {}) => {
		const form = new FormData();
		for (const [k, v] of Object.entries(fields)) form.append(k, String(v));
		const buf = await fs.readFile(file);
		form.append('file', new Blob([buf], {type: 'video/mp4'}), path.basename(file));
		return call('/api/videos/create', {method: 'POST', body: form, headers});
	};

	const tooLong = await sendFile(longFile, {title: 'Слишком длинный', template: 'expose'});
	tooLong.status === 413
		? pass('видео 210 с отклонено', tooLong.json.error.slice(0, 70))
		: fail('лимит длительности', `статус ${tooLong.status}: ${tooLong.text.slice(0, 120)}`);

	const balanceAfterReject = await one('SELECT credits FROM users WHERE id = $1', [user.id]);
	Number(balanceAfterReject.credits) === 5
		? pass('кредит за отклонённый файл не списан', '5 роликов на месте')
		: fail('кредит списан впустую', `осталось ${balanceAfterReject.credits}`);

	await fs.unlink(longFile).catch(() => {});

	// ═══ 4. ЗАЩИТА ОТ ДУБЛЕЙ ═══
	say('\n═══ 4. ЗАЩИТА ОТ ДВОЙНОГО ЗАПУСКА ═══');

	const token = 'e2e-' + crypto.randomBytes(6).toString('hex');
	const fields = {title: 'E2E прогон', template: 'expose', brief: 'проверка пайплайна', preview: '1'};

	const first = await sendFile('public/base.mp4', fields, {'X-Request-Id': token});
	first.status === 200 && first.json?.id
		? pass('ролик создан', `id ${first.json.id}, осталось ${first.json.credits}`)
		: fail('создание ролика', `статус ${first.status}: ${first.text.slice(0, 200)}`);

	const again = await sendFile('public/base.mp4', fields, {'X-Request-Id': token});
	again.json?.duplicate && again.json?.id === first.json.id
		? pass('повтор с тем же ключом вернул тот же ролик', `id ${again.json.id}`)
		: fail('повтор по ключу', JSON.stringify(again.json));

	const noKey = await sendFile('public/base.mp4', fields);
	noKey.status === 409
		? pass('двойной тап без ключа отбит', '409')
		: fail('окно защиты', `статус ${noKey.status}`);

	const spent = await one('SELECT credits FROM users WHERE id = $1', [user.id]);
	Number(spent.credits) === 4.7
		? pass('списан ровно один черновик', '4.7 из 5')
		: fail('списание', `осталось ${spent.credits}, ждали 4.7`);

	const VIDEO_ID = first.json.id;

	// ═══ 5. ОЧЕРЕДЬ И ПРОГРЕСС ═══
	say('\n═══ 5. ОЧЕРЕДЬ И ПРОГРЕСС ═══');

	const stages = new Set();
	let last = null;
	const started = Date.now();

	while (Date.now() - started < 15 * 60_000) {
		const list = await call('/api/videos', {method: 'POST'});
		const v = list.json.videos.find((x) => x.id === VIDEO_ID);
		if (!v) { fail('ролик пропал из списка', ''); break; }

		if (v.stage && v.stage !== last) {
			last = v.stage;
			stages.add(v.stage);
			say(`     ${String(v.progress).padStart(3)}%  ${v.stage}`);
		}
		if (v.status === 'ready' || v.status === 'failed') { last = v; break; }
		// Часто: разбор дорожки по паузам занимает полторы секунды,
		// при опросе раз в две секунды эта стадия просто не видна.
		await new Promise((r) => setTimeout(r, 250));
	}

	stages.size >= 3
		? pass('стадии видны клиенту', [...stages].join(' → '))
		: fail('стадии', `увидел только: ${[...stages].join(', ') || 'ничего'}`);

	// ═══ 6. РЕЗУЛЬТАТ ═══
	say('\n═══ 6. РЕЗУЛЬТАТ ═══');

	const done = await one('SELECT * FROM videos WHERE id = $1', [VIDEO_ID]);
	done.status === 'ready'
		? pass('ролик смонтирован', `${Number(done.duration_sec).toFixed(1)} с`)
		: fail('монтаж', `статус ${done.status}: ${(done.error || '').slice(0, 200)}`);

	if (done.status === 'ready') {
		done.speech_provider && done.render_ms && done.output_bytes
			? pass('метрики записаны',
					`речь ${done.speech_provider} · монтаж ${(done.render_ms/1000).toFixed(0)}с · ` +
					`вход ${(done.source_bytes/1048576).toFixed(1)}МБ → выход ${(done.output_bytes/1048576).toFixed(1)}МБ`)
			: fail('метрики', JSON.stringify({p: done.speech_provider, r: done.render_ms, o: done.output_bytes}));

		// Движок кладёт в plan свой отчёт качества — по нему видно,
		// что монтаж действительно состоялся, а не просто перекодировался файл.
		const quality = done.plan;
		Number.isFinite(Number(quality?.final_score))
			? pass('движок оценил монтаж',
					`итог ${Number(quality.final_score).toFixed(2)} · профиль ${quality.profile} · ` +
					`текст ${quality.text_score} · читаемость ${quality.readability_score} · ` +
					`лицо ${quality.face_safety_score}`)
			: fail('отчёт качества', JSON.stringify(quality)?.slice(0, 200) ?? 'пусто');

		Number(quality?.face_safety_score) >= 0.9 && Number(quality?.readability_score) >= 0.9
			? pass('субтитры в безопасных зонах и читаемы',
					`лицо ${quality.face_safety_score}, читаемость ${quality.readability_score}`)
			: fail('вёрстка субтитров',
					`лицо ${quality?.face_safety_score}, читаемость ${quality?.readability_score}`);

		await fs.access(done.output_path).then(
			() => pass('файл на диске', done.output_path.replace(ROOT, '.')),
			() => fail('файл', 'не найден')
		);

		// ═══ 7. ВЫДАЧА ССЫЛКОЙ ═══
		say('\n═══ 7. ВЫДАЧА ССЫЛКОЙ ═══');

		done.share_token
			? pass('токен ссылки выдан', done.share_token.slice(0, 10) + '…')
			: fail('токен', 'не выдан');

		const dl = await fetch(`${BASE}/dl/${done.share_token}`);
		const body = await dl.arrayBuffer();
		dl.status === 200 && body.byteLength === Number(done.output_bytes)
			? pass('ссылка отдаёт файл целиком', `${(body.byteLength/1048576).toFixed(1)} МБ, ${dl.headers.get('content-type')}`)
			: fail('скачивание', `статус ${dl.status}, ${body.byteLength} байт против ${done.output_bytes}`);

		const cd = dl.headers.get('content-disposition') ?? '';
		const fname = /filename\*=UTF-8''(\S+)/.exec(cd);
		cd.includes('attachment') && fname
			? pass('заголовок скачивания на месте', decodeURIComponent(fname[1]))
			: fail('content-disposition', cd);

		const part = await fetch(`${BASE}/dl/${done.share_token}`, {headers: {Range: 'bytes=0-1023'}});
		const partBody = await part.arrayBuffer();
		part.status === 206 && partBody.byteLength === 1024
			? pass('перемотка работает', `206, ${part.headers.get('content-range')}`)
			: fail('range-запрос', `статус ${part.status}, ${partBody.byteLength} байт`);

		const badToken = await fetch(`${BASE}/dl/нет-такого-токена`);
		badToken.status === 404
			? pass('чужой токен не работает', '404')
			: fail('чужой токен', `статус ${badToken.status}`);

		// ═══ 8. МЕДИА ДЛЯ МИНИ-АППА ═══
		say('\n═══ 8. МЕДИА ДЛЯ МИНИ-АППА ═══');

		const poster = await fetch(`${BASE}/media/poster/${VIDEO_ID}?initData=${encodeURIComponent(INIT)}`);
		const posterBody = await poster.arrayBuffer();
		poster.status === 200 && posterBody.byteLength > 1000
			? pass('обложка отдаётся', `${Math.round(posterBody.byteLength/1024)} КБ`)
			: fail('обложка', `статус ${poster.status}`);

		const noAuth = await fetch(`${BASE}/media/video/${VIDEO_ID}`);
		noAuth.status === 401
			? pass('медиа без подписи закрыто', '401')
			: fail('медиа без подписи', `статус ${noAuth.status}`);

		// ═══ 9. УВЕДОМЛЕНИЕ ═══
		say('\n═══ 9. УВЕДОМЛЕНИЕ В БОТ ═══');
		const ready = events.find((e) => e.type === 'ready');
		ready?.video?.share_token
			? pass('воркер отдал ссылку боту', `${config.publicUrl}/dl/${ready.video.share_token.slice(0, 8)}…`)
			: fail('уведомление', JSON.stringify(events.map((e) => e.type)));

		// ═══ 10. УБОРЩИК ═══
		say('\n═══ 10. СРОКИ ХРАНЕНИЯ ═══');
		done.keep_until
			? pass('срок хранения проставлен', new Date(done.keep_until).toLocaleDateString('ru-RU'))
			: fail('keep_until', 'пусто');

		await q("UPDATE videos SET updated_at = NOW() - interval '10 days' WHERE id = $1", [VIDEO_ID]);
		const swept = await sweepStorage();
		const afterSweep = await one('SELECT source_deleted_at, source_path FROM videos WHERE id = $1', [VIDEO_ID]);
		afterSweep.source_deleted_at
			? pass('исходник убран по сроку', `${swept.sources} шт.`)
			: fail('уборка исходника', 'не сработала');

		await fs.access(afterSweep.source_path).then(
			() => fail('файл исходника', 'остался на диске'),
			() => pass('файл исходника удалён с диска')
		);

		const redo = await call(`/api/videos/${VIDEO_ID}/rebuild`, {
			method: 'POST',
			headers: {'Content-Type': 'application/json'},
			body: JSON.stringify({marks: [{at: 5, note: 'тест'}]}),
		});
		redo.status === 410
			? pass('правка без исходника объяснена', redo.json.error.slice(0, 60))
			: fail('правка без исходника', `статус ${redo.status}`);

		await q("UPDATE videos SET keep_until = NOW() - interval '1 day' WHERE id = $1", [VIDEO_ID]);
		const swept2 = await sweepStorage();
		const expired = await one('SELECT status, share_token, output_deleted_at FROM videos WHERE id = $1', [VIDEO_ID]);
		expired.status === 'expired' && !expired.share_token
			? pass('просроченный ролик убран', `${swept2.outputs} шт., токен обнулён`)
			: fail('уборка ролика', JSON.stringify(expired));

		const deadLink = await fetch(`${BASE}/dl/${done.share_token}`);
		deadLink.status === 404
			? pass('старая ссылка перестала работать', '404')
			: fail('ссылка после сгорания', `статус ${deadLink.status}`);
	}
} catch (err) {
	fail('прогон оборвался', err.stack?.split('\n').slice(0, 3).join(' | ') ?? String(err));
}

say('\n' + '═'.repeat(60));
say(`ИТОГ: ${ok.length} прошло, ${bad.length} провалено`);
if (bad.length) { say('\nНЕ ПРОШЛО:'); bad.forEach((b) => say('  ✖ ' + b)); }
say('═'.repeat(60) + '\n');

stopWorker();
await app.close();
await pool.end();
process.exit(bad.length ? 1 : 0);

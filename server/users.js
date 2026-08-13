// Пользователи и кредиты.
//
// Единственное место, где меняется баланс, — addCredits и spendCredits.
// Обе пишут строку в ledger, поэтому «куда делись ролики» всегда
// имеет ответ.

import crypto from 'node:crypto';
import {q, one, many, tx} from './db.js';
import {config} from './config.js';

const newRefCode = () => crypto.randomBytes(4).toString('hex');

export const upsertUser = async (tgUser, startParam = null) => {
	const existing = await one('SELECT * FROM users WHERE tg_id = $1', [tgUser.id]);

	if (existing) {
		// is_admin пересчитываем каждый раз: список ADMIN_IDS может
		// поменяться уже после того, как человек завёлся в базе.
		await q(
			`UPDATE users SET username = $2, first_name = $3, last_name = $4,
			 photo_url = $5, is_admin = $6, seen_at = NOW() WHERE id = $1`,
			[
				existing.id,
				tgUser.username ?? null,
				tgUser.first_name ?? null,
				tgUser.last_name ?? null,
				tgUser.photo_url ?? null,
				config.admins.includes(Number(tgUser.id)),
			]
		);
		return await one('SELECT * FROM users WHERE id = $1', [existing.id]);
	}

	// Пришёл по реферальной ссылке: t.me/bot?start=r_<code>
	let referrer = null;
	if (startParam?.startsWith('r_')) {
		referrer = await one('SELECT id FROM users WHERE ref_code = $1', [
			startParam.slice(2),
		]);
	}

	return await one(
		`INSERT INTO users (tg_id, username, first_name, last_name, photo_url,
		                    ref_code, referred_by, is_admin)
		 VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING *`,
		[
			tgUser.id,
			tgUser.username ?? null,
			tgUser.first_name ?? null,
			tgUser.last_name ?? null,
			tgUser.photo_url ?? null,
			newRefCode(),
			referrer?.id ?? null,
			config.admins.includes(Number(tgUser.id)),
		]
	);
};

export const getUser = (id) => one('SELECT * FROM users WHERE id = $1', [id]);

// Пакет продлевает срок от большей из двух дат: если старый ещё не сгорел,
// новый добавляется к остатку, а не обнуляет его.
export const addCredits = async (userId, amount, reason, ref = null) =>
	tx(async (client) => {
		const {rows} = await client.query(
			`UPDATE users
			 SET credits = credits + $2,
			     expires_at = GREATEST(COALESCE(expires_at, NOW()), NOW())
			                  + ($3 || ' days')::interval
			 WHERE id = $1
			 RETURNING credits, expires_at`,
			[userId, amount, config.packageDays]
		);
		const row = rows[0];
		await client.query(
			'INSERT INTO ledger (user_id, delta, balance, reason, ref) VALUES ($1,$2,$3,$4,$5)',
			[userId, amount, row.credits, reason, ref]
		);
		return row;
	});

// Списание идёт под блокировкой строки: два параллельных запроса на рендер
// не смогут увести баланс в минус.
//
// Вариант с готовым клиентом нужен там, где списание и постановка задачи
// обязаны быть одной транзакцией: иначе при сбое вставки кредит уже списан,
// а ролика нет.
export const spendCreditsIn = async (client, userId, amount, reason, ref = null) => {
	const {rows} = await client.query(
		'SELECT credits, expires_at FROM users WHERE id = $1 FOR UPDATE',
		[userId]
	);
	const user = rows[0];
	if (!user) return {ok: false, reason: 'Пользователь не найден'};

	if (user.expires_at && new Date(user.expires_at) < new Date()) {
		return {ok: false, reason: 'Пакет сгорел — нужно докупить ролики'};
	}
	if (Number(user.credits) < amount) {
		return {ok: false, reason: 'Не хватает роликов в пакете'};
	}

	const {rows: after} = await client.query(
		'UPDATE users SET credits = credits - $2 WHERE id = $1 RETURNING credits',
		[userId, amount]
	);
	await client.query(
		'INSERT INTO ledger (user_id, delta, balance, reason, ref) VALUES ($1,$2,$3,$4,$5)',
		[userId, -amount, after[0].credits, reason, ref]
	);
	return {ok: true, credits: Number(after[0].credits)};
};

export const spendCredits = async (userId, amount, reason, ref = null) =>
	tx((client) => spendCreditsIn(client, userId, amount, reason, ref));

// Реферал получает бонус только когда приглашённый заплатил —
// иначе ссылку накрутят пустыми регистрациями.
export const rewardReferrer = async (userId) => {
	const user = await one(
		'SELECT referred_by, ref_rewarded FROM users WHERE id = $1',
		[userId]
	);
	if (!user?.referred_by || user.ref_rewarded) return null;

	await q('UPDATE users SET ref_rewarded = TRUE WHERE id = $1', [userId]);
	await addCredits(
		user.referred_by,
		config.referralBonus,
		'Бонус за приглашённого эксперта',
		String(userId)
	);
	return user.referred_by;
};

export const publicUser = (u) => ({
	id: Number(u.id),
	tgId: Number(u.tg_id),
	username: u.username,
	name: [u.first_name, u.last_name].filter(Boolean).join(' ') || 'Эксперт',
	photo: u.photo_url,
	credits: Number(u.credits),
	expiresAt: u.expires_at,
	expired: u.expires_at ? new Date(u.expires_at) < new Date() : false,
	refCode: u.ref_code,
	isAdmin: u.is_admin,
});

// ── админские выборки ─────────────────────────────────────────

// Находит человека по @username, числовому id телеграма или
// внутреннему id. Админ обычно знает только @ник.
export const findUser = async (needle) => {
	const raw = String(needle || '').trim().replace(/^@/, '');
	if (!raw) return null;

	if (/^\d+$/.test(raw)) {
		return (
			(await one('SELECT * FROM users WHERE tg_id = $1', [raw])) ??
			(await one('SELECT * FROM users WHERE id = $1', [raw]))
		);
	}
	return await one('SELECT * FROM users WHERE lower(username) = lower($1)', [raw]);
};

export const userCard = async (user) => {
	const stats = await one(
		`SELECT
		   COUNT(*)                                       AS total,
		   COUNT(*) FILTER (WHERE status = 'ready')       AS ready,
		   COUNT(*) FILTER (WHERE status IN ('queued','running')) AS active,
		   COUNT(*) FILTER (WHERE status = 'failed')      AS failed
		 FROM videos WHERE user_id = $1`,
		[user.id]
	);
	const paid = await one(
		`SELECT COALESCE(SUM(amount),0) AS sum, COUNT(*) AS cnt
		 FROM payments WHERE user_id = $1 AND status = 'paid'`,
		[user.id]
	);
	const moves = await many(
		'SELECT delta, reason, created_at FROM ledger WHERE user_id = $1 ORDER BY id DESC LIMIT 5',
		[user.id]
	);
	return {stats, paid, moves};
};

export const serviceStats = async () => {
	const users = await one(
		`SELECT COUNT(*) AS total,
		        COUNT(*) FILTER (WHERE credits > 0) AS paying,
		        COUNT(*) FILTER (WHERE created_at > NOW() - interval '7 days') AS fresh
		 FROM users`
	);
	const videos = await one(
		`SELECT COUNT(*) AS total,
		        COUNT(*) FILTER (WHERE status = 'ready') AS ready,
		        COUNT(*) FILTER (WHERE status IN ('queued','running')) AS active,
		        COUNT(*) FILTER (WHERE status = 'failed') AS failed,
		        COUNT(*) FILTER (WHERE created_at > NOW() - interval '24 hours') AS today
		 FROM videos`
	);
	const money = await one(
		`SELECT COALESCE(SUM(amount),0) AS total, COUNT(*) AS cnt,
		        COALESCE(SUM(amount) FILTER (WHERE paid_at > NOW() - interval '30 days'),0) AS month
		 FROM payments WHERE status = 'paid'`
	);
	return {users, videos, money};
};

// Сводка по пайплайну: сколько на самом деле занимает монтаж и сколько
// весит результат. До появления этих колонок цифры жили только в логах
// контейнера и терялись при каждом редеплое.
export const pipelineStats = () =>
	one(
		`SELECT
		   COUNT(*) FILTER (WHERE render_ms IS NOT NULL)      AS measured,
		   ROUND(AVG(duration_sec)::numeric)                  AS avg_duration,
		   ROUND(AVG(render_ms)::numeric / 1000)              AS avg_render_sec,
		   ROUND(AVG(speech_ms)::numeric / 1000, 1)           AS avg_speech_sec,
		   ROUND(AVG(source_bytes)::numeric / 1048576)        AS avg_source_mb,
		   ROUND(AVG(output_bytes)::numeric / 1048576)        AS avg_output_mb,
		   COALESCE(SUM(source_bytes) FILTER (WHERE source_deleted_at IS NULL), 0)
		     + COALESCE(SUM(output_bytes) FILTER (WHERE output_deleted_at IS NULL), 0)
		                                                      AS disk_bytes,
		   MODE() WITHIN GROUP (ORDER BY speech_provider)     AS speech_provider
		 FROM videos
		 WHERE created_at > NOW() - interval '30 days'`
	);

export const queuePeek = () =>
	many(
		`SELECT j.id, j.status, j.progress, j.stage, j.attempts,
		        v.title, v.user_id, u.username
		 FROM jobs j
		 JOIN videos v ON v.id = j.video_id
		 JOIN users u ON u.id = v.user_id
		 WHERE j.status IN ('queued','running')
		 ORDER BY j.id LIMIT 12`
	);

// Проверка подписи Telegram Mini App.
//
// Мини-апп присылает initData — строку с данными пользователя и подписью.
// Без проверки подписи любой может подставить чужой tg_id и списать
// чужие ролики, поэтому доверять этим данным без HMAC нельзя.
//
// Алгоритм из документации Telegram:
//   secret = HMAC_SHA256(ключ "WebAppData", bot_token)
//   hash   = HMAC_SHA256(secret, data_check_string)
// где data_check_string — пары "ключ=значение" кроме hash,
// отсортированные по ключу и склеенные через \n.

import crypto from 'node:crypto';
import {config} from './config.js';

const MAX_AGE_SEC = 24 * 60 * 60;

// Последние отказы — чтобы понять, почему настоящий Telegram не проходит.
// Сюда не попадает ни подпись, ни данные пользователя целиком: только то,
// что нужно для разбора — какие поля пришли и сошёлся ли счёт.
export const REJECTS = [];

const remember = (report) => {
	REJECTS.unshift({...report, at: new Date().toISOString()});
	REJECTS.length = Math.min(REJECTS.length, 12);
};

export const parseInitData = (initData) => {
	if (!initData || typeof initData !== 'string') {
		return {ok: false, reason: 'пустой initData'};
	}

	const params = new URLSearchParams(initData);
	const hash = params.get('hash');
	if (!hash) return {ok: false, reason: 'нет подписи'};

	params.delete('hash');
	// signature появляется в новых версиях и в подпись не входит
	params.delete('signature');

	const check = [...params.entries()]
		.map(([k, v]) => `${k}=${v}`)
		.sort()
		.join('\n');

	const secret = crypto
		.createHmac('sha256', 'WebAppData')
		.update(config.bot.token)
		.digest();

	const mine = crypto.createHmac('sha256', secret).update(check).digest('hex');

	// Сравнение постоянного времени: обычное === утекает информацию
	// о том, сколько символов совпало.
	const a = Buffer.from(mine, 'hex');
	const b = Buffer.from(hash, 'hex');
	if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) {
		remember({
			поля: [...params.keys()].sort(),
			ихПодпись: String(hash).slice(0, 10),
			нашаПодпись: mine.slice(0, 10),
			ботВКлюче: String(config.bot.token).split(':')[0],
			длинаКлюча: String(config.bot.token).length,
			строкаПроверки: check.length,
		});
		return {ok: false, reason: 'подпись не сходится'};
	}

	const authDate = Number(params.get('auth_date') || 0);
	if (!authDate || Date.now() / 1000 - authDate > MAX_AGE_SEC) {
		return {ok: false, reason: 'данные устарели, переоткрой приложение'};
	}

	let user;
	try {
		user = JSON.parse(params.get('user') || 'null');
	} catch {
		return {ok: false, reason: 'битые данные пользователя'};
	}
	if (!user?.id) return {ok: false, reason: 'нет пользователя'};

	return {ok: true, user, startParam: params.get('start_param') || null};
};

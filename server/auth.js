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

	// Telegram добавил поле signature — вторую подпись, для проверки
	// третьей стороной. Входит ли оно в счёт основной подписи, в разных
	// клиентах выходит по-разному, поэтому считаем оба порядка и
	// принимаем совпадение с любым.
	//
	// Безопасности это не ослабляет: обе строки подписаны секретом бота,
	// подделать любую из них без токена нельзя.
	const line = (entries) => entries.map(([k, v]) => `${k}=${v}`).sort().join('\n');

	const withSignature = line([...params.entries()]);
	const withoutSignature = line([...params.entries()].filter(([k]) => k !== 'signature'));

	const secret = crypto
		.createHmac('sha256', 'WebAppData')
		.update(config.bot.token)
		.digest();

	const sign = (text) => crypto.createHmac('sha256', secret).update(text).digest('hex');

	// Сравнение постоянного времени: обычное === утекает информацию
	// о том, сколько символов совпало.
	const same = (mine) => {
		const a = Buffer.from(mine, 'hex');
		const b = Buffer.from(hash, 'hex');
		return a.length === b.length && crypto.timingSafeEqual(a, b);
	};

	const matched = same(sign(withoutSignature))
		? 'без signature'
		: same(sign(withSignature))
			? 'с signature'
			: null;

	if (!matched) {
		let who = null;
		try { who = JSON.parse(params.get('user') || 'null')?.id ?? null; } catch {}

		remember({
			кто: who,
			поля: [...params.keys()].sort(),
			былаSignature: params.has('signature'),
			ихПодпись: String(hash).slice(0, 10),
			безSignature: sign(withoutSignature).slice(0, 10),
			сSignature: sign(withSignature).slice(0, 10),
			ботВКлюче: String(config.bot.token).split(':')[0],
			длинаКлюча: String(config.bot.token).length,
		});
		return {ok: false, reason: 'подпись не сходится'};
	}

	params.delete('signature');

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

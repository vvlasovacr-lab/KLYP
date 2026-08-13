// Оплата через Lava.top.
//
// ⚠️ ВАЖНО про этот файл.
// Точная форма запроса на создание счёта и формат вебхука зависят от версии
// API кассы и от того, как заведены товары в твоём кабинете. Я не могу
// это угадать, поэтому всё, что специфично для Lava, собрано в двух
// функциях ниже — createInvoice и readWebhook. Сверь их с актуальной
// документацией в личном кабинете и поправь только их: остальной код
// (начисление кредитов, идемпотентность, уведомления) от формата не зависит.
//
// Что точно нужно сделать перед запуском:
//   1. Завести три товара в кабинете Lava — по одному на пакет.
//   2. Скопировать их offerId в LAVA_OFFER_START / _PRO / _STUDIO.
//   3. Указать адрес вебхука: {PUBLIC_URL}/webhook/lava
//   4. Положить ключ в LAVA_API_KEY, секрет вебхука — в LAVA_WEBHOOK_SECRET.

import crypto from 'node:crypto';
import {config, hasLava} from './config.js';
import {q, one} from './db.js';
import {findPackage} from './packages.js';

// ── создание счёта ────────────────────────────────────────────
// Правь тело запроса под свою версию API. Функция обязана вернуть
// { invoiceId, payUrl } — этого достаточно остальному коду.
const callLavaInvoice = async ({pkg, user, orderId}) => {
	const offerId = config.lava.offers[pkg.code];
	if (!offerId) {
		throw new Error(
			`Для пакета «${pkg.title}» не задан offerId. Заполни LAVA_OFFER_${pkg.code.toUpperCase()}`
		);
	}

	const res = await fetch(config.lava.invoiceUrl, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			'X-Api-Key': config.lava.apiKey,
		},
		body: JSON.stringify({
			offerId,
			currency: pkg.currency ?? 'RUB',
			// Почта нужна кассе для чека. Телеграм её не отдаёт,
			// поэтому подставляем технический адрес с id пользователя.
			email: `tg${user.tg_id}@reels.studio`,
			// Это поле вернётся в вебхуке и свяжет оплату с заказом.
			clientUtm: {orderId},
			buyerLanguage: 'RU',
		}),
	});

	const text = await res.text();
	if (!res.ok) {
		throw new Error(`Lava ответила ${res.status}: ${text.slice(0, 400)}`);
	}

	let data;
	try {
		data = JSON.parse(text);
	} catch {
		throw new Error(`Lava вернула не JSON: ${text.slice(0, 200)}`);
	}

	const payUrl = data.paymentUrl || data.url || data.data?.url;
	const invoiceId = data.id || data.invoiceId || data.data?.id || orderId;

	if (!payUrl) {
		throw new Error(
			`В ответе Lava нет ссылки на оплату. Пришло: ${JSON.stringify(data).slice(0, 300)}`
		);
	}
	return {invoiceId: String(invoiceId), payUrl};
};

// ── разбор вебхука ────────────────────────────────────────────
// Тоже правится под формат кассы. Должна вернуть:
//   { orderId, invoiceId, paid: boolean }
const readWebhook = (body) => {
	const orderId =
		body?.clientUtm?.orderId ?? body?.custom?.orderId ?? body?.orderId ?? null;
	const invoiceId = body?.id ?? body?.invoiceId ?? body?.contractId ?? null;
	const status = String(body?.status ?? body?.eventType ?? '').toLowerCase();
	const paid =
		status.includes('success') ||
		status.includes('paid') ||
		status.includes('completed') ||
		status === 'subscription.recurring.payment.success';

	return {orderId, invoiceId: invoiceId ? String(invoiceId) : null, paid};
};

// Подпись вебхука. Если касса её не шлёт — держи секрет в URL
// и проверяй его, но не оставляй эндпоинт полностью открытым:
// иначе любой сможет начислить себе ролики POST-запросом.
export const verifyWebhook = (rawBody, signature) => {
	if (!config.lava.webhookSecret) return true; // проверка выключена
	if (!signature) return false;

	const mine = crypto
		.createHmac('sha256', config.lava.webhookSecret)
		.update(rawBody)
		.digest('hex');

	const a = Buffer.from(mine);
	const b = Buffer.from(String(signature));
	return a.length === b.length && crypto.timingSafeEqual(a, b);
};

// ── публичное API модуля ──────────────────────────────────────

export const startPayment = async (user, packageCode) => {
	const pkg = findPackage(packageCode);
	if (!pkg) throw new Error('Неизвестный пакет');

	const payment = await one(
		`INSERT INTO payments (user_id, package_code, credits, amount, status)
		 VALUES ($1,$2,$3,$4,'pending') RETURNING *`,
		[user.id, pkg.code, pkg.credits, pkg.amount]
	);

	const orderId = `rs-${payment.id}`;

	// Без ключа кассы возвращаем ссылку-заглушку: интерфейс собирается
	// и тестируется, оплата просто не проходит.
	if (!hasLava()) {
		const payUrl = `${config.publicUrl}/pay/mock/${payment.id}`;
		await q('UPDATE payments SET invoice_id = $2, pay_url = $3 WHERE id = $1', [
			payment.id,
			orderId,
			payUrl,
		]);
		return {payUrl, mock: true, paymentId: Number(payment.id)};
	}

	const {invoiceId, payUrl} = await callLavaInvoice({pkg, user, orderId});
	await q('UPDATE payments SET invoice_id = $2, pay_url = $3 WHERE id = $1', [
		payment.id,
		invoiceId,
		payUrl,
	]);
	return {payUrl, mock: false, paymentId: Number(payment.id)};
};

// Возвращает оплаченный payment либо null, если это повтор или не оплата.
// Идемпотентность держится на статусе: касса может прислать вебхук дважды.
export const applyWebhook = async (body) => {
	const {orderId, invoiceId, paid} = readWebhook(body);
	if (!paid) return null;

	const id = orderId?.startsWith('rs-') ? Number(orderId.slice(3)) : null;
	const payment = id
		? await one('SELECT * FROM payments WHERE id = $1', [id])
		: await one('SELECT * FROM payments WHERE invoice_id = $1', [invoiceId]);

	if (!payment) throw new Error(`Платёж не найден: ${orderId ?? invoiceId}`);
	if (payment.status === 'paid') return null; // повторный вебхук

	await q(
		`UPDATE payments SET status = 'paid', paid_at = NOW(), raw = $2, invoice_id = COALESCE(invoice_id, $3)
		 WHERE id = $1`,
		[payment.id, JSON.stringify(body), invoiceId]
	);
	return payment;
};

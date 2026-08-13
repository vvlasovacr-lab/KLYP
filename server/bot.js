// Бот. Держит вход в мини-апп и уведомления.
//
// Файлы через бота не ходят ни в одну сторону: Bot API не даёт скачать
// вложение больше 20 МБ и отправить больше 50 МБ, а рилс весит больше.
// Загрузка идёт через мини-апп напрямую на сервер, выдача — ссылкой.

import {Bot, InlineKeyboard} from 'grammy';
import {config} from './config.js';
import {one} from './db.js';
import {
	upsertUser, publicUser, addCredits, spendCredits,
	findUser, userCard, serviceStats, pipelineStats, queuePeek,
} from './users.js';

export const buildBot = () => {
	const bot = new Bot(config.bot.token);

	const openApp = () =>
		new InlineKeyboard().webApp('Открыть студию', `${config.publicUrl}/app/`);

	bot.command('start', async (ctx) => {
		const payload = ctx.match?.trim() || null;
		const user = await upsertUser(ctx.from, payload);
		const me = publicUser(user);

		const greeting = me.credits > 0
			? `На счету ${me.credits} ${plural(me.credits, 'ролик', 'ролика', 'роликов')}.`
			: 'Пакет пока не куплен — выбери подходящий внутри студии.';

		await ctx.reply(
			`Привет, ${me.name}.\n\n` +
			`Загружаешь сырое видео — забираешь готовый рилс с титрами, врезками и звуком.\n\n` +
			`${greeting}`,
			{reply_markup: openApp()}
		);
	});

	bot.command('balance', async (ctx) => {
		const user = await upsertUser(ctx.from);
		const me = publicUser(user);
		const until = me.expiresAt
			? new Date(me.expiresAt).toLocaleDateString('ru-RU', {day: 'numeric', month: 'long'})
			: '—';

		await ctx.reply(
			`Роликов в пакете: ${me.credits}\n` +
			`Пакет действует до: ${until}${me.expired ? ' (сгорел)' : ''}`,
			{reply_markup: openApp()}
		);
	});

	bot.command('help', async (ctx) => {
		await ctx.reply(
			'Как это работает:\n\n' +
			'1. Открываешь студию кнопкой ниже\n' +
			'2. Загружаешь видео, выбираешь шаблон, пишешь пожелания\n' +
			'3. Через несколько минут готовый ролик придёт сюда\n\n' +
			'Не нравится момент — ставишь метку на таймлайне и пересобираешь.\n\n' +
			'/balance — сколько роликов осталось',
			{reply_markup: openApp()}
		);
	});

	// ── админские команды ──────────────────────────────────────
	// Доступ по списку ADMIN_IDS. Отвечаем молчанием, а не отказом:
	// чужой не должен узнать, что такая команда вообще существует.
	const admin = (handler) => async (ctx) => {
		if (!config.admins.includes(Number(ctx.from.id))) return;
		try {
			await handler(ctx);
		} catch (err) {
			await ctx.reply(`Ошибка: ${err.message}`);
		}
	};

	bot.command('admin', admin(async (ctx) => {
		await ctx.reply(
			'Команды администратора\n\n' +
			'/give @ник 30 — начислить ролики\n' +
			'/take @ник 10 — списать ролики\n' +
			'/who @ник — карточка клиента\n' +
			'/stats — сводка по сервису\n' +
			'/queue — что сейчас в очереди\n\n' +
			'Вместо @ника можно указать номер телеграма.'
		);
	}));

	bot.command('give', admin(async (ctx) => {
		const [who, amount] = (ctx.match || '').trim().split(/\s+/);
		const count = Number(amount);

		if (!who || !Number.isFinite(count) || count <= 0) {
			return ctx.reply('Формат: /give @ник 30');
		}

		const user = await findUser(who);
		if (!user) return ctx.reply(`Не нашёл клиента: ${who}`);

		const after = await addCredits(
			user.id, count, `Начислено вручную (@${ctx.from.username || ctx.from.id})`
		);

		await ctx.reply(
			`Начислил ${count} ${plural(count, 'ролик', 'ролика', 'роликов')} — ${nameOf(user)}\n` +
			`Стало: ${Number(after.credits)} · пакет до ${fmtDate(after.expires_at)}`
		);

		// Клиент должен узнать о подарке сам, а не обнаружить случайно.
		await bot.api.sendMessage(
			Number(user.tg_id),
			`Тебе начислено ${count} ${plural(count, 'ролик', 'ролика', 'роликов')}.\n` +
			`Всего на счету: ${Number(after.credits)}.`,
			{reply_markup: openApp()}
		).catch(() => {});
	}));

	bot.command('take', admin(async (ctx) => {
		const [who, amount] = (ctx.match || '').trim().split(/\s+/);
		const count = Number(amount);

		if (!who || !Number.isFinite(count) || count <= 0) {
			return ctx.reply('Формат: /take @ник 10');
		}

		const user = await findUser(who);
		if (!user) return ctx.reply(`Не нашёл клиента: ${who}`);

		const out = await spendCredits(
			user.id, count, `Списано вручную (@${ctx.from.username || ctx.from.id})`
		);
		if (!out.ok) return ctx.reply(`Не вышло: ${out.reason}`);

		await ctx.reply(`Списал ${count} у ${nameOf(user)}. Осталось: ${out.credits}`);
	}));

	bot.command('who', admin(async (ctx) => {
		const who = (ctx.match || '').trim();
		if (!who) return ctx.reply('Формат: /who @ник');

		const user = await findUser(who);
		if (!user) return ctx.reply(`Не нашёл клиента: ${who}`);

		const {stats, paid, moves} = await userCard(user);
		const expired = user.expires_at && new Date(user.expires_at) < new Date();

		const history = moves.length
			? moves.map((m) => {
					const sign = Number(m.delta) > 0 ? '+' : '';
					return `  ${sign}${Number(m.delta)} — ${m.reason}`;
				}).join('\n')
			: '  движений не было';

		await ctx.reply(
			`${nameOf(user)}\n` +
			`id ${user.tg_id} · в базе с ${fmtDate(user.created_at)}\n\n` +
			`Роликов на счету: ${Number(user.credits)}\n` +
			`Пакет до: ${fmtDate(user.expires_at)}${expired ? ' (сгорел)' : ''}\n\n` +
			`Смонтировано: ${stats.ready} из ${stats.total}\n` +
			`В работе: ${stats.active} · с ошибкой: ${stats.failed}\n\n` +
			`Оплат: ${paid.cnt} на ${Number(paid.sum).toLocaleString('ru-RU')} ₽\n\n` +
			`Последние движения:\n${history}`
		);
	}));

	bot.command('stats', admin(async (ctx) => {
		const {users, videos, money} = await serviceStats();
		const p = await pipelineStats();

		// Пока ни один ролик не смонтирован, средних нет — и врать
		// цифрами не надо: так и пишем.
		const pipeline = Number(p?.measured)
			? `Замеров за 30 дней: ${p.measured}\n` +
				`Ролик в среднем: ${p.avg_duration ?? '—'} с\n` +
				`Рендер: ${p.avg_render_sec ?? '—'} с · речь: ${p.avg_speech_sec ?? '—'} с (${p.speech_provider ?? '—'})\n` +
				`Вход: ${p.avg_source_mb ?? '—'} МБ · выход: ${p.avg_output_mb ?? '—'} МБ\n` +
				`Занято на диске: ${(Number(p.disk_bytes) / 1073741824).toFixed(1)} ГБ`
			: 'Замеров пока нет — ни один ролик не смонтирован.';

		await ctx.reply(
			`Сводка по сервису\n\n` +
			`Клиенты: ${users.total} · с пакетом: ${users.paying}\n` +
			`Новых за неделю: ${users.fresh}\n\n` +
			`Роликов всего: ${videos.total}\n` +
			`Готово: ${videos.ready} · в работе: ${videos.active} · упало: ${videos.failed}\n` +
			`За сутки: ${videos.today}\n\n` +
			`Оплат: ${money.cnt} на ${Number(money.total).toLocaleString('ru-RU')} ₽\n` +
			`За 30 дней: ${Number(money.month).toLocaleString('ru-RU')} ₽\n\n` +
			`Пайплайн\n${pipeline}`
		);
	}));

	bot.command('queue', admin(async (ctx) => {
		const jobs = await queuePeek();
		if (!jobs.length) return ctx.reply('Очередь пуста.');

		const lines = jobs.map((j) => {
			const mark = j.status === 'running' ? '▶' : '·';
			const pct = j.status === 'running' ? ` ${j.progress}% ${j.stage ?? ''}` : '';
			const retry = j.attempts > 1 ? ` (попытка ${j.attempts})` : '';
			return `${mark} ${j.title} — @${j.username ?? j.user_id}${pct}${retry}`;
		});
		await ctx.reply(`В очереди ${jobs.length}:\n\n${lines.join('\n')}`);
	}));

	bot.on('message:video', async (ctx) => {
		await ctx.reply(
			'Видео принимаю только через студию — так файл не упирается в лимит Telegram и не теряет качество.',
			{reply_markup: openApp()}
		);
	});

	bot.catch((err) => {
		console.error('ошибка бота:', err.message);
	});

	// Уведомления от воркера и кассы
	const notify = async (userId, event) => {
		const user = await one('SELECT tg_id FROM users WHERE id = $1', [userId]);
		if (!user) return;
		const chat = Number(user.tg_id);

		try {
			if (event.type === 'ready') {
				const video = event.video;

				// Файл не отправляем: Bot API не пропускает больше 50 МБ,
				// а минутный рилс весит больше. Отдаём ссылкой — она тянет
				// файл любого размера и работает с перемоткой.
				const keyboard = new InlineKeyboard()
					.webApp('Открыть студию', `${config.publicUrl}/app/`);
				if (video.share_token) {
					keyboard.row().url('Скачать ролик', `${config.publicUrl}/dl/${video.share_token}`);
				}

				const weight = video.output_bytes
					? ` · ${(Number(video.output_bytes) / 1048576).toFixed(0)} МБ`
					: '';
				const keep = video.keep_until
					? `\nСсылка работает до ${fmtDate(video.keep_until)} — успей скачать.`
					: '';

				await bot.api.sendMessage(
					chat,
					`Готово: «${video.title}»${video.preview_only ? ' (черновик)' : ''}${weight}${keep}`,
					{reply_markup: keyboard}
				);
			}

			if (event.type === 'failed') {
				await bot.api.sendMessage(
					chat,
					`Не получилось смонтировать «${event.video.title}».\n` +
					`Ролик вернул в пакет — попробуй ещё раз.\n\n` +
					`Причина: ${event.message.slice(0, 200)}`,
					{reply_markup: openApp()}
				);
			}

			if (event.type === 'paid') {
				await bot.api.sendMessage(
					chat,
					`Оплата прошла. Начислено роликов: ${event.payment.credits}.`,
					{reply_markup: openApp()}
				);
			}
		} catch (err) {
			console.error('не смог отправить уведомление:', err.message);
		}
	};

	return {bot, notify};
};

const plural = (n, one, few, many) => {
	const a = Math.abs(n) % 100;
	const b = a % 10;
	if (a > 10 && a < 20) return many;
	if (b > 1 && b < 5) return few;
	if (b === 1) return one;
	return many;
};

const nameOf = (u) => {
	const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || 'Без имени';
	return u.username ? `${name} (@${u.username})` : name;
};

const fmtDate = (d) => {
	if (!d) return '—';
	const date = new Date(d);
	if (isNaN(date)) return '—';
	return date.toLocaleDateString('ru-RU', {day: 'numeric', month: 'long'});
};

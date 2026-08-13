// Точка входа. Поднимает базу, бота, API и воркер в одном процессе.
//
// Воркер живёт здесь же, пока нагрузки мало: рендер и веб делят машину.
// Когда очередь начнёт копиться, вынеси его отдельным сервисом на Railway
// с теми же переменными и WEB_ENABLED=0 — код уже к этому готов.

import fs from 'node:fs/promises';
import {config} from './config.js';
import {migrate, pool} from './db.js';
import {buildBot} from './bot.js';
import {buildApi} from './api.js';
import {startWorker, setNotifier, requeueStale, startSweeper} from './worker.js';

const WEB = process.env.WEB_ENABLED !== '0';
const WORKER = process.env.WORKER_ENABLED !== '0';

const main = async () => {
	console.log('\nReels Studio\n');

	await fs.mkdir(config.storage.root, {recursive: true});
	console.log(`  хранилище: ${config.storage.root}`);

	console.log('  применяю миграции…');
	await migrate();

	const {bot, notify} = buildBot();
	setNotifier(notify);

	if (WORKER) {
		await requeueStale();
		startWorker();
		// Уборщик живёт рядом с воркером: он ходит по тем же файлам,
		// и на вебе без диска ему делать нечего.
		startSweeper();
	}

	if (WEB) {
		const app = await buildApi({notify});
		await app.listen({port: config.port, host: '0.0.0.0'});
		console.log(`  сервер: ${config.publicUrl}`);
		console.log(`  мини-апп: ${config.publicUrl}/app/`);
		console.log(`  вебхук кассы: ${config.publicUrl}/webhook/lava`);
	}

	// Вебхук для бота нужен там, где несколько инстансов: long polling
	// в двух копиях приводит к конфликту 409.
	if (config.bot.useWebhook) {
		const url = `${config.publicUrl}/webhook/telegram`;
		await bot.api.setWebhook(url, {secret_token: config.bot.secret});
		console.log(`  бот на вебхуке: ${url}`);
	} else {
		await bot.api.deleteWebhook().catch(() => {});
		bot.start({onStart: (me) => console.log(`  бот @${me.username} на long polling`)});
	}

	const me = await bot.api.getMe();
	if (!process.env.BOT_USERNAME) process.env.BOT_USERNAME = me.username;

	console.log('\nготов к работе\n');

	const bye = async (signal) => {
		console.log(`\n${signal}: останавливаюсь…`);
		await bot.stop().catch(() => {});
		await pool.end().catch(() => {});
		process.exit(0);
	};
	process.on('SIGTERM', () => bye('SIGTERM'));
	process.on('SIGINT', () => bye('SIGINT'));
};

main().catch((err) => {
	console.error('\n✖ не удалось запуститься:', err);
	process.exit(1);
});

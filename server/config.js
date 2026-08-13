// Всё, что приходит из окружения, читается здесь и больше нигде.
// Если переменной нет — падаем на старте с внятным текстом, а не через
// час в вебхуке оплаты.

import path from 'node:path';

const need = (key) => {
	const v = process.env[key];
	if (!v) {
		console.error(`\n✖ Не задана переменная ${key}. Смотри .env.example\n`);
		process.exit(1);
	}
	return v;
};

const opt = (key, fallback) => process.env[key] ?? fallback;

// Пустая строка в переменной — это «не задано», а не «задано пустым».
// Railway сохраняет такие переменные, и без этой проверки пресет
// провайдера затирался бы пустотой.
const set = (key) => {
	const v = process.env[key];
	return v !== undefined && String(v).trim() !== '' ? String(v).trim() : null;
};

// ── провайдеры распознавания речи ─────────────────────────────
// Все три говорят на одном протоколе (multipart + verbose_json),
// поэтому смена провайдера — это смена трёх строк, а не кода.
// Свой сервис подключается через provider=custom и SPEECH_URL.
export const SPEECH_PRESETS = {
	openai: {
		title: 'OpenAI Whisper',
		url: 'https://api.openai.com/v1/audio/transcriptions',
		model: 'whisper-1',
		maxAudioMb: 24,
		wordTimestamps: true,
	},
	groq: {
		title: 'Groq',
		url: 'https://api.groq.com/openai/v1/audio/transcriptions',
		model: 'whisper-large-v3-turbo',
		maxAudioMb: 24,
		wordTimestamps: true,
	},
	custom: {
		title: 'Свой сервис',
		url: '',
		model: 'whisper-1',
		maxAudioMb: 24,
		wordTimestamps: true,
	},
};

const speechConfig = () => {
	const apiKey = set('SPEECH_API_KEY') ?? '';
	const asked = (set('SPEECH_PROVIDER') ?? 'auto').toLowerCase();

	// auto: есть ключ — работаем через OpenAI, нет — уходим на паузы.
	const name = asked === 'auto' ? (apiKey ? 'openai' : 'silence') : asked;
	const preset = SPEECH_PRESETS[name] ?? SPEECH_PRESETS.custom;

	return {
		provider: name,
		title: name === 'silence' ? 'Границы по паузам' : preset.title,
		apiKey,
		// Точечные переменные перебивают пресет: так подключается
		// совместимый сервис, которого нет в списке.
		url: set('SPEECH_URL') ?? preset.url,
		model: set('SPEECH_MODEL') ?? preset.model,
		language: set('SPEECH_LANG') ?? 'ru',
		// Лимит на размер запроса у распознавания. Дорожка сжимается
		// в моно-mp3, так что час записи укладывается примерно в 28 МБ.
		maxAudioMb: Number(set('SPEECH_MAX_AUDIO_MB') ?? preset.maxAudioMb),
		// Не каждый сервис умеет тайминги по словам. Без них подсветка
		// работать не будет, но реплики хотя бы получат текст.
		wordTimestamps: (set('SPEECH_WORD_TIMESTAMPS') ?? '1') !== '0',
	};
};

export const config = {
	port: Number(opt('PORT', 3000)),
	// Публичный адрес сервиса: на него Telegram открывает мини-апп,
	// а касса шлёт вебхук. На Railway подставляется автоматически.
	publicUrl: (
		opt('PUBLIC_URL') ||
		(process.env.RAILWAY_PUBLIC_DOMAIN
			? `https://${process.env.RAILWAY_PUBLIC_DOMAIN}`
			: `http://localhost:${opt('PORT', 3000)}`)
	).replace(/\/$/, ''),

	databaseUrl: need('DATABASE_URL'),

	bot: {
		token: need('BOT_TOKEN'),
		// Секрет для вебхука Telegram: если его не проверять, кто угодно
		// сможет слать боту поддельные апдейты.
		secret: opt('BOT_WEBHOOK_SECRET', 'reels-hook-secret'),
		useWebhook: opt('BOT_MODE', 'polling') === 'webhook',
	},

	admins: String(opt('ADMIN_IDS', ''))
		.split(',')
		.map((s) => s.trim())
		.filter(Boolean)
		.map(Number),

	lava: {
		apiKey: opt('LAVA_API_KEY', ''),
		// Полный URL создания счёта. Вынесен в переменную намеренно:
		// у касс меняются версии эндпоинтов, и это не повод править код.
		invoiceUrl: opt('LAVA_INVOICE_URL', 'https://gate.lava.top/api/v2/invoice'),
		webhookSecret: opt('LAVA_WEBHOOK_SECRET', ''),
		// Соответствие «код пакета → offerId в кассе». Заполняется после
		// того, как товары заведены в личном кабинете Lava.
		offers: {
			start: opt('LAVA_OFFER_START', ''),
			pro: opt('LAVA_OFFER_PRO', ''),
			studio: opt('LAVA_OFFER_STUDIO', ''),
		},
	},

	storage: {
		// Railway Volume монтируется сюда. Локально — папка в проекте.
		root: path.resolve(opt('STORAGE_DIR', './storage')),
		maxUploadMb: Number(opt('MAX_UPLOAD_MB', 2048)),
		// Потолок длительности исходника. Рилс — короткий формат, а время
		// рендера растёт линейно: получасовая лекция заняла бы весь воркер
		// на час и съела бы кредит за один ролик.
		maxDurationSec: Number(opt('MAX_DURATION_SEC', 180)),

		// Исходник нужен только для пересборки с правками. Держим его
		// ровно столько, сколько живёт окно правок, и сносим.
		// 0 — удалять сразу после успешного монтажа.
		sourceKeepDays: Number(opt('SOURCE_KEEP_DAYS', 2)),
		// Готовый ролик клиент забирает в первые дни. Хранить его вечно
		// дороже, чем сам рендер: том оплачивается каждый месяц.
		outputKeepDays: Number(opt('OUTPUT_KEEP_DAYS', 30)),
		// Как часто уборщик проходит по диску.
		sweepMinutes: Number(opt('STORAGE_SWEEP_MIN', 60)),
	},

	render: {
		// Сколько роликов рендерим одновременно. Больше одного на слабой
		// машине только замедлит — рендер и так съедает все ядра.
		concurrency: Number(opt('RENDER_CONCURRENCY', 1)),
		// Черновик: дешевле и быстрее, списывает долю кредита.
		previewCost: Number(opt('PREVIEW_COST', 0.3)),
		previewScale: Number(opt('PREVIEW_SCALE', 0.45)),
		timeoutMin: Number(opt('RENDER_TIMEOUT_MIN', 30)),
		// Сколько ждать один кадр. У Remotion по умолчанию тридцать секунд —
		// на слабой машине кадр с видео и шрифтами в них не укладывается.
		frameTimeoutMs: Number(opt('RENDER_FRAME_TIMEOUT_MS', 180000)),
		// Сколько вкладок браузера рендерят одновременно. По умолчанию одна:
		// параллельные вкладки читают один и тот же видеофайл, и на сервере
		// это надёжно вешало рендер на первом же кадре второго диапазона.
		concurrencyPerRender: Number(opt('RENDER_CONCURRENCY_PER_JOB', 1)),
		// Отрисовка кадра на процессоре вместо видеокарты. На сервере
		// без карты — единственный рабочий вариант, на маке — лишнее
		// замедление, поэтому включается только в проде.
		softwareGl: (opt('RENDER_SOFTWARE_GL', '') || (process.env.NODE_ENV === 'production' ? '1' : '0')) !== '0',
	},

	packageDays: Number(opt('PACKAGE_DAYS', 90)),
	referralBonus: Number(opt('REFERRAL_BONUS', 10)),

	// Распознавание речи. Без ключа субтитры выйдут пустыми:
	// границы реплик найдутся по паузам, а текста взять неоткуда.
	speech: speechConfig(),

	// Модель подключается позже: пока разметку собирает шаблон.
	// Появится ключ — плановщик сам переключится, менять код не нужно.
	anthropic: {
		apiKey: opt('ANTHROPIC_API_KEY', ''),
		model: opt('ANTHROPIC_MODEL', 'claude-opus-5'),
	},

	isProd: process.env.NODE_ENV === 'production',
};

export const hasLava = () => Boolean(config.lava.apiKey);

// Распознавание включено, только если провайдер выбран, ключ задан
// и известен адрес. Иначе молча уходим на границы по паузам.
export const hasSpeech = () =>
	config.speech.provider !== 'silence' &&
	Boolean(config.speech.apiKey) &&
	Boolean(config.speech.url);

export const hasModel = () => Boolean(config.anthropic.apiKey);

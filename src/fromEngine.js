// ПЕРЕВОД ПЛАНА ДВИЖКА В НАШ ФОРМАТ.
//
// Движок решает, что показывать: где смысловая фраза, какое слово важное,
// где призыв, куда ставить текст, чтобы не попасть на лицо и в слепые зоны.
// Наши компоненты решают, как это выглядит: крупные плашки, бейджи, золото,
// рывок и расфокус на склейке.
//
// Здесь первое переводится во второе. Всё, что движок посчитал, берётся
// как есть; всё, чего он не считает (ритм склеек, вид плашки), достраивается
// по нашим правилам.

import {pickLook, fingerprint, PALETTES, LAYOUTS, FONTS} from './looks.js';
import {checkSafeArea} from './safety.js';
import {toManner, PACE} from './manner.js';

// ── что считать акцентом ──────────────────────────────────────
// Движок помечает важные слова ролью emphasis и даёт им категорию:
// число, деньги, проблема, конфликт, эмоция. Категория определяет цвет —
// на числах и деньгах золото, на проблеме и конфликте красный.
const HOT = new Set(['emphasis', 'accent', 'hero', 'punch']);

const DANGER = new Set(['problem', 'conflict', 'risk', 'negative']);

const isHot = (word) => HOT.has(String(word.role ?? '').toLowerCase());

// ── реплики ───────────────────────────────────────────────────
// Сцена движка уже разбита по смыслу и проверена на слепые зоны,
// поэтому своей пересборкой строк её трогать не нужно.
const toChunks = (scenes) =>
	scenes
		.map((scene) => ({
			start: Number(scene.start),
			end: Number(scene.end),
			type: scene.type,
			position: scene.layout?.position ?? 'lower',
			words: (scene.words ?? [])
				.map((word) => ({
					text: String(word.word ?? word.text ?? ''),
					start: Number(word.start),
					end: Number(word.end),
					hot: isHot(word),
					danger: DANGER.has(String(word.category ?? '').toLowerCase()),
				}))
				.filter((word) => word.text && Number.isFinite(word.start)),
		}))
		.filter((chunk) => chunk.words.length);

// ── акценты ───────────────────────────────────────────────────
// Движок помечает только те слова, в которых уверен, — на ровной речи
// их выходит вдвое меньше, чем нужно для ритма. Недостачу добираем сами:
// ищем лучшего кандидата в каждом окне, а не опускаем порог. Порог на
// ровной речи не спасает — там у всех слов одинаково низкий вес.

// Служебные слова крупным планом выглядят как ошибка вёрстки.
const STOP = new Set(
	`и а но да или же бы ли не ни в во на за под над при про с со к ко у о об обо из от до для без через между
	 что чтобы как когда если то это этот эта эти тот та те так вот уже ещё там тут
	 я ты он она оно мы вы они мне тебе ему ей нам вам им меня тебя его её нас вас их
	 кто кого кому свой своя мой твой наш ваш был была было были есть быть
	 очень просто только даже тоже`.split(/\s+/)
);

const bare = (s) => String(s).toLowerCase().replace(/[^\p{L}\p{N}%]/gu, '');
const letters = (s) => String(s).replace(/[^\p{L}\p{N}]/gu, '').length;

// Насколько слово тянет на смысловое.
const weigh = (word, previous) => {
	const clean = bare(word.text);
	if (!clean || STOP.has(clean)) return 0;

	let score = 0;
	// Цифра почти всегда и есть суть: «80%», «145 тысяч»
	if (/[0-9%]/.test(word.text)) score += 60;

	const long = letters(word.text);
	if (long >= 11) score += 34;
	else if (long >= 8) score += 22;
	else if (long >= 6) score += 12;
	else if (long <= 3) score -= 14;

	// Пауза перед словом — человек сам его выделил голосом
	if (previous) {
		const pause = word.start - previous.end;
		if (pause > 0.45) score += 30;
		else if (pause > 0.25) score += 16;
	}

	if (/[!?]/.test(word.text)) score += 24;
	if (/^(никогда|всегда|никто|нельзя|обязательно|главн|важн|запомн)/.test(clean)) score += 26;

	return score;
};

const toAccents = (chunks, {gap = 3.4, duration = 0} = {}) => {
	const flat = chunks.flatMap((chunk) => chunk.words);
	const taken = [];

	const put = (word, tone) => {
		taken.push({
			start: Number(word.start.toFixed(2)),
			end: Number(Math.max(word.end, word.start + 0.15).toFixed(2)),
			text: word.text,
			tone,
		});
	};

	// Сначала всё, что отметил движок: он смотрит на смысл фразы целиком,
	// а не на отдельное слово, и ошибается реже.
	for (const word of flat) {
		if (word.hot) put(word, word.danger ? 'danger' : 'gold');
	}

	// Потом добор до нужного ритма.
	const target = Math.max(taken.length, Math.floor(duration / gap));
	const free = (time) => taken.every((t) => Math.abs(t.start - time) >= gap);

	const ranked = flat
		.map((word, i) => ({word, score: weigh(word, flat[i - 1])}))
		.filter((x) => x.score >= 18 && !x.word.hot)
		.sort((a, b) => b.score - a.score);

	for (const {word} of ranked) {
		if (taken.length >= target) break;
		if (!free(word.start)) continue;
		put(word, word.danger ? 'danger' : 'gold');
	}

	return taken
		.sort((a, b) => a.start - b.start)
		.map((t) => [t.start, t.end, t.text, t.tone]);
};

// Модель называет слово и секунду, но её секунда — приблизительная:
// она читает расшифровку, а не звук. Привязываемся к настоящему слову,
// иначе подсветка встанет мимо того, что произносится.
const snap = (flat, {at, text}) => {
	const wanted = bare(text);
	let best = null;
	let bestGap = Infinity;

	for (const word of flat) {
		const gap = Math.abs(word.start - at);
		if (gap > 2.5) continue;
		// совпадение по тексту важнее близости по времени: одно и то же
		// слово может встретиться в ролике дважды
		const same = bare(word.text) === wanted || bare(word.text).startsWith(wanted);
		const score = gap - (same ? 3 : 0);
		if (score < bestGap) {
			bestGap = score;
			best = word;
		}
	}
	return best;
};

// Правка расшифровки. Машина слышит звук, но не знает, о чём разговор:
// «ООшка» превращается в «уошку», «НДС» — в «эндээс». Модель видит смысл
// и возвращает такие слова; здесь замена применяется к самим репликам,
// чтобы она попала и в субтитры, и в подсветку.
const applyFixes = (chunks, fixes) => {
	if (!fixes?.length) return chunks;

	let done = 0;

	for (const chunk of chunks) {
		for (const word of chunk.words) {
			const fix = fixes.find(
				(f) => Math.abs(Number(f.at) - word.start) < 0.6 && bare(f.was) === bare(word.text)
			);
			if (!fix?.now) continue;

			// Знаки в конце слова принадлежат речи, а не ошибке распознавания:
			// точку и запятую сохраняем на месте.
			const tail = word.text.match(/[.,!?…»)]+$/)?.[0] ?? '';
			word.text = String(fix.now).replace(/[.,!?…»)]+$/, '') + tail;
			done++;
		}
	}

	if (done) console.log(`  правок расшифровки: ${done}`);
	return chunks;
};

const accentsFromModel = (chunks, marks, gap) => {
	const flat = chunks.flatMap((chunk) => chunk.words);
	const taken = [];

	for (const mark of marks) {
		const word = snap(flat, mark);
		if (!word) continue;
		// подряд идущие подсветки сливаются в кашу
		if (taken.some((t) => Math.abs(t[0] - word.start) < Math.min(gap, 2))) continue;

		taken.push([
			Number(word.start.toFixed(2)),
			Number(Math.max(word.end, word.start + 0.15).toFixed(2)),
			word.text,
			mark.tone === 'danger' ? 'danger' : 'gold',
		]);
	}

	return taken.sort((a, b) => a[0] - b[0]);
};

// ── склейки ───────────────────────────────────────────────────
// Движок ставит всего пару движений камеры за ролик — под наш референс
// этого мало. Берём его метки как обязательные и достраиваем ритм:
// склейка на каждом акценте и через равные промежутки в тишине.
const toCuts = ({engine, accents, broll, duration, gap, uneven = 0}) => {
	const marks = new Map();
	const put = (t, kind) => {
		const key = Number(t.toFixed(2));
		if (key < 0.2 || key > duration - 0.4) return;
		// врезка важнее ритма, ритм важнее пустоты
		const rank = {broll: 3, back: 3, accent: 2, base: 1};
		const old = marks.get(key);
		if (!old || rank[kind] > rank[old]) marks.set(key, kind);
	};

	for (const shot of broll) {
		put(shot.from, 'broll');
		put(shot.to, 'back');
	}
	for (const event of engine.camera ?? []) put(Number(event.time), 'accent');
	for (const [from] of accents) put(from, 'accent');

	// ЛИЦО НЕ ТРОГАЕМ БЕЗ ПОВОДА.
	//
	// Раньше здесь стояла сетка: рывок кадра каждые gap секунд, независимо
	// от того, происходит что-нибудь в этот момент или нет. Отсюда и
	// бралось ощущение машинного монтажа — картинка дёргалась ровно, как
	// метроном, и зритель это считывает даже не понимая, что именно не так.
	//
	// В эталоне лицо снято одним планом почти без склеек: ритм держат
	// текст и вставки, а не подёргивание кадра. Мы копировали не то.
	//
	// Теперь метка появляется только там, где и правда что-то произошло:
	// вошла или ушла врезка, прозвучало ударное слово. Сетка осталась
	// одна — на случай, когда человек долго говорит ровно и в кадре
	// действительно ничего нет. Тогда раз в несколько промежутков даётся
	// вдох, чтобы картинка не застыла совсем.
	const events = [...marks.keys()].sort((a, b) => a - b);

	// Порог тишины: пауза короче этой — нормальный длинный план, а не
	// застывший кадр. Три промежутка жанра.
	const still = gap * 3;

	const edges = [0, ...events, duration];
	for (let i = 0; i < edges.length - 1; i++) {
		const from = edges[i];
		const to = edges[i + 1];
		if (to - from < still) continue;

		// Ставим вдох посередине затянувшейся тишины, а при совсем долгой
		// — несколько, но всё равно реже, чем шла прежняя сетка.
		const many = Math.floor((to - from) / still);
		for (let n = 1; n <= many; n++) {
			const at = from + ((to - from) * n) / (many + 1);
			// Рваный темп сдвигает вдох от середины: ровно посередине он
			// сам превращается в сетку, только пореже.
			put(at + (uneven ? uneven * gap * (n % 2 ? 0.5 : -0.5) : 0), 'base');
		}
	}

	return [...marks.entries()]
		.map(([t, kind]) => ({t, kind}))
		.sort((a, b) => a.t - b.t);
};

// ── слово-выкрик ──────────────────────────────────────────────
// Призыв в конце: «напиши слово ЧАТ». Движок помечает такую фразу
// ролью CTA, а нам нужно само слово — оно всплывает в кавычках.
const CALL = /^(напиш|пиши|пишите|ставь|отправ|жми|коммент)/i;
const MARKER = /^(слово|кодовое)$/i;
const clean = (s) => String(s).toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');

const toShouts = (chunks, duration) => {
	const tail = chunks.filter((chunk) => chunk.start > duration * 0.55);
	const words = tail.flatMap((chunk) => chunk.words);

	const take = (word) => [{
		from: Number(word.start.toFixed(2)),
		to: Number((word.start + 1.1).toFixed(2)),
		text: word.text.toUpperCase().replace(/[^\p{L}\p{N}]/gu, ''),
	}];

	const next = (from) => {
		for (let i = from; i < words.length; i++) {
			const value = clean(words[i].text);
			if (!value || value.length < 3) continue;
			if (MARKER.test(value) || CALL.test(value)) continue;
			return words[i];
		}
		return null;
	};

	// Прямое указание точнее любого другого признака, поэтому первым.
	for (let i = 0; i < words.length - 1; i++) {
		if (MARKER.test(clean(words[i].text))) {
			const word = next(i + 1);
			if (word) return take(word);
		}
	}
	for (let i = 0; i < words.length - 1; i++) {
		if (CALL.test(clean(words[i].text))) {
			const word = next(i + 1);
			if (word) return take(word);
		}
	}
	return [];
};

// ── врезки ────────────────────────────────────────────────────
// Клип подбирается по словам в реплике. Сравнение по началу слова,
// а не по подстроке: иначе ключ «рост» срабатывает внутри «просто».
const LIBRARY = [
	// Порядок важен: первый подошедший и выигрывает, поэтому узкие темы
	// стоят выше общих. «Наручники» должны победить «деньги» в фразе
	// «сядешь за эти деньги».
	{file: 'arrest.mp4', keys: ['наручник', 'посад', 'сяд', 'сидеть', 'аресто', 'задерж', 'примут', 'уголовн', 'уголовк', 'уложк', 'статья', 'тюрьм', 'мошенн', 'схем', 'преступ', 'полиц', 'грех', 'винов', 'отлета', 'дроп', '159']},
	{file: 'beach.mp4', keys: ['бали', 'таиланд', 'отдых', 'отлеж', 'море', 'пляж', 'курорт', 'отпуск', 'ретрит', 'заграниц', 'дубай']},
	{file: 'lawyer.mp4', keys: ['директор', 'гендир', 'учредит', 'юрист', 'адвокат', 'нанима', 'наняли', 'должност', 'руковод', 'начальн', 'собствен']},
	{file: 'papers.mp4', keys: ['документ', 'бумаг', 'отчёт', 'отчет', 'бухгалт', 'налог', 'печат', 'справк', 'выписк', 'декларац', 'проверк']},
	// «подпис» нельзя: оно ловит и «подписывайся на канал», а это про соцсети
	{file: 'signing.mp4', keys: ['договор', 'подписал', 'подписан', 'банкротств', 'суд', 'услови', 'закон', 'контракт', 'соглашен']},
	{file: 'flight.mp4', keys: ['самолёт', 'самолет', 'улет', 'уеха', 'уед', 'ехать', 'перелёт', 'перелет', 'билет', 'аэропорт', 'граница', 'свал']},
	{file: 'declined.mp4', keys: ['отказ', 'не проход', 'карт', 'терминал', 'оплат', 'банк', 'списа', 'платёж', 'платеж', 'заблокир']},
	{file: 'cash-counter.mp4', keys: ['деньг', 'наличн', 'сумм', 'рубл', 'тысяч', 'миллион', 'зарплат', 'доход', 'заработ', 'заплач', 'плат', 'лут']},
	{file: 'chart-red.mp4', keys: ['процент', 'ставк', 'долг', 'график', 'рост', 'растёт', 'кредит', 'переплат', 'падает', 'убыт', 'потер']},
	{file: 'shopping.mp4', keys: ['покупк', 'магазин', 'трат', 'шопинг', 'купи', 'потрат', 'вещи', 'расход']},
	{file: 'scroll-feed.mp4', keys: ['телефон', 'лент', 'чат', 'соцсет', 'подписчик', 'подписыв', 'подпишись', 'комьюнити', 'сообществ', 'канал', 'коммент', 'охват', 'просмотр', 'объявлен', 'ваканс', 'хедхантер', 'headhunter']},
];

const matchClip = (chunk) => {
	const words = chunk.words.map((word) => bare(word.text)).filter(Boolean);
	for (const item of LIBRARY) {
		if (words.some((word) => item.keys.some((key) => word.startsWith(key)))) {
			return item.file;
		}
	}
	return null;
};

// Врезки, выбранные моделью: она читает фразу целиком и понимает, о чём
// речь, а словарь ключей ловит только совпадение по началу слова.
const brollFromModel = (marks, {gap = 7, length = 2.6, duration = 0} = {}) => {
	const known = new Set(LIBRARY.map((item) => item.file));
	const shots = [];
	const used = new Set();
	let lastEnd = -Infinity;

	for (const mark of [...marks].sort((a, b) => a.at - b.at)) {
		const file = String(mark.file ?? '').replace(/^.*\//, '');
		// модель могла выдумать имя файла — такой клип просто пропускаем
		if (!known.has(file) || used.has(file)) continue;

		const from = Number(mark.at);
		if (!Number.isFinite(from) || from < 3 || from > duration - 4) continue;
		if (from - lastEnd < gap) continue;

		const to = Number(Math.min(from + length, duration - 1).toFixed(2));
		if (to - from < 1.2) continue;

		// Где показать: во весь экран или карточкой в углу. Углом лицо
		// остаётся в кадре — так показывают доказательство, не бросая
		// говорящего.
		const where = mark.where === 'угол' ? 'угол' : 'экран';
		shots.push({from: Number(from.toFixed(2)), to, file, startFrom: 0, zoom: 1, where});
		used.add(file);
		lastEnd = to;
	}

	return shots;
};

const toBroll = (engine, chunks, {gap = 7, length = 2.6, duration = 0} = {}) => {
	// Если движок подобрал свои клипы — берём их, он смотрит на смысл фразы
	// целиком. Сейчас его библиотека приезжает пустыми файлами из Git LFS,
	// поэтому подбираем сами из наших — они на месте и вертикальные.
	const own = (engine.broll ?? [])
		.flatMap((event) => {
			const shots = event.shots ?? (event.src ? [event] : []);
			return shots.filter((shot) => shot.src).map((shot) => ({
				from: Number(event.from ?? shot.from ?? 0),
				to: Number(event.to ?? shot.to ?? 0),
				file: String(shot.src).replace(/^.*?jobs\/[^/]+\//, ''),
				startFrom: Number(shot.startFrom ?? 0),
				zoom: 1,
			}));
		})
		.filter((shot) => shot.to > shot.from);

	if (own.length) return own;

	const shots = [];
	let lastEnd = -Infinity;
	const used = new Set();

	for (const chunk of chunks) {
		// первые секунды заняты плашкой, последние — призывом
		if (chunk.start < 4 || chunk.start > duration - 4) continue;
		if (chunk.start - lastEnd < gap) continue;

		const file = matchClip(chunk);
		// один и тот же клип дважды подряд выглядит как ошибка монтажа
		if (!file || used.has(file)) continue;

		const from = Number(chunk.start.toFixed(2));
		const to = Number(Math.min(from + length, duration - 1).toFixed(2));
		if (to - from < 1.2) continue;

		// имя без папки: префикс broll/ добавляет сам компонент
		shots.push({from, to, file, startFrom: 0, zoom: 1});
		used.add(file);
		lastEnd = to;
	}

	return shots;
};

// ── речевой монтаж ────────────────────────────────────────────
// Движок вырезает паузы и слегка ускоряет вялые куски. Видео из-за этого
// перестаёт быть линейным: выходная секунда 30 может быть секундой 34
// исходника. Отдаём куски рендеру, он склеит их встык.
const toSpeech = (engine) => {
	const timeline = engine.speechEdit?.timeline ?? [];
	return timeline
		.map((part) => ({
			from: Number(part.source_start),
			to: Number(part.source_end),
			at: Number(part.output_start),
			until: Number(part.output_end),
			speed: Number(part.speed) || 1,
		}))
		.filter((part) => part.until > part.at && part.to > part.from);
};

// ── сборка ────────────────────────────────────────────────────
export const fromEngine = (montage, {template = 'expose', font = null, director = null, ownClips = []} = {}) => {
	const engine = montage && typeof montage === 'object' ? montage : {};
	const duration =
		Number(engine.output?.duration) || Number(engine.source?.duration) || 0;

	// Правки расшифровки применяются первыми: дальше и заголовок,
	// и подсветка берут уже исправленный текст.
	const chunks = applyFixes(toChunks(engine.scenes ?? []), director?.fixes);

	// Жанр ролика модель определяет по содержанию: разоблачение это,
	// разбор или спокойный разговор. От него зависит плотность эффектов.
	const kind = director?.template ?? template;

	// Оформление выбирает модель — под то, о чём и как говорят в ролике.
	// Если она промолчала, оно вычисляется из самого файла: другой
	// исходник почти наверняка получит другую палитру и раскладку.
	const look = pickLook(
		kind,
		fingerprint({
			duration,
			words: chunks.reduce((sum, chunk) => sum + chunk.words.length, 0),
			text: chunks.map((chunk) => chunk.words.map((w) => w.text).join(' ')).join(' '),
		})
	);

	// Выбор модели перебивает выпавшее по отпечатку.
	const asked = director?.look;
	if (asked) {
		if (PALETTES[asked.palette]) look.palette = PALETTES[asked.palette];
		if (LAYOUTS[asked.layout]) look.layout = LAYOUTS[asked.layout];
		if (FONTS[asked.font]) look.font = FONTS[asked.font];
	}

	// Клиент мог выбрать шрифт сам — тогда он перебивает тот, что выпал
	// ролику по отпечатку. Заголовок оставляем дисплейным: подписи
	// субтитров и крупные плашки живут по разным правилам.
	if (font) {
		look.font = {...look.font, key: font, name: font, base: font, accent: font};
	}

	// Везде один порядок: сначала решение модели, потом правила.
	// Пустой ответ модели по любому из пунктов — не повод остаться
	// без разметки: недостающее достраивается по-старому.
	const fromModel = director ?? {};

	let accents = fromModel.accents?.length
		? accentsFromModel(chunks, fromModel.accents, look.accentGap)
		: [];
	if (!accents.length) accents = toAccents(chunks, {gap: look.accentGap, duration});

	let broll = fromModel.broll?.length
		? brollFromModel(fromModel.broll, {duration})
		: [];
	if (!broll.length) broll = toBroll(engine, chunks, {duration});

	// Клиент принёс свои врезки — ставим их вместо наших, по порядку и в
	// те же моменты. Что показать, он решил сам; куда поставить — знает
	// режиссёр, потому что видит, где в речи для этого место.
	if (ownClips.length) {
		broll = broll.map((shot, i) =>
			i < ownClips.length ? {...shot, file: ownClips[i], own: true} : shot
		);
	}

	// Плашки нет ни у одного ролика.
	//
	// Раньше первые секунды занимал крупный заголовок, и мы долго
	// подбирали, когда он уместен. Ответ оказался простым: никогда.
	// Ролик начинается сразу с речи, а разнообразие берётся из манеры
	// субтитров, веса слов, палитры и темпа.
	const title = null;

	// Проходные слова: связки, вводные, повторы. В эталоне размер и есть
	// ударение, поэтому им нужен свой список — иначе всё звучит одинаково
	// громко.
	const flatWords = chunks.flatMap((chunk) => chunk.words);
	const quiet = (fromModel.quiet ?? [])
		.map((mark) => snap(flatWords, mark))
		.filter(Boolean)
		.map((word) => [
			Number(word.start.toFixed(2)),
			Number(Math.max(word.end, word.start + 0.12).toFixed(2)),
		])
		.sort((a, b) => a[0] - b[0]);

	// Почерк этого ролика: как ведёт себя текст, в каком темпе идут
	// склейки, насколько громко оформление. Выбирает модель — без неё
	// берётся то, как было всегда.
	const manner = toManner(director?.manner);
	const tempo = PACE[manner.pace] ?? PACE['ровно'];

	// Жанр говорит о плотности вообще, темп — об этом ролике. Поэтому
	// множитель идёт к промежутку, заданному жанром, а не заменяет его.
	const cutGap = look.cutGap * tempo.cut;

	const plan = {
		accents,
		broll,
		shouts: toShouts(chunks, duration),
		quiet,
		cuts: toCuts({engine, accents, broll, duration, gap: cutGap, uneven: tempo.uneven}),
		title,
		// палитра, раскладка и шрифт этого ролика
		look,
		manner,
		// насколько сильно дышит кадр между склейками
		tempo,
		face: engine.face ?? null,
	};

	// Последняя проверка уже собранного плана. Найденное не молчим:
	// без этого нарушение всплывёт только у клиента в ленте.
	const problems = checkSafeArea(plan);
	if (problems.length) {
		console.warn(`  внимание: текст выходит за рамку площадки — ${JSON.stringify(problems)}`);
	}

	return {duration, chunks, speech: toSpeech(engine), plan};
};

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
import {checkSafeArea, fitTitle} from './safety.js';

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
const toCuts = ({engine, accents, broll, duration, gap}) => {
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

	// ритмические метки там, где долго ничего не происходит
	const busy = (t) => [...marks.keys()].some((m) => Math.abs(m - t) < gap * 0.7);
	for (let t = gap; t < duration - 0.6; t += gap) {
		if (!busy(t)) put(t, 'base');
	}

	return [...marks.entries()]
		.map(([t, kind]) => ({t, kind}))
		.sort((a, b) => a.t - b.t);
};

// ── титульная плашка ──────────────────────────────────────────
// Первые секунды — заголовок ролика. Длинные слова идут крупно,
// короткие уходят на бейджи: так строка не расползается и держит ритм.
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

// Пока висит плашка, субтитров нет: она их заменяет. Значит и уйти она
// должна ровно тогда, когда договорено последнее её слово — иначе слово
// исчезает с плашкой и тут же выезжает субтитром, будто его написали
// дважды.
const titleEnd = (chunks, text) => {
	const wanted = String(text).split(/\s+/).map(bare).filter(Boolean);
	if (!wanted.length) return null;

	const flat = chunks.flatMap((chunk) => chunk.words);
	const set = new Set(wanted);
	let last = null;
	let missed = 0;

	// Заголовок пересказывает начало речи, и слово в слово совпадает не
	// всегда: «100 тысяч» вполне может стать «100 000». Поэтому идём по
	// расшифровке и запоминаем последнее совпадение, а не требуем, чтобы
	// сошлись все слова подряд. Три промаха кряду — значит заголовок
	// кончился и дальше идёт обычная речь.
	for (const word of flat) {
		const clean = bare(word.text);
		if (!clean) continue;

		if (set.has(clean) || [...set].some((w) => clean.startsWith(w) || w.startsWith(clean))) {
			last = word;
			missed = 0;
		} else if (last && ++missed >= 3) {
			break;
		}
	}

	// Дольше шести секунд плашка перекрывает уже сам ролик.
	return last ? Math.min(6, last.end) : null;
};

// Модель уже разбила заголовок на строки — по смыслу, а не по счёту
// символов. Своё деление здесь только навредило бы: оно нарезает ровными
// кусками и рвёт словосочетания.
const titleFromModel = (chunks, lines, until) => {
	const DX = [0, 78, -10, -72];
	const clean = lines
		.map((line) => String(line).trim())
		.filter(Boolean)
		.slice(0, 4);

	if (!clean.length) return null;

	// Когда плашке уходить, решает модель: она знает, какие слова в неё
	// вошла. Её число проверяем по расшифровке — если она промахнулась
	// мимо речи, берём то, что насчитали сами.
	const spoken = titleEnd(chunks, clean.join(' '));
	const asked = Number(until);
	const end =
		Number.isFinite(asked) && asked > 0.5 && asked <= 6 && (!spoken || Math.abs(asked - spoken) < 1.5)
			? asked
			: spoken ?? Math.min(3.5, chunks[Math.min(1, chunks.length - 1)]?.end ?? 3.2);

	return {
		in: 0.15,
		out: Number(end.toFixed(2)),
		// чередование крупной строки и бейджа — как на референсе
		lines: clean.map((text, i) => ({
			dx: DX[i] ?? 0,
			pieces: [{kind: i % 2 === 0 ? 'big' : 'badge', text}],
		})),
	};
};

const toTitle = (chunks, hook) => {
	const source = String(hook?.text || chunks[0]?.words.map((w) => w.text).join(' ') || '');
	const all = source.replace(/[?!.]+$/, '').split(/\s+/).filter(Boolean);
	if (!all.length) return null;

	// Четыре строки — как на референсе: «КАК БЫСТРО / находить /
	// ЗАЛЕТАЮЩИЕ / идеи». Больше не влезает по высоте кадра.
	const MAX_LINES = 4;
	const MAX_CHARS = 68;

	// Длинный заголовок обрезаем по словам, а не по символам, и не оставляем
	// в конце предлог или союз — «и что с» смотрится как оборванная мысль.
	const HANGING = /^(и|а|но|да|или|же|бы|ли|в|во|на|за|под|над|при|про|с|со|к|ко|у|о|об|из|от|до|для|без|через|что|как|это|уже|ещё|там|тут)$/i;

	let budget = 0;
	const words = [];
	for (const word of all) {
		if (words.length >= 10) break;
		if (budget + word.length + 1 > MAX_CHARS && words.length) break;
		budget += word.length + 1;
		words.push(word);
	}
	while (words.length > 1 && HANGING.test(words[words.length - 1])) words.pop();

	// Строка крупным кеглем вмещает около девятнадцати заглавных букв —
	// дальше она либо уезжает за край, либо ужимается до нечитаемого.
	// Берём наименьшее число строк, при котором в этот предел укладываемся,
	// и делим текст поровну: так строки выходят ровными, а не «длинная-огрызок».
	const MAX_PER_LINE = 19;
	const length = words.join(' ').length;
	const needed = Math.max(1, Math.min(MAX_LINES, Math.ceil(length / MAX_PER_LINE)));
	const perLine = Math.ceil(length / needed);

	const lines = [];
	let buffer = [];
	// бейджи слегка разъезжаются: ровная колонка выглядит мёртвой
	const DX = [0, 78, -10, -72];

	// Строка не должна кончаться предлогом или союзом: «год без» на одной
	// строке и «процентов» на другой читается как обрыв. Такое слово
	// уезжает вниз, к тому, к чему относится.
	const flush = (carry = []) => {
		if (!buffer.length) return carry;
		const moved = [];
		while (buffer.length > 1 && HANGING.test(buffer[buffer.length - 1])) {
			moved.unshift(buffer.pop());
		}
		const kind = lines.length % 2 === 0 ? 'big' : 'badge';
		lines.push({dx: DX[lines.length] ?? 0, pieces: [{kind, text: buffer.join(' ')}]});
		buffer = [];
		return moved;
	};

	// Перенос решается ДО того, как слово попадёт в строку: иначе длинное
	// слово уже влезло, и строка выходит за отведённую ширину.
	let carry = [];
	for (let i = 0; i < words.length; i++) {
		const word = words[i];
		const would = [...buffer, ...carry, word].join(' ').length;

		if (buffer.length && would > perLine && lines.length < MAX_LINES - 1) {
			carry = [...flush(), ...carry];
		}

		buffer.push(...carry, word);
		carry = [];
	}
	flush();

	// Одинокое короткое слово в последней строке выглядит как опечатка —
	// подклеиваем его к предыдущей.
	if (lines.length > 1) {
		const last = lines[lines.length - 1].pieces[0];
		if (last.text.length <= 5 && !last.text.includes(' ')) {
			lines.pop();
			const prev = lines[lines.length - 1].pieces[0];
			prev.text = `${prev.text} ${last.text}`;
		}
	}

	// Плашка держится, пока не договорено последнее её слово: иначе оно
	// исчезнет вместе с ней и тут же появится субтитром.
	const spoken = titleEnd(chunks, lines.map((l) => l.pieces[0].text).join(' '));
	const end = spoken ?? Math.min(3.5, chunks[Math.min(1, chunks.length - 1)]?.end ?? 3.2);

	return {in: 0.15, out: Number(end.toFixed(2)), lines: lines.slice(0, 4)};
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

		shots.push({from: Number(from.toFixed(2)), to, file, startFrom: 0, zoom: 1});
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

	let title = fromModel.title?.lines?.length
		? titleFromModel(chunks, fromModel.title.lines, fromModel.title.until)
		: null;
	if (!title) title = toTitle(chunks, engine.speechEdit?.hook);

	// Каждый монтаж прогоняется через рамку площадки: сверху шапка, справа
	// колонка кнопок, снизу подпись, по бокам обрезаемые края. Заголовок
	// придумывает модель, длину слов не угадать — что не влезло, укорачиваем
	// по словам, а не обрезаем по буквам.
	if (title) title = fitTitle(title);

	// Не каждый ролик надо открывать заголовком: если человек заходит
	// издалека, плашка поверх такого начала выглядит наклейкой. Решает
	// модель — она видит, чем начинается речь.
	if (director?.opening === 'сразу') title = null;

	const cutGap = look.cutGap;

	const plan = {
		accents,
		broll,
		shouts: toShouts(chunks, duration),
		cuts: toCuts({engine, accents, broll, duration, gap: cutGap}),
		title,
		// палитра, раскладка и шрифт этого ролика
		look,
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

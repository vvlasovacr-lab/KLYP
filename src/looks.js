// ОФОРМЛЕНИЯ.
//
// Приложением пользуются разные люди, и ролики не должны выглядеть
// близнецами. Поэтому у каждого шаблона есть набор вариантов: палитра,
// раскладка текста, шрифт. Вариант выбирается не случайно, а вычисляется
// из самого исходника — длительности, текста, ритма речи.
//
// Почему не случайно: клиент нажимает «пересобрать» и ждёт исправления
// своих замечаний, а не новой шкурки. Один исходник — одно оформление.
// Зато другой исходник почти наверняка получит другое.

// ── палитры ───────────────────────────────────────────────────
// Первый цвет — обычные акценты, второй — тревожные (долг, проблема,
// потеря). Бейдж — плашка под короткими словами в заголовке.
export const PALETTES = {
	gold: {
		name: 'золото',
		accent: 'linear-gradient(180deg,#FCE6C0 0%,#EDBA7C 52%,#D9964E 100%)',
		danger: 'linear-gradient(180deg,#FFB0A6 0%,#F2685A 52%,#D33B2C 100%)',
		badge: '#8E1119',
		badgeInk: '#FFF3E4',
		title: '#F5E9DA',
	},
	crimson: {
		name: 'алый',
		accent: 'linear-gradient(180deg,#FFD9D2 0%,#FF6B5A 52%,#E02D1B 100%)',
		danger: 'linear-gradient(180deg,#FFE7A8 0%,#F5C24B 52%,#D99A1F 100%)',
		badge: '#1A1A1A',
		badgeInk: '#FFFFFF',
		title: '#FFFFFF',
	},
	ice: {
		name: 'лёд',
		accent: 'linear-gradient(180deg,#DFF3FF 0%,#7FC4EC 52%,#3E92C4 100%)',
		danger: 'linear-gradient(180deg,#FFC9C0 0%,#F1705F 52%,#C93B29 100%)',
		badge: '#123245',
		badgeInk: '#E8F6FF',
		title: '#F2FAFF',
	},
	acid: {
		name: 'кислота',
		accent: 'linear-gradient(180deg,#F2FFB8 0%,#C6F24E 52%,#8FBE18 100%)',
		danger: 'linear-gradient(180deg,#FFD0E4 0%,#F45D9B 52%,#C42463 100%)',
		badge: '#14260A',
		badgeInk: '#EEFFCC',
		title: '#FFFFFF',
	},
	mint: {
		name: 'мята',
		accent: 'linear-gradient(180deg,#D8FFF0 0%,#69D9AF 52%,#2FA37B 100%)',
		danger: 'linear-gradient(180deg,#FFDCC2 0%,#F0904A 52%,#C55F16 100%)',
		badge: '#0E2A22',
		badgeInk: '#E6FFF6',
		title: '#F4FFFB',
	},
	violet: {
		name: 'фиолет',
		accent: 'linear-gradient(180deg,#EEDBFF 0%,#B47BE8 52%,#8341C0 100%)',
		danger: 'linear-gradient(180deg,#FFD4C4 0%,#F2556B 52%,#C9451C 100%)',
		badge: '#1E1030',
		badgeInk: '#F3E6FF',
		title: '#FBF5FF',
	},
};

// ── раскладки текста ──────────────────────────────────────────
// Где стоят субтитры и как выровнены. Все варианты держатся ниже лица
// и выше нижней панели площадки — иначе текст перекроет интерфейс.
export const LAYOUTS = {
	chest: {name: 'на груди', topY: 0.5, align: 'center', titleY: 0.46},
	low: {name: 'низко', topY: 0.6, align: 'center', titleY: 0.5},
	leftColumn: {name: 'столбиком слева', topY: 0.52, align: 'left', titleY: 0.44},
	high: {name: 'над плечом', topY: 0.44, align: 'center', titleY: 0.4},
};

// ── шрифтовые пары ────────────────────────────────────────────
export const FONTS = {
	montserrat: {name: 'Montserrat', base: 'Montserrat', accent: 'Montserrat', title: 'Oswald'},
	unbounded: {name: 'Unbounded', base: 'Manrope', accent: 'Unbounded', title: 'Unbounded'},
	oswald: {name: 'Oswald', base: 'GolosText', accent: 'Oswald', title: 'Oswald'},
};

// ── шаблоны ───────────────────────────────────────────────────
// Каждый задаёт характер монтажа и список допустимых вариантов
// оформления. Внутри шаблона все варианты уместны — поэтому любой
// из них можно выдать клиенту, не спрашивая.
export const TEMPLATES = {
	expose: {
		title: 'Разоблачение',
		accentGap: 3.0,
		cutGap: 2.2,
		palettes: ['gold', 'crimson', 'violet'],
		layouts: ['chest', 'low', 'leftColumn'],
		fonts: ['montserrat', 'unbounded'],
	},
	breakdown: {
		title: 'Разбор',
		accentGap: 4.2,
		cutGap: 3.4,
		palettes: ['ice', 'mint', 'gold'],
		layouts: ['leftColumn', 'chest'],
		fonts: ['oswald', 'montserrat'],
	},
	case: {
		title: 'Кейс',
		accentGap: 3.4,
		cutGap: 2.8,
		palettes: ['mint', 'gold', 'ice'],
		layouts: ['chest', 'high'],
		fonts: ['montserrat', 'oswald'],
	},
	hook: {
		title: 'Хук',
		accentGap: 2.4,
		cutGap: 1.9,
		palettes: ['acid', 'crimson', 'violet'],
		layouts: ['low', 'chest'],
		fonts: ['unbounded', 'montserrat'],
	},
	offer: {
		title: 'Оффер',
		accentGap: 2.8,
		cutGap: 2.2,
		palettes: ['gold', 'acid', 'crimson'],
		layouts: ['chest', 'high'],
		fonts: ['unbounded', 'oswald'],
	},
};

// ── выбор варианта ────────────────────────────────────────────

// Отпечаток исходника: число, в котором отражается и длина ролика,
// и то, что в нём сказано. Разные видео дают разные числа, одно и то же —
// всегда одинаковое.
export const fingerprint = ({duration = 0, text = '', words = 0} = {}) => {
	let hash = 2166136261;
	const source = `${Math.round(duration * 100)}|${words}|${String(text).slice(0, 400)}`;

	for (let i = 0; i < source.length; i++) {
		hash ^= source.charCodeAt(i);
		// множитель FNV: перемешивает биты так, что близкие строки
		// расходятся далеко друг от друга
		hash = Math.imul(hash, 16777619) >>> 0;
	}
	return hash >>> 0;
};

// Отдельный хеш на каждую ось. Сдвигать один и тот же отпечаток нельзя:
// остатки от деления получаются связанными, и палитра тянет за собой
// раскладку — из шести вариантов реально выпадали бы два.
const mix = (seed, salt) => {
	let value = (seed ^ Math.imul(salt, 0x9e3779b1)) >>> 0;
	value = Math.imul(value ^ (value >>> 15), 0x85ebca6b) >>> 0;
	value = Math.imul(value ^ (value >>> 13), 0xc2b2ae35) >>> 0;
	return (value ^ (value >>> 16)) >>> 0;
};

const pick = (list, seed) => list[seed % list.length];

// Оформление ролика: шаблон задаёт рамки, отпечаток выбирает вариант.
export const pickLook = (templateCode, mark) => {
	const template = TEMPLATES[templateCode] ?? TEMPLATES.expose;
	const seed = Number.isFinite(mark) ? mark >>> 0 : 0;

	const palette = pick(template.palettes, mix(seed, 1));
	const layout = pick(template.layouts, mix(seed, 2));
	const font = pick(template.fonts, mix(seed, 3));

	return {
		template: templateCode,
		accentGap: template.accentGap,
		cutGap: template.cutGap,
		palette: {key: palette, ...PALETTES[palette]},
		layout: {key: layout, ...LAYOUTS[layout]},
		font: {key: font, ...FONTS[font]},
	};
};

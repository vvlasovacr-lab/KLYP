// ПОДГОНКА ТЕКСТА ПОД ШИРИНУ КАДРА.
//
// Замерить строку по-настоящему можно только в DOM, а рендер собирает кадр
// без раскладки — поэтому ширина прикидывается по символам. Прикидка грубая,
// но нужна не точность, а гарантия: длинное слово вроде «БЕСПРОЦЕНТНЫХ»
// или «АЛЬФА-БАНКА» обязано ужаться, а не уехать за край.

// Доли кегля на символ. Заглавные шире строчных, знаки уже обоих.
const CHAR_W = {caps: 0.74, lower: 0.62, other: 0.36};

export const estimateWidth = (text, {size, uppercase = false, padding = 0}) => {
	const value = uppercase ? String(text).toUpperCase() : String(text);
	let units = padding;

	for (const ch of value) {
		if (/[A-ZА-ЯЁ0-9]/.test(ch)) units += CHAR_W.caps;
		else if (/[a-zа-яё]/.test(ch)) units += CHAR_W.lower;
		else units += CHAR_W.other;
	}

	return units * size;
};

// Во сколько раз ужать, чтобы самый длинный кусок влез в отведённую ширину.
// Общий масштаб на всю группу: если ужимать каждую строку по-своему,
// заголовок рассыпается на куски разного размера.
export const fitScale = (items, maxPx, {minimum = 0.5} = {}) => {
	const longest = items.reduce((widest, item) => Math.max(widest, estimateWidth(item.text, item)), 0);
	if (longest <= maxPx || longest === 0) return 1;
	return Math.max(minimum, maxPx / longest);
};

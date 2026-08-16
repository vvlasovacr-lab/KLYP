// СУБТИТРЫ ПО ОДНОМУ СЛОВУ.
//
// В кадре всегда ровно одно слово — то, которое звучит сейчас. Оно
// мягко всплывает и так же мягко уходит, уступая место следующему.
//
// Почему не строкой целиком: строка заставляет глаз бегать по кадру и
// читать наперёд, а слово под голосом читается само. Плюс к моменту
// показа известно ровно одно слово — ошибиться вёрсткой негде, тогда
// как строку надо переносить, ужимать и следить, чтобы она не залезла
// в слепую зону.
//
// Тайминги берутся из распознавания: у каждого слова своя секунда.
// Слово держится до начала следующего, поэтому пустот между ними нет.

import {interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {SAFE, SUB} from './style.js';

// Прикидка ширины слова без замеров в DOM — чтобы длинные слова
// вроде «БЕСПРОЦЕНТНЫХ» сами ужимались и не резались о края кадра.
const CHAR_W = {caps: 0.74, lower: 0.62, other: 0.36};

const estimateWidth = (text, tier, size) => {
	const s = tier.uppercase ? text.toUpperCase() : text;
	let units = 0;
	for (const ch of s) {
		if (/[A-ZА-ЯЁ0-9]/.test(ch)) units += CHAR_W.caps;
		else if (/[a-zа-яё]/.test(ch)) units += CHAR_W.lower;
		else units += CHAR_W.other;
	}
	return units * size;
};

// ── сколько слово живёт на экране ────────────────────────────
// Короткие служебные слова звучат по десятой доле секунды. Показывать
// их столько же — мельтешение, которое глаз не успевает прочесть.
// Поэтому слово держится до следующего, но не меньше своего минимума.
const MIN_HOLD = 0.26;
// Пауза длиннее этой — конец мысли: экран пустеет, а не тянет слово.
const MAX_HOLD = 0.9;

// Появление и уход. Значения нарочно маленькие: на вертикальном видео
// длинные переходы читаются как задержка, а не как плавность.
const IN = 0.13;
const OUT = 0.1;

const timeline = (chunks) => {
	const words = chunks.flatMap((chunk) =>
		chunk.words.map((w) => ({...w, chunkStart: chunk.start}))
	);

	return words.map((word, i) => {
		const next = words[i + 1];
		const natural = Math.max(word.end, word.start + MIN_HOLD);
		const until = next
			? Math.min(Math.max(next.start, word.start + MIN_HOLD), word.end + MAX_HOLD)
			: natural + 0.35;

		return {...word, from: word.start, until};
	});
};

export const Subtitles = ({chunks, time, fromSeconds, isAccent, brollAt, look}) => {
	useCurrentFrame();
	const {width, height} = useVideoConfig();

	const words = timeline(chunks);
	const word = words.find((w) => time >= w.from && time < w.until);
	if (!word) return null;

	// Оформление у каждого ролика своё: палитра, высота строки, шрифт.
	// Без него берётся стиль-кит — так студия открывается как раньше.
	const accentTier = look
		? {...SUB.accent, gradient: look.palette.accent, font: look.font.accent}
		: SUB.accent;
	const baseTier = look ? {...SUB.base, font: look.font.base} : SUB.base;
	const tier = isAccent(word.start) ? accentTier : baseTier;

	// Высота выбирается по началу слова: если под ним врезка, текст
	// уходит выше, чтобы не сесть на чужую картинку.
	const topY = brollAt(word.from) ? SUB.onCardTopY : (look?.layout.topY ?? SUB.topY);

	// Слово тянется на всю отведённую ширину: короткое «я» встаёт крупно,
	// длинное «учредители» ужимается до края. Кегль пляшет от слова к
	// слову — и это как раз то, что держит внимание: строка неподвижной
	// высоты читается как бегущая строка, а не как речь.
	//
	// Потолок и пол нужны, чтобы двухбуквенное слово не занимало полкадра,
	// а самое длинное осталось читаемым.
	const maxPx = width * SUB.maxWidth;
	const own = estimateWidth(word.text, tier, tier.size);
	const size = Math.min(
		tier.size * SUB.growTo,
		Math.max(tier.size * SUB.minFit, (tier.size * maxPx) / own)
	);

	const life = word.until - word.from;
	const enter = Math.min(IN, life / 3);
	const leave = Math.min(OUT, life / 3);

	// Приход и уход считаем по времени, а не пружиной: слово живёт доли
	// секунды, и пружина не успевает дойти до покоя — получается дёрганье.
	const appear = interpolate(time, [word.from, word.from + enter], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const fade = interpolate(time, [word.until - leave, word.until], [1, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	const opacity = Math.min(appear, fade);
	// Всплывает снизу и слегка растёт — движение читается как «сказано»,
	// а не как «выехала плашка».
	const rise = interpolate(appear, [0, 1], [SUB.riseFrom, 0]);
	const scale = interpolate(appear, [0, 1], [0.88, 1]);

	const paint = tier.gradient
		? {
				backgroundImage: tier.gradient,
				WebkitBackgroundClip: 'text',
				backgroundClip: 'text',
				WebkitTextFillColor: 'transparent',
				color: 'transparent',
			}
		: {color: tier.color};

	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				top: height * topY,
				// центрируем по видимой части кадра, а не по кадру целиком:
				// справа колонка кнопок, и текст должен стоять по центру того,
				// что зритель реально видит
				transform: `translateX(${(SAFE.centerX - 0.5) * width}px)`,
				display: 'flex',
				justifyContent: 'center',
				filter: SUB.shadow,
			}}
		>
			<span
				style={{
					display: 'inline-block',
					fontFamily: tier.font,
					fontWeight: tier.weight,
					fontSize: size,
					letterSpacing: '-0.01em',
					whiteSpace: 'nowrap',
					transform: `translateY(${rise}px) scale(${scale})`,
					transformOrigin: 'center bottom',
					opacity,
					...paint,
				}}
			>
				{tier.uppercase ? word.text.toUpperCase() : word.text}
			</span>
		</div>
	);
};

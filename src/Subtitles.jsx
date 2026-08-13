import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SAFE, SUB} from './style.js';

// Прикидка ширины слова без замеров в DOM — чтобы длинные слова
// вроде «БЕСПРОЦЕНТНЫХ» сами ужимались и не резались о края кадра.
const CHAR_W = {caps: 0.74, lower: 0.62, other: 0.36};
const SIDE_MARGINS = parseFloat(SUB.gap) * 2; // отступы слева и справа, в долях кегля

const estimateWidth = (text, tier, size) => {
	const s = tier.uppercase ? text.toUpperCase() : text;
	let units = SIDE_MARGINS;
	for (const ch of s) {
		if (/[A-ZА-ЯЁ0-9]/.test(ch)) units += CHAR_W.caps;
		else if (/[a-zа-яё]/.test(ch)) units += CHAR_W.lower;
		else units += CHAR_W.other;
	}
	return units * size;
};

// одно самое длинное слово задаёт масштаб для всей реплики,
// иначе соседние слова прыгали бы в размере
const fitScale = (words, tier, maxPx) => {
	const longest = words.reduce(
		(acc, w) => Math.max(acc, estimateWidth(w, tier, tier.size)),
		0
	);
	if (longest <= maxPx) return 1;
	return Math.max(SUB.minFit, maxPx / longest);
};

const Word = ({word, tier, size, isActive, enterFrame, fps, frame}) => {
	const local = frame - enterFrame;

	const appear = spring({
		frame: local,
		fps,
		config: {damping: 13, stiffness: 190, mass: 0.55},
	});
	const pop = spring({
		frame: local,
		fps,
		config: {damping: 11, stiffness: 240, mass: 0.4},
	});

	// слово, которого ещё не было, держит своё место, но невидимо —
	// так строка не прыгает, когда появляется следующее
	const hidden = local < 0;
	const scale =
		interpolate(appear, [0, 1], [0.72, 1]) * (isActive ? 1 + SUB.pop * pop : 1);
	const y = interpolate(appear, [0, 1], [SUB.riseFrom, 0]);

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
		<span
			style={{
				display: 'inline-block',
				margin: `0 ${SUB.gap}`,
				fontFamily: tier.font,
				fontWeight: tier.weight,
				fontSize: size,
				transform: `translateY(${hidden ? SUB.riseFrom : y}px) scale(${
					hidden ? 0.72 : scale
				})`,
				opacity: hidden ? 0 : appear,
				transformOrigin: 'center bottom',
				...paint,
			}}
		>
			{tier.uppercase ? word.toUpperCase() : word}
		</span>
	);
};

export const Subtitles = ({chunks, time, fromSeconds, isAccent, brollAt, look}) => {
	const frame = useCurrentFrame();
	const {fps, width, height} = useVideoConfig();

	const chunk = chunks.find((c) => time >= c.start && time < c.end);
	if (!chunk) return null;

	// Оформление у каждого ролика своё: палитра, высота строки, шрифт.
	// Без него берётся стиль-кит — так студия открывается как раньше.
	const accentTier = look
		? {...SUB.accent, gradient: look.palette.accent, font: look.font.accent}
		: SUB.accent;
	const baseTier = look ? {...SUB.base, font: look.font.base} : SUB.base;

	// последнее прозвучавшее слово — оно подсвечено
	const activeIndex = chunk.words.reduce(
		(acc, w, i) => (time >= w.start ? i : acc),
		0
	);

	// высоту строка выбирает один раз — в момент своего появления.
	// Иначе на стыке с врезкой она прыгала бы по вертикали посреди слова.
	const topY = brollAt(chunk.start)
		? SUB.onCardTopY
		: (look?.layout.topY ?? SUB.topY);

	// строка гаснет, а не пропадает рывком; у совсем коротких реплик
	// затухание укорачивается, чтобы они не начинали гаснуть сразу
	const fade = Math.min(SUB.fadeOut, (chunk.end - chunk.start) / 2);
	const leave = interpolate(time, [chunk.end - fade, chunk.end], [1, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	const maxPx = width * SUB.maxWidth;
	const tierOf = (w) => (isAccent(w.start) ? accentTier : baseTier);
	const fit = new Map(
		[accentTier, baseTier].map((tier) => [
			tier,
			fitScale(
				chunk.words.filter((w) => tierOf(w) === tier).map((w) => w.text),
				tier,
				maxPx
			),
		])
	);

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
				opacity: leave,
			}}
		>
			<div
				style={{
					width: width * SUB.maxWidth,
					// Выравнивание — часть оформления: где-то текст стоит по центру,
					// где-то собран столбиком у левого края, как на референсах.
					textAlign: look?.layout.align ?? 'center',
					lineHeight: SUB.lineGap,
					letterSpacing: '-0.01em',
				}}
			>
				{chunk.words.map((w, i) => (
					<Word
						key={i}
						word={w.text}
						tier={tierOf(w)}
						size={tierOf(w).size * fit.get(tierOf(w))}
						isActive={i === activeIndex}
						enterFrame={Math.round((w.start - fromSeconds) * fps)}
						fps={fps}
						frame={frame}
					/>
				))}
			</div>
		</div>
	);
};

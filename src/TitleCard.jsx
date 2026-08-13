import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SAFE, TITLE} from './style.js';
import {fitScale} from './fit.js';

const Piece = ({piece, fit = 1, look}) => {
	const isBadge = piece.kind === 'badge';
	const base = isBadge ? TITLE.badge : TITLE.big;

	// Палитра ролика перебивает стиль-кит: цвет плашки, фон и цвет бейджа.
	const cfg = look
		? {
				...base,
				color: isBadge ? look.palette.badgeInk : look.palette.title,
				...(isBadge ? {bg: look.palette.badge} : {}),
			}
		: base;

	const text = cfg.uppercase ? piece.text.toUpperCase() : piece.text;

	return (
		<span
			style={{
				display: 'inline-block',
				fontFamily: look?.font.title ?? TITLE.font,
				fontWeight: cfg.weight,
				fontSize: Math.round(cfg.size * fit),
				color: cfg.color,
				lineHeight: 1.05,
				letterSpacing: isBadge ? '0.01em' : '-0.005em',
				whiteSpace: 'nowrap',
				transform: `skewX(${TITLE.skew}deg)`,
				...(isBadge
					? {
							backgroundColor: cfg.bg,
							padding: `${cfg.padY}px ${cfg.padX}px`,
							borderRadius: cfg.radius,
						}
					: {}),
			}}
		>
			{text}
		</span>
	);
};

const Line = ({line, index, fps, frame, enterFrame, fit, look}) => {
	const local = frame - enterFrame - Math.round(index * TITLE.stagger * fps);
	const appear = spring({
		frame: local,
		fps,
		config: {damping: 14, stiffness: 170, mass: 0.6},
	});

	const hidden = local < 0;
	const scale = interpolate(appear, [0, 1], [0.86, 1]);
	const y = interpolate(appear, [0, 1], [40, 0]);

	return (
		<div
			style={{
				marginTop: index === 0 ? 0 : TITLE.lineOverlap,
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				gap: TITLE.wordGap,
				transform: `translate(${line.dx}px, ${hidden ? 40 : y}px) scale(${
					hidden ? 0.86 : scale
				})`,
				opacity: hidden ? 0 : appear,
				transformOrigin: 'center center',
			}}
		>
			{line.pieces.map((piece, i) => (
				<Piece key={i} piece={piece} fit={fit} look={look} />
			))}
		</div>
	);
};

export const TitleCard = ({title, time, fromSeconds = 0, look}) => {
	const T = title ?? TITLE;
	const frame = useCurrentFrame();
	const {fps, width, height} = useVideoConfig();
	const shiftX = (SAFE.centerX - 0.5) * width;

	if (time < T.in || time >= T.out) return null;

	// Заголовок приходит из речи клиента: там может оказаться и «Три ошибки»,
	// и «Как кредитка Альфа-Банка». Кегль общий на все строки и подбирается
	// по самой длинной, иначе строки разъедутся по размеру.
	const room = width * (SAFE.centerX * 2 - SAFE.side * 2) - Math.abs(shiftX);
	const fit = fitScale(
		T.lines.map((line) => ({
			text: line.pieces.map((piece) => piece.text).join(' '),
			size: (line.pieces[0]?.kind === 'badge' ? TITLE.badge : TITLE.big).size,
			uppercase: (line.pieces[0]?.kind === 'badge' ? TITLE.badge : TITLE.big).uppercase,
			// бейджи занимают ещё и внутренние поля
			padding: line.pieces[0]?.kind === 'badge' ? 0.5 : 0,
		})),
		room
	);

	// плашка уходит целиком за последние доли секунды
	const leave = interpolate(
		time,
		[T.out - TITLE.fadeOut, T.out],
		[0, 1],
		{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
	);

	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				top: height * TITLE.anchorY,
				transform: `translate(${shiftX}px, -50%) scale(${1 + leave * 0.06})`,
				opacity: 1 - leave,
				display: 'flex',
				flexDirection: 'column',
				alignItems: 'center',
				filter:
					'drop-shadow(0 4px 10px rgba(0,0,0,0.55)) drop-shadow(0 16px 40px rgba(0,0,0,0.45))',
			}}
		>
			{T.lines.map((line, i) => (
				<Line
					key={i}
					line={line}
					index={i}
					fps={fps}
					frame={frame}
					fit={fit}
					look={look}
					enterFrame={Math.round((T.in - fromSeconds) * fps)}
				/>
			))}
		</div>
	);
};

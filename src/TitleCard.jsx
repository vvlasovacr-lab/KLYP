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

// Одно слово плашки. Всплывает само по себе, со своей задержкой —
// заголовок набирается на глазах, а не выпрыгивает готовым куском.
const Rising = ({delay, fps, frame, children}) => {
	const local = frame - delay;
	const appear = spring({
		frame: local,
		fps,
		config: {damping: 14, stiffness: 180, mass: 0.55},
	});

	const hidden = local < 0;

	return (
		<span
			style={{
				display: 'inline-block',
				transform: `translateY(${hidden ? 26 : interpolate(appear, [0, 1], [26, 0])}px)` +
					` scale(${hidden ? 0.9 : interpolate(appear, [0, 1], [0.9, 1])})`,
				opacity: hidden ? 0 : appear,
				transformOrigin: 'center bottom',
			}}
		>
			{children}
		</span>
	);
};

const Line = ({line, index, fps, frame, enterFrame, fit, look, from}) => {
	// Слово за словом. Бейдж не дробим: у него общая подложка, и по словам
	// она рассыпалась бы на несколько плашек.
	let seen = from;

	return (
		<div
			style={{
				marginTop: index === 0 ? 0 : TITLE.lineOverlap,
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
				gap: TITLE.wordGap,
				transform: `translateX(${line.dx}px)`,
			}}
		>
			{line.pieces.map((piece, i) => {
				if (piece.kind === 'badge') {
					const delay = enterFrame + Math.round(seen * TITLE.wordStep * fps);
					seen += 1;
					return (
						<Rising key={i} delay={delay} fps={fps} frame={frame}>
							<Piece piece={piece} fit={fit} look={look} />
						</Rising>
					);
				}

				const words = String(piece.text).split(/\s+/).filter(Boolean);
				return words.map((word, w) => {
					const delay = enterFrame + Math.round(seen * TITLE.wordStep * fps);
					seen += 1;
					return (
						<Rising key={`${i}-${w}`} delay={delay} fps={fps} frame={frame}>
							<Piece piece={{...piece, text: word}} fit={fit} look={look} />
						</Rising>
					);
				});
			})}
		</div>
	);
};

// Сколько слов в строке — чтобы следующая строка начинала отсчёт с них,
// а не с нуля: иначе вторая строка обгонит первую.
const wordsIn = (line) =>
	line.pieces.reduce(
		(n, piece) =>
			n + (piece.kind === 'badge' ? 1 : String(piece.text).split(/\s+/).filter(Boolean).length),
		0
	);

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
					from={T.lines.slice(0, i).reduce((n, l) => n + wordsIn(l), 0)}
				/>
			))}
		</div>
	);
};

import {
	AbsoluteFill,
	Easing,
	interpolate,
	spring,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';
import {CARD} from './style.js';

// общий вход для любого элемента карточки
const useRise = (enterFrame, order) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const local = frame - enterFrame - Math.round(order * CARD.stagger * fps);
	const appear = spring({
		frame: local,
		fps,
		config: {damping: 15, stiffness: 180, mass: 0.6},
	});
	return {
		opacity: local < 0 ? 0 : appear,
		y: local < 0 ? 34 : interpolate(appear, [0, 1], [34, 0]),
	};
};

const Band = ({y, children, enterFrame, order}) => {
	const {height} = useVideoConfig();
	const rise = useRise(enterFrame, order);
	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				top: height * y,
				display: 'flex',
				justifyContent: 'center',
				opacity: rise.opacity,
				transform: `translateY(${rise.y}px)`,
			}}
		>
			{children}
		</div>
	);
};

const gradientText = (gradient) => ({
	backgroundImage: gradient,
	WebkitBackgroundClip: 'text',
	backgroundClip: 'text',
	WebkitTextFillColor: 'transparent',
	color: 'transparent',
});

const Label = ({text, enterFrame}) => (
	<Band y={CARD.label.y} enterFrame={enterFrame} order={0}>
		<span
			style={{
				fontFamily: CARD.label.font,
				fontWeight: CARD.label.weight,
				fontSize: CARD.label.size,
				letterSpacing: CARD.label.tracking,
				color: CARD.label.color,
			}}
		>
			{text}
		</span>
	</Band>
);

const Stat = ({card, enterFrame, progress}) => {
	const frame = useCurrentFrame();
	const {fps} = useVideoConfig();
	const local = frame - enterFrame - Math.round(CARD.stagger * fps);

	// цифра не появляется, а прилетает штампом
	const stamp = spring({
		frame: local,
		fps,
		config: {damping: 11, stiffness: 200, mass: 0.8},
	});
	const scale = interpolate(stamp, [0, 1], [CARD.stat.stampFrom, 1]);

	// счётчик: рост ставки лучше показать, чем написать
	const counted = interpolate(local, [0, CARD.stat.countFrames], [0, 1], {
		easing: Easing.out(Easing.cubic),
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const text = card.count
		? Math.round(
				interpolate(counted, [0, 1], [card.count[0], card.count[1]])
			) + (card.suffix ?? '')
		: card.value;

	// блик проходит по цифре один раз за врезку
	const glare = interpolate(
		progress,
		[CARD.stat.glareAt, CARD.stat.glareAt + CARD.stat.glareSpan],
		[-120, 220],
		{extrapolateLeft: 'clamp', extrapolateRight: 'clamp'}
	);

	const type = {
		fontFamily: CARD.stat.font,
		fontWeight: CARD.stat.weight,
		fontSize: CARD.stat.size,
		lineHeight: 0.9,
		letterSpacing: '-0.02em',
	};

	return (
	<>
		<Band y={CARD.stat.y} enterFrame={enterFrame} order={1}>
			<span
				style={{
					position: 'relative',
					display: 'inline-block',
					transform: `scale(${local < 0 ? CARD.stat.stampFrom : scale})`,
					filter: 'drop-shadow(0 14px 40px rgba(0,0,0,0.5))',
				}}
			>
				<span
					style={{
						...type,
						...gradientText(card.alarm ? CARD.stat.alarm : CARD.stat.gradient),
					}}
				>
					{text}
				</span>
				<span
					aria-hidden
					style={{
						...type,
						position: 'absolute',
						left: 0,
						top: 0,
						...gradientText(
							`linear-gradient(102deg, transparent ${glare - 22}%, rgba(255,255,255,${CARD.stat.glare}) ${glare}%, transparent ${glare + 22}%)`
						),
					}}
				>
					{text}
				</span>
			</span>
		</Band>
		{card.caption ? (
			<Band y={CARD.caption.y} enterFrame={enterFrame} order={2}>
				<span
					style={{
						fontFamily: CARD.caption.font,
						fontWeight: CARD.caption.weight,
						fontSize: CARD.caption.size,
						color: CARD.caption.color,
					}}
				>
					{card.caption}
				</span>
			</Band>
		) : null}
	</>
	);
};

const Rows = ({card, enterFrame}) => {
	const {width, height} = useVideoConfig();
	return (
		<>
			{card.rows.map(([key, val], i) => (
				<Band
					key={key}
					y={CARD.row.y + (i * (CARD.row.size + CARD.row.gap * 2)) / height}
					enterFrame={enterFrame}
					order={i + 1}
				>
					<div
						style={{
							width: width * CARD.row.width,
							display: 'flex',
							justifyContent: 'space-between',
							alignItems: 'baseline',
							gap: 24,
							paddingBottom: CARD.row.gap,
							borderBottom: `2px solid ${CARD.row.rule}`,
							fontFamily: CARD.row.font,
							fontWeight: CARD.row.weight,
							fontSize: CARD.row.size,
						}}
					>
						<span style={{color: CARD.row.key}}>{key}</span>
						<span style={{color: CARD.row.val, whiteSpace: 'nowrap'}}>
							{val}
						</span>
					</div>
				</Band>
			))}
		</>
	);
};

const Tags = ({card, enterFrame}) => {
	const {width} = useVideoConfig();
	return (
		<Band y={CARD.tag.y} enterFrame={enterFrame} order={1}>
			<div
				style={{
					width: width * CARD.tag.width,
					display: 'flex',
					flexWrap: 'wrap',
					justifyContent: 'center',
					gap: CARD.tag.gap,
				}}
			>
				{card.tags.map((t) => (
					<span
						key={t}
						style={{
							fontFamily: CARD.tag.font,
							fontWeight: CARD.tag.weight,
							fontSize: CARD.tag.size,
							color: CARD.tag.color,
							background: CARD.tag.bg,
							border: `2px solid ${CARD.tag.border}`,
							borderRadius: CARD.tag.radius,
							padding: `${CARD.tag.padY}px ${CARD.tag.padX}px`,
						}}
					>
						{t}
					</span>
				))}
			</div>
		</Band>
	);
};

// Как врезка входит в кадр. Раньше вход был один на все ролики, и
// серьёзный разбор получал ту же расфокусировку, что дерзкий монтаж.
//
//   резко        мгновенно, без проявления — рубленый стык
//   свистом      влетает сбоку под звук пролёта
//   наплывом     выплывает из расфокуса, мягко
//   стоп-кадром  щёлкает, чуть увеличенная, и замирает
const ENTRY = {
	'резко': {fade: 0.04, blur: 0, slide: 0, from: 1},
	'свистом': {fade: 0.1, blur: 0.35, slide: 0.5, from: 1},
	'наплывом': {fade: 1, blur: 1, slide: 0, from: 1},
	'стоп-кадром': {fade: 0.06, blur: 0, slide: 0, from: 1.08},
};

export const BrollCard = ({shot, time, fromSeconds, manner}) => {
	const {fps, width} = useVideoConfig();
	const enterFrame = Math.round((shot.from - fromSeconds) * fps);
	const card = shot.card;

	const entry = ENTRY[manner?.brollIn] ?? ENTRY['наплывом'];

	// фон медленно наезжает, чтобы врезка не выглядела картинкой
	const progress = interpolate(time, [shot.from, shot.to], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	// Насколько мягко приходит — задаёт манера. При резком входе окно
	// проявления почти нулевое, и стык читается как рубленая склейка.
	const fadeIn = Math.max(0.02, CARD.fadeIn * entry.fade);

	const fade = Math.min(
		interpolate(time, [shot.from, shot.from + fadeIn], [0, 1], {
			extrapolateLeft: 'clamp',
			extrapolateRight: 'clamp',
		}),
		interpolate(time, [shot.to - CARD.fadeOut, shot.to], [1, 0], {
			extrapolateLeft: 'clamp',
			extrapolateRight: 'clamp',
		})
	);

	// врезка выплывает из расфокуса — тот же приём, что на склейке
	const focus = interpolate(time, [shot.from, shot.from + fadeIn], [1, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	// Влёт сбоку и щелчок стоп-кадра. Оба движения короткие: на врезке
	// в полторы секунды длинный заход съедает саму картинку.
	const slide = entry.slide
		? interpolate(focus, [0, 1], [0, width * 0.22 * entry.slide])
		: 0;
	const pop = entry.from !== 1 ? interpolate(focus, [0, 1], [1, entry.from]) : 1;

	return (
		<AbsoluteFill
			style={{
				overflow: 'hidden',
				opacity: fade,
				transform: slide || pop !== 1 ? `translateX(${slide}px) scale(${pop})` : undefined,
				filter:
					entry.blur && focus > 0.01
						? `blur(${focus * CARD.blurIn * entry.blur}px)`
						: 'none',
			}}
		>
			<AbsoluteFill
				style={{
					background: CARD.bg,
					transform: `scale(${1 + CARD.zoomIn * progress})`,
				}}
			/>
			<AbsoluteFill
				style={{
					backgroundImage: `repeating-linear-gradient(115deg, ${CARD.grain} 0 2px, transparent 2px 14px)`,
				}}
			/>

			<Label text={card.label} enterFrame={enterFrame} />
			{card.type === 'stat' ? (
				<Stat card={card} enterFrame={enterFrame} progress={progress} />
			) : null}
			{card.type === 'rows' ? <Rows card={card} enterFrame={enterFrame} /> : null}
			{card.type === 'tags' ? <Tags card={card} enterFrame={enterFrame} /> : null}
		</AbsoluteFill>
	);
};

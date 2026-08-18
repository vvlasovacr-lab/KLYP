// ВРЕЗКА УГЛОМ.
//
// Лицо остаётся во весь кадр, а в углу всплывает небольшая карточка —
// скриншот, запись экрана, доказательство.
//
// Зачем отдельно от обычной врезки: врезка во весь экран уводит от
// говорящего, и если её ставить на каждое упоминание, ролик рассыпается
// на слайд-шоу. Углом показывают то, что подтверждает слова, не отбирая
// внимания у самих слов, — в эталоне так показан профиль, пока человек
// продолжает говорить.
//
// Место — верхний угол: низ кадра занят субтитрами, а правый край —
// колонкой кнопок площадки.

import {
	AbsoluteFill,
	Img,
	OffthreadVideo,
	interpolate,
	spring,
	staticFile,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';
import {CORNER, SAFE} from './style.js';

// Скриншот или снимок документа показывают не проигрыванием, а наездом.
const STILL = /\.(jpe?g|png|webp|heic|heif)$/i;

export const CornerCard = ({shot, time, fromSeconds = 0}) => {
	const frame = useCurrentFrame();
	const {fps, width, height} = useVideoConfig();
	if (!shot) return null;

	const enter = Math.round((shot.from - fromSeconds) * fps);
	const local = frame - enter;

	const appear = spring({
		frame: local,
		fps,
		config: {damping: 20, stiffness: 220, mass: 0.6},
	});

	const leave = interpolate(time, [shot.to - CORNER.fade, shot.to], [1, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});

	const hidden = local < 0;
	const on = hidden ? 0 : Math.min(appear, leave);
	if (on <= 0.01) return null;

	const cardW = width * CORNER.width;
	const cardH = cardW * CORNER.ratio;

	// Въезжает сверху, из-за края кадра: карточка, проявляющаяся на
	// месте, читается как наклейка.
	const slide = interpolate(on, [0, 1], [-cardH * 0.6, 0]);

	return (
		<AbsoluteFill style={{pointerEvents: 'none'}}>
			<div
				style={{
					position: 'absolute',
					top: height * CORNER.top + slide,
					left: width * SAFE.side,
					width: cardW,
					height: cardH,
					borderRadius: CORNER.radius,
					overflow: 'hidden',
					opacity: on,
					transform: `scale(${interpolate(on, [0, 1], [0.9, 1])}) rotate(${CORNER.tilt}deg)`,
					boxShadow: CORNER.shadow,
					border: `${CORNER.border}px solid rgba(255,255,255,0.9)`,
					backgroundColor: '#000',
				}}
			>
				{/* Углом чаще всего показывают скриншот — то есть фото.
				    Оно тоже едет, иначе карточка выглядит наклейкой. */}
				{STILL.test(shot.file) ? (
					<Img
						src={staticFile(shot.own ? shot.file : `broll/${shot.file}`)}
						style={{
							width: '100%',
							height: '100%',
							objectFit: 'cover',
							transform: `scale(${interpolate(time, [shot.from, shot.to], [1.02, 1.1], {
								extrapolateLeft: 'clamp',
								extrapolateRight: 'clamp',
							})})`,
						}}
					/>
				) : (
					<OffthreadVideo
						src={staticFile(shot.own ? shot.file : `broll/${shot.file}`)}
						startFrom={0}
						muted
						style={{width: '100%', height: '100%', objectFit: 'cover'}}
					/>
				)}
			</div>
		</AbsoluteFill>
	);
};

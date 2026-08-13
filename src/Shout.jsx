import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SHOUT} from './style.js';

// Одно слово в кавычках во весь экран — призыв к действию.
export const Shout = ({shout, fromSeconds, look}) => {
	const frame = useCurrentFrame();
	const {fps, height} = useVideoConfig();

	// Выкрик берёт палитру и шрифт ролика: он часть того же оформления,
	// что и акценты в субтитрах.
	const gradient = look?.palette.accent ?? SHOUT.gradient;

	const enter = Math.round((shout.from - fromSeconds) * fps);
	const local = frame - enter;

	// всплывает с перелётом, потом чуть дышит — чтобы взгляд зацепился
	const appear = spring({
		frame: local,
		fps,
		config: {damping: 9, stiffness: 210, mass: 0.7},
	});
	const breathe =
		1 + SHOUT.breathe * Math.sin((local / fps) * 3.4) * Math.min(1, appear);

	const scale = interpolate(appear, [0, 1], [0.55, 1]) * breathe;
	const [open, close] = SHOUT.quotes;

	return (
		<div
			style={{
				position: 'absolute',
				left: 0,
				right: 0,
				top: height * SHOUT.anchorY,
				transform: 'translateY(-50%)',
				display: 'flex',
				justifyContent: 'center',
				filter:
					'drop-shadow(0 5px 12px rgba(0,0,0,0.6)) drop-shadow(0 18px 44px rgba(0,0,0,0.5))',
			}}
		>
			<span
				style={{
					fontFamily: look?.font.accent ?? SHOUT.font,
					fontWeight: SHOUT.weight,
					fontSize: SHOUT.size,
					letterSpacing: '-0.01em',
					transform: `scale(${scale}) rotate(${SHOUT.tilt}deg)`,
					opacity: appear,
					...(gradient
						? {
								backgroundImage: gradient,
								WebkitBackgroundClip: 'text',
								backgroundClip: 'text',
								WebkitTextFillColor: 'transparent',
								color: 'transparent',
							}
						: {color: SHOUT.color}),
				}}
			>
				{open}
				{shout.text}
				{close}
			</span>
		</div>
	);
};

// КАРТОЧКА-УТВЕРЖДЕНИЕ.
//
// Весь экран заливается цветом, на нём одно слово. Речь при этом не
// прерывается — прерывается картинка.
//
// Зачем: ролик, где сорок секунд подряд одно лицо, глаз перестаёт
// читать. В эталоне такую карточку ставят один-два раза, на переломе
// мысли, и она работает как вдох. Это не то же самое, что врезка:
// врезка показывает предмет разговора, а карточка не показывает ничего
// — она даёт паузу.
//
// Отличается и от выкрика: выкрик — крупное слово поверх видео, лицо
// остаётся. Здесь лица нет вовсе.

import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {SAFE, STATEMENT} from './style.js';

export const Statement = ({card, time, look}) => {
	useCurrentFrame();
	const {width, height} = useVideoConfig();
	if (!card) return null;

	const life = card.to - card.from;
	// Приход и уход резкие: карточка должна щёлкнуть, а не проявиться.
	// Мягкое появление читается как ошибка воспроизведения.
	const io = Math.min(STATEMENT.snap, life / 4);

	const appear = interpolate(time, [card.from, card.from + io], [0, 1], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const leave = interpolate(time, [card.to - io, card.to], [1, 0], {
		extrapolateLeft: 'clamp',
		extrapolateRight: 'clamp',
	});
	const on = Math.min(appear, leave);

	// Слово наезжает вместе с заливкой, но чуть медленнее — так читается
	// движение, а не мигание.
	const grow = interpolate(appear, [0, 1], [STATEMENT.from, 1]);

	const text = String(card.text ?? '').trim();
	if (!text) return null;

	// Кегль подбираем под длину: короткое слово идёт во весь экран,
	// длинное ужимается, чтобы не упереться в края.
	const room = width * (1 - SAFE.side * 2);
	const size = Math.min(STATEMENT.size, room / (text.length * 0.62));

	return (
		<AbsoluteFill
			style={{
				backgroundColor: look?.palette.card ?? STATEMENT.bg,
				opacity: on,
				display: 'flex',
				alignItems: 'center',
				justifyContent: 'center',
			}}
		>
			<span
				style={{
					fontFamily: look?.font.title ?? STATEMENT.font,
					fontWeight: STATEMENT.weight,
					fontSize: size,
					color: STATEMENT.ink,
					letterSpacing: '-0.015em',
					transform: `scale(${grow})`,
					// Слово стоит по центру видимой части кадра: справа
					// колонка кнопок площадки, и центр кадра — не центр
					// того, что видит зритель.
					marginLeft: (SAFE.centerX - 0.5) * width,
					maxWidth: room,
					textAlign: 'center',
					lineHeight: 1.05,
				}}
			>
				{text}
			</span>
		</AbsoluteFill>
	);
};

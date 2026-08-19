// ПЛАШКА.
//
// Первые секунды ролика: человек листает ленту и должен остановиться.
// Приходит она четырьмя способами — какой взять, решает модель под
// содержание. Раньше способ был один, и любой ролик начинался
// одинаково, отчего лента выглядела предсказуемой.
//
//   по-слову  строки собираются словами на глазах
//   целиком   появляется разом, жёстко — для дерзкого захода
//   печать    набирается буквами
//   выезд     выезжает сбоку одним куском

import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {SAFE, TITLE} from './style.js';
import {fitScale} from './fit.js';
import {MANNER} from './manner.js';

// Скорость набора в манере «печать». Медленнее — плашка не успевает
// дособраться до ухода; быстрее — набор не читается как набор.
const TYPE_PER_SEC = 26;

const Piece = ({piece, fit = 1, look, shown = null}) => {
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

	const full = cfg.uppercase ? String(piece.text).toUpperCase() : String(piece.text);
	// Набор буквами режем уже после приведения регистра — иначе счёт
	// знаков разойдётся с тем, что видно на экране.
	const text = shown === null ? full : <Typed text={full} shown={shown} grow={isBadge} />;

	// Пока до строки не дошла очередь, прячем её целиком.
	//
	// Раньше прозрачным становился только текст, а подложка бейджа
	// оставалась — и в кадре висел пустой чёрный прямоугольник поперёк
	// груди. Место под строку при этом сохраняется: без него плашка
	// прыгала бы по высоте на каждой букве.
	const waiting = shown === 0;

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
				// Ещё не набранная строка прячется вместе с подложкой.
				opacity: waiting ? 0 : 1,
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

// Как именно кусок плашки въезжает в кадр. Пружина у каждой манеры
// своя: мягкая для набора словами, тугая для жёсткого появления.
const SPRING = {
	'по-слову': {damping: 14, stiffness: 180, mass: 0.55},
	'целиком': {damping: 30, stiffness: 420, mass: 0.5},
	'выезд': {damping: 22, stiffness: 200, mass: 0.7},
	'печать': {damping: 30, stiffness: 420, mass: 0.5},
};

// Одно слово плашки. Всплывает со своей задержкой — заголовок
// набирается на глазах, а не выпрыгивает готовым куском.
const Rising = ({delay, fps, frame, mode = 'по-слову', width = 1080, children}) => {
	const local = frame - delay;
	const appear = spring({
		frame: local,
		fps,
		config: SPRING[mode] ?? SPRING['по-слову'],
	});

	const hidden = local < 0;
	const at = (from, to) => (hidden ? from : interpolate(appear, [0, 1], [from, to]));

	// Выезд идёт вбок и с запасом за край кадра: если начать у самой
	// границы, движение читается как подрагивание, а не как выезд.
	const shift =
		mode === 'выезд'
			? `translateX(${at(-width * 0.55, 0)}px)`
			: `translateY(${at(mode === 'целиком' ? 0 : 26, 0)}px)`;

	// Жёсткое появление приходит из чуть большего размера — так удар
	// читается сильнее, чем при росте из маленького.
	const scale = mode === 'целиком' ? at(1.14, 1) : mode === 'выезд' ? 1 : at(0.9, 1);

	return (
		<span
			style={{
				display: 'inline-block',
				transform: `${shift} scale(${scale})`,
				opacity: hidden ? 0 : appear,
				transformOrigin: 'center bottom',
			}}
		>
			{children}
		</span>
	);
};

// Набор буквами. Показываем столько знаков, сколько успело напечататься
// к этому кадру.
//
// У крупной строки ненабранный хвост остаётся на месте прозрачным: без
// него строка прыгала бы по ширине на каждой букве, а она широкая и
// прыжок заметен.
//
// У бейджа наоборот — хвост убираем совсем. Подложка у него цветная, и
// зарезервированная ширина выглядит как полоса в пустоту: набралось
// «НЕ», а красный прямоугольник тянется на весь экран. Бейдж короткий,
// поэтому растёт он незаметно.
const Typed = ({text, shown, grow = false}) => {
	const cut = Math.max(0, Math.min(text.length, shown));
	if (grow) return <>{text.slice(0, cut)}</>;

	return (
		<>
			{text.slice(0, cut)}
			<span style={{opacity: 0}}>{text.slice(cut)}</span>
		</>
	);
};

const Line = ({line, index, fps, frame, enterFrame, fit, look, from, mode, width, typedFrom}) => {
	// Слово за словом. Бейдж не дробим: у него общая подложка, и по словам
	// она рассыпалась бы на несколько плашек.
	let seen = from;
	let typed = typedFrom;

	// Шаг между словами есть только там, где плашка и правда собирается
	// словами. В остальных манерах всё приходит разом.
	const step = mode === 'по-слову' ? TITLE.wordStep : 0;

	const row = {
		marginTop: index === 0 ? 0 : TITLE.lineOverlap,
		display: 'flex',
		alignItems: 'center',
		justifyContent: 'center',
		gap: TITLE.wordGap,
		transform: `translateX(${line.dx}px)`,
	};

	// Набор буквами: слова не дробим и не анимируем поодиночке — вместо
	// этого показываем ровно столько знаков, сколько успело напечататься.
	if (mode === 'печать') {
		const done = Math.floor(((frame - enterFrame) / fps) * TYPE_PER_SEC);

		return (
			<div style={row}>
				{line.pieces.map((piece, i) => {
					const text = String(piece.text);
					const shown = done - typed;
					typed += text.length + 1;

					// Место под ещё не набранное держим занятым, но невидимым:
					// иначе строка прыгала бы по ширине на каждой букве.
					return (
						<Piece
							key={i}
							piece={piece}
							fit={fit}
							look={look}
							shown={Math.max(0, shown)}
						/>
					);
				})}
			</div>
		);
	}

	return (
		<div style={row}>
			{line.pieces.map((piece, i) => {
				if (piece.kind === 'badge') {
					const delay = enterFrame + Math.round(seen * step * fps);
					seen += 1;
					return (
						<Rising key={i} delay={delay} fps={fps} frame={frame} mode={mode} width={width}>
							<Piece piece={piece} fit={fit} look={look} />
						</Rising>
					);
				}

				const words = String(piece.text).split(/\s+/).filter(Boolean);
				return words.map((word, w) => {
					const delay = enterFrame + Math.round(seen * step * fps);
					seen += 1;
					return (
						<Rising
							key={`${i}-${w}`}
							delay={delay}
							fps={fps}
							frame={frame}
							mode={mode}
							width={width}
						>
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

// То же для набора буквами: следующая строка начинает печататься после
// предыдущей. Пробел между кусками тоже занимает свой такт.
const charsIn = (line) =>
	line.pieces.reduce((n, piece) => n + String(piece.text).length + 1, 0);

export const TitleCard = ({title, time, fromSeconds = 0, look, manner}) => {
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
					mode={manner?.titleIn ?? MANNER.titleIn}
					width={width}
					enterFrame={Math.round((T.in - fromSeconds) * fps)}
					from={T.lines.slice(0, i).reduce((n, l) => n + wordsIn(l), 0)}
					typedFrom={T.lines.slice(0, i).reduce((n, l) => n + charsIn(l), 0)}
				/>
			))}
		</div>
	);
};

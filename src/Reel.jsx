import {
	AbsoluteFill,
	Audio,
	Easing,
	OffthreadVideo,
	Sequence,
	interpolate,
	spring,
	staticFile,
	useCurrentFrame,
	useVideoConfig,
} from 'remotion';
import {useMemo} from 'react';
import {Fonts} from './fonts.jsx';
import {Subtitles} from './Subtitles.jsx';
import {TitleCard} from './TitleCard.jsx';
import {Shout} from './Shout.jsx';
import {BrollCard} from './BrollCard.jsx';
import {CornerCard} from './CornerCard.jsx';
import {Statement} from './Statement.jsx';
import {retime} from './retime.js';
import {readPlan} from './timeline.js';
import {CAMERA, CARD, CUT, TITLE} from './style.js';
import {SFX, buildCues} from './sfx.js';
import {MANNER, PACE, SOUND} from './manner.js';

// рывок кадра, вспышка и расфокус на стыке
const useCutEffect = (time, cutAt, force = 1) => {
	const {fps} = useVideoConfig();
	if (!CUT.on) return {punch: 1, flash: 0, tint: CUT.base, blur: 0};

	const cut = cutAt(time);
	const tint = CUT[cut?.kind] ?? CUT.base;
	const since = cut ? Math.round((time - cut.t) * fps) : Infinity;

	const punch =
		since < CUT.punchFrames
			? interpolate(since, [0, CUT.punchFrames], [1 + CUT.punch * force, 1], {
					easing: Easing.out(Easing.cubic),
					extrapolateRight: 'clamp',
				})
			: 1;

	const flash =
		since < CUT.flashFrames
			? interpolate(since, [0, CUT.flashFrames], [tint.alpha, 0], {
					easing: Easing.out(Easing.quad),
					extrapolateRight: 'clamp',
				})
			: 0;

	// расфокус на стыке: резкость наводится обратно за десяток кадров
	const depth = cut?.kind === 'broll' ? CUT.blurBroll : CUT.blur;
	const blur =
		since < CUT.blurFrames
			? interpolate(since, [0, CUT.blurFrames], [depth, 0], {
					easing: Easing.out(Easing.cubic),
					extrapolateRight: 'clamp',
				})
			: 0;

	return {punch, flash, tint, blur};
};

// медленный дрейф на всю длину + короткий наезд на каждом акценте
const useCameraZoom = (time, fromSeconds, accentStarts, force = 1) => {
	const frame = useCurrentFrame();
	const {fps, durationInFrames} = useVideoConfig();

	const drift = interpolate(frame, [0, durationInFrames], [0, CAMERA.drift], {
		extrapolateRight: 'clamp',
	});

	// важен только последний сработавший акцент
	const last = accentStarts
		.filter((s) => time >= s && time < s + CAMERA.settle)
		.pop();

	const settle = spring({
		frame: frame - Math.round(((last ?? 0) - fromSeconds) * fps),
		fps,
		config: {damping: 18, stiffness: 90, mass: 0.9},
	});
	const punch = last === undefined ? 0 : CAMERA.punch * force * (1 - settle);

	return CAMERA.on ? 1 + drift + punch : 1;
};

// ГОВОРЯЩИЙ В КАДРЕ.
//
// Движок вырезает паузы и слегка ускоряет вялые куски, поэтому выходное
// время больше не совпадает с исходным: тридцатая секунда ролика может быть
// тридцать четвёртой секундой съёмки. Каждый кусок ставится отдельным
// отрезком со своим startFrom и скоростью — стык получается незаметным,
// потому что режется он там, где человек молчал.
//
// Без плана речевого монтажа играем исходник как есть.
// Сколько кадров длится перекрытие на стыке кусков. Два кадра — около
// семидесяти миллисекунд: щелчка уже не слышно, а начало слова ещё не
// съедено.
const SPLICE = 2;

const Speaker = ({source, speech, fromSeconds, style}) => {
	const {fps, durationInFrames} = useVideoConfig();
	const file = staticFile(source || 'base.mp4');

	if (!speech?.length) {
		return (
			<OffthreadVideo
				src={file}
				startFrom={Math.round(fromSeconds * fps)}
				endAt={Math.round(fromSeconds * fps) + durationInFrames}
				style={style}
			/>
		);
	}

	return speech.map((part, i) => {
		const from = Math.round((part.at - fromSeconds) * fps);
		const length = Math.max(1, Math.round((part.until - part.at) * fps));
		if (from + length < 0 || from > durationInFrames) return null;

		// Стык встык слышен щелчком: волна обрывается на полуслове и
		// начинается с другого места. Поэтому кусок тянется на пару кадров
		// дальше своего конца и там затихает, а следующий за это же время
		// набирает громкость — звук переходит внахлёст, а не рубится.
		//
		// Картинка при этом режется ровно там, где и раньше: следующий
		// кусок рисуется поверх, а хвост предыдущего слышно, но не видно.
		const head = i > 0 ? SPLICE : 0;
		const tail = i < speech.length - 1 ? SPLICE : 0;

		const volume = (f) => {
			const rise = head ? Math.min(1, (f + 1) / head) : 1;
			const drop = tail ? Math.min(1, (length + tail - f) / tail) : 1;
			return Math.max(0, Math.min(rise, drop));
		};

		return (
			<Sequence key={i} from={from} durationInFrames={length + tail} layout="none">
				<AbsoluteFill style={{overflow: 'hidden'}}>
					<OffthreadVideo
						src={file}
						startFrom={Math.round(part.from * fps)}
						endAt={Math.round(part.to * fps) + tail}
						playbackRate={part.speed}
						volume={volume}
						style={style}
					/>
				</AbsoluteFill>
			</Sequence>
		);
	});
};

export const Reel = ({chunks, plan, speech, source, music = null, fromSeconds = 0}) => {
	const frame = useCurrentFrame();
	const {fps, durationInFrames} = useVideoConfig();

	// Разметка приходит извне: у каждого ролика она своя.
	// Без плана берётся образцовая — так студия открывается как раньше.
	const tl = useMemo(() => readPlan(plan), [plan]);

	// Почерк этого ролика: манера субтитров, приход плашки, темп, вход
	// врезок, плотность звука. Приходит из плана — выбирать его здесь
	// нельзя, рендер обязан быть повторяемым.
	const manner = plan?.manner ?? MANNER;
	const tempo = plan?.tempo ?? PACE[manner.pace] ?? PACE['ровно'];

	const cues = useMemo(
		() => buildCues({...tl.raw, sound: SOUND[manner.sound] ?? 1}),
		[tl, manner.sound]
	);

	const time = fromSeconds + frame / fps;
	const zoom = useCameraZoom(time, fromSeconds, tl.accentStarts, tempo.zoom);
	const {punch, flash, tint, blur} = useCutEffect(time, tl.cutAt, tempo.punch);

	// Реплики от движка уже разбиты по смыслу и проверены на слепые зоны —
	// пересобирать их своим ретаймом значило бы ломать чужую работу.
	// Своя пересборка нужна только сырой расшифровке.
	const lines = useMemo(
		() => (speech?.length ? chunks : retime(chunks)),
		[chunks, speech]
	);

	// Оформление этого ролика: палитра, раскладка, шрифт. Приходит из плана,
	// а не выбирается здесь — рендер обязан быть повторяемым.
	const look = plan?.look ?? null;

	// Плашки может не быть вовсе: модель решает, открывать ролик
	// заголовком или сразу голосом. Подставлять сюда образец из кода
	// нельзя — в кадре окажется чужой текст про кредитку.
	// Настоящий план пришёл без плашки — значит её и не должно быть.
	// Образец из кода показываем только когда плана нет вовсе: это
	// открытая студия, а не заказ клиента.
	const title = tl.title ?? (plan && typeof plan === 'object' ? null : TITLE);
	const titleOnScreen = Boolean(title) && time >= title.in && time < title.out;
	const shout = tl.shoutAt(time);

	// Врезка бывает двух видов. Во весь экран — уводит от говорящего,
	// показывает предмет разговора. Углом — лицо остаётся, в углу
	// всплывает доказательство. Какую взять, решила модель.
	const insert = tl.brollAt(time);
	const broll = insert && insert.where !== 'угол' ? insert : null;
	const corner = insert && insert.where === 'угол' ? insert : null;

	// Карточка-утверждение перекрывает всё: она и есть картинка.
	const statement = tl.statementAt?.(time) ?? null;

	// живая врезка входит и уходит так же мягко, как графическая
	const brollFade = broll
		? Math.min(
				interpolate(time, [broll.from, broll.from + CARD.fadeIn], [0, 1], {
					extrapolateLeft: 'clamp',
					extrapolateRight: 'clamp',
				}),
				interpolate(time, [broll.to - CARD.fadeOut, broll.to], [1, 0], {
					extrapolateLeft: 'clamp',
					extrapolateRight: 'clamp',
				})
			)
		: 0;
	const brollBlur = broll
		? interpolate(time, [broll.from, broll.from + CARD.fadeIn], [CARD.blurIn, 0], {
				extrapolateLeft: 'clamp',
				extrapolateRight: 'clamp',
			})
		: 0;

	return (
		<AbsoluteFill style={{backgroundColor: '#000'}}>
			<Fonts />

			<AbsoluteFill style={{overflow: 'hidden'}}>
				<Speaker
					source={source}
					speech={speech}
					fromSeconds={fromSeconds}
					style={{
						width: '100%',
						height: '100%',
						objectFit: 'cover',
						transform: `scale(${zoom * punch * (broll?.zoom ?? 1)})`,
						filter: blur > 0.1 ? `blur(${blur}px)` : 'none',
					}}
				/>
			</AbsoluteFill>

			{/* перебивка перекрывает базу целиком: свой файл либо карточка */}
			{broll?.file ? (
				// Sequence сдвигает отсчёт: клип начинается со входа врезки,
				// а не с нуля таймлайна — иначе короткий файл кончится раньше
				<Sequence
					from={Math.round((broll.from - fromSeconds) * fps)}
					durationInFrames={Math.ceil((broll.to - broll.from) * fps)}
					layout="none"
				>
					<AbsoluteFill style={{overflow: 'hidden', opacity: brollFade}}>
						<OffthreadVideo
							/* Своя врезка клиента лежит рядом с исходником, наша —
							   в библиотеке. Отличаем по метке, а не по имени файла:
							   клиент может назвать свой клип как угодно. */
							src={staticFile(broll.own ? broll.file : `broll/${broll.file}`)}
							startFrom={Math.round((broll.startFrom ?? 0) * fps)}
							style={{
								width: '100%',
								height: '100%',
								objectFit: 'cover',
								transform: `scale(${punch})`,
								filter: brollBlur > 0.1 ? `blur(${brollBlur}px)` : 'none',
							}}
							muted
						/>
					</AbsoluteFill>
				</Sequence>
			) : broll?.card ? (
				<BrollCard shot={broll} time={time} fromSeconds={fromSeconds} manner={manner} />
			) : null}

			{/* Врезка углом: лицо остаётся, доказательство всплывает
			    сверху. Идёт поверх видео, но под текстом. */}
			<CornerCard shot={corner} time={time} fromSeconds={fromSeconds} />

			{flash > 0 ? (
				<AbsoluteFill style={{backgroundColor: `rgba(${tint.rgb},${flash})`}} />
			) : null}

			{/* Своя музыка клиента: тихо, под голосом. Громче делать нельзя —
			    речь в рилсе главное, а фон только держит темп. */}
			{music ? (
				<Audio src={staticFile(music.file)} volume={music.volume ?? 0.16} loop />
			) : null}

			{SFX.on
				? cues.map((cue, i) => {
						const at = Math.round((cue.at - fromSeconds) * fps);
						if (at + 30 < 0 || at > durationInFrames) return null;
						return (
							<Sequence key={i} from={at} durationInFrames={30}>
								<Audio
									src={staticFile(`sfx/${cue.name}.wav`)}
									volume={cue.volume * SFX.master}
								/>
							</Sequence>
						);
					})
				: null}

			{/* Карточка-утверждение закрывает собой всё: и лицо, и текст.
			    Она и есть картинка на эти секунды. */}
			<Statement card={statement} time={time} look={look} />

			{/* плашка и выкрик перебивают обычные титры — иначе текст дублируется */}
			{statement ? null : titleOnScreen ? (
				<TitleCard title={title} time={time} fromSeconds={fromSeconds} look={look} manner={manner} />
			) : shout ? (
				<Shout shout={shout} fromSeconds={fromSeconds} look={look} />
			) : (
				<Subtitles
					chunks={lines}
					time={time}
					fromSeconds={fromSeconds}
					isAccent={tl.isAccent}
					isQuiet={tl.isQuiet}
					onCard={Boolean(tl.brollAt)}
					brollAt={tl.brollAt}
					look={look}
					manner={manner}
				/>
			)}
		</AbsoluteFill>
	);
};

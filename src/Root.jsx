import {Composition} from 'remotion';
import {Reel} from './Reel.jsx';
import {demoPlan} from './timeline.js';
import chunks from './chunks.json';

const FPS = 30;
const DEMO_SECONDS = 50.4;

// Длительность у каждого ролика своя и приходит вместе с пропсами.
// Без этого композиция была бы прибита к длине одного исходника.
const calculateMetadata = ({props}) => ({
	durationInFrames: Math.max(
		1,
		Math.round((Number(props.durationInSeconds) || DEMO_SECONDS) * FPS)
	),
});

export const RemotionRoot = () => {
	return (
		<>
			{/* Рабочая композиция: и студия, и рендер идут через неё.
			    В студии план не передан, поэтому берётся образцовый. */}
			<Composition
				id="Full"
				component={Reel}
				durationInFrames={Math.round(DEMO_SECONDS * FPS)}
				calculateMetadata={calculateMetadata}
				fps={FPS}
				width={1080}
				height={1920}
				defaultProps={{
					chunks,
					plan: demoPlan,
					speech: null,
					source: null,
					fromSeconds: 0,
					durationInSeconds: DEMO_SECONDS,
				}}
			/>

			{/* Короткий кусок — чтобы быстро посмотреть стиль, не ожидая
			    полного рендера. */}
			<Composition
				id="Demo"
				component={Reel}
				durationInFrames={10 * FPS}
				fps={FPS}
				width={1080}
				height={1920}
				defaultProps={{
					chunks,
					plan: demoPlan,
					speech: null,
					source: null,
					fromSeconds: 0,
					durationInSeconds: 10,
				}}
			/>
		</>
	);
};

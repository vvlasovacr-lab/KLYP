import React from 'react';
import {Audio, Sequence, staticFile, useVideoConfig} from 'remotion';

const speechEnvelope = (time, words) => {
  let activity = 0;
  for (const word of words) {
    const start = Number(word.start) - 0.10;
    const end = Number(word.end) + 0.16;
    if (time >= start && time <= end) return 1;
    if (time >= start - 0.14 && time < start) activity = Math.max(activity, 1 - (start - time) / 0.14);
    if (time > end && time <= end + 0.28) activity = Math.max(activity, 1 - (time - end) / 0.28);
  }
  return Math.max(0, Math.min(1, activity));
};

export const BackgroundMusic = ({music, scenes, duration}) => {
  const {fps} = useVideoConfig();
  if (!music?.enabled || !music.src) return null;
  const words = (scenes || []).flatMap((scene) => scene.words || []);
  const durationFrames = Math.max(1, Math.ceil(duration * fps));
  const baseVolume = Math.max(0, Math.min(0.5, Number(music.volume ?? 0.18)));
  const ducking = Math.max(0, Math.min(0.95, Number(music.ducking ?? 0.65)));
  const fadeIn = Math.max(0.05, Number(music.fadeIn ?? 0.8));
  const fadeOut = Math.max(0.05, Number(music.fadeOut ?? 1.0));
  return (
    <Sequence from={0} durationInFrames={durationFrames}>
      <Audio
        src={staticFile(music.src)}
        loop
        volume={(frame) => {
          const time = frame / fps;
          const activity = speechEnvelope(time, words);
          const intro = Math.min(1, time / fadeIn);
          const outro = Math.min(1, Math.max(0, duration - time) / fadeOut);
          return baseVolume * (1 - activity * ducking) * Math.min(intro, outro);
        }}
      />
    </Sequence>
  );
};

import React from 'react';
import {Audio, Sequence, interpolate, staticFile, useVideoConfig} from 'remotion';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

export const SfxTrack = ({events}) => {
  const {fps} = useVideoConfig();
  return (events || []).filter((event) => event.enabled !== false && event.src).map((event, index) => {
    const duration = Math.max(1, Math.round(Number(event.duration || 0.5) * fps));
    const fadeIn = Math.max(1, Math.round(Number(event.fade_in || 0.01) * fps));
    const fadeOut = Math.max(1, Math.round(Number(event.fade_out || 0.06) * fps));
    const volume = Math.max(0, Math.min(1, Number(event.volume ?? event.intensity ?? 0.7)));
    return <Sequence key={`sfx-${index}`} from={Math.max(0, Math.round(event.time * fps))} durationInFrames={duration}>
      <Audio src={staticFile(event.src)} volume={(frame) => volume * Math.min(
        interpolate(frame, [0, fadeIn], [0, 1], clamp),
        interpolate(frame, [Math.max(0, duration - fadeOut), duration], [1, 0], clamp),
      )} />
    </Sequence>;
  });
};

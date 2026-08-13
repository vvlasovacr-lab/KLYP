import React from 'react';
import {AbsoluteFill, interpolate, Sequence, useCurrentFrame, useVideoConfig} from 'remotion';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

const Flash = ({event, durationInFrames}) => {
  const frame = useCurrentFrame();
  const peak = Number(event.flash || 0);
  const opacity = interpolate(frame, [0, Math.max(1, durationInFrames * 0.18), durationInFrames], [0, peak, 0], clamp);
  return <AbsoluteFill style={{background: 'linear-gradient(115deg, rgba(255,255,255,.9), rgba(255,226,153,.72))', opacity, mixBlendMode: 'screen', pointerEvents: 'none'}} />;
};

export const HybridTransitionEffects = ({events = []}) => {
  const {fps} = useVideoConfig();
  return events.filter((event) => Number(event.flash || 0) > 0).map((event, index) => {
    const from = Math.max(0, Math.round(Number(event.time || 0) * fps));
    const duration = Math.max(2, Math.round(Number(event.duration || 0.2) * fps));
    return <Sequence key={`hybrid-flash-${index}`} from={from} durationInFrames={duration}><Flash event={event} durationInFrames={duration} /></Sequence>;
  });
};

import React from 'react';
import {interpolate, OffthreadVideo, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

const BrollShot = ({shot, durationInFrames, presentation}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const hybridFade = presentation ? Math.max(2, Math.round(fps * Number(presentation.fadeSeconds || 0.16))) : 0;
  const transitionFrames = presentation
    ? Math.min(Math.floor(durationInFrames / 3), hybridFade)
    : String(shot.transition || 'CUT').toUpperCase() === 'FADE' ? Math.min(5, Math.round(fps * 0.14)) : 0;
  const opacity = transitionFrames > 0
    ? interpolate(frame, [0, transitionFrames, durationInFrames - transitionFrames, durationInFrames], [0, 1, 1, 0], clamp)
    : 1;
  const motion = String(shot.motion || '').toUpperCase();
  const baseScale = Number(presentation?.baseScale || 1.025);
  const zoomScale = Number(presentation?.zoomScale || 1.035);
  const scale = motion === 'SUBTLE_ZOOM' || presentation ? interpolate(frame, [0, durationInFrames], [baseScale, zoomScale], clamp) : baseScale;
  const translateX = motion === 'PAN_LEFT'
    ? interpolate(frame, [0, durationInFrames], [1.8, -1.8], clamp)
    : motion === 'PAN_RIGHT'
      ? interpolate(frame, [0, durationInFrames], [-1.8, 1.8], clamp)
      : 0;
  const entryBlur = Number(presentation?.entryBlur || 0);
  const exitBlur = Number(presentation?.exitBlur || 0);
  const blur = transitionFrames > 0
    ? Math.max(
      interpolate(frame, [0, transitionFrames], [entryBlur, 0], clamp),
      interpolate(frame, [durationInFrames - transitionFrames, durationInFrames], [0, exitBlur], clamp),
    ) : 0;
  return <OffthreadVideo
    src={staticFile(shot.src)}
    startFrom={Math.max(0, Math.round((shot.startFrom || 0) * fps))}
    playbackRate={1}
    muted
    style={{
      position: 'absolute', inset: 0, width: '100%', height: '100%',
      objectFit: shot.fit || 'cover', objectPosition: shot.objectPosition || '50% 50%',
      opacity, filter: blur > 0.01 ? `blur(${blur}px)` : 'none',
      transform: `translateX(${translateX}%) scale(${scale})`, transformOrigin: shot.objectPosition || '50% 50%',
    }}
  />;
};

export const BrollLayer = ({events, presentation = null}) => {
  const {fps} = useVideoConfig();
  return (events || []).filter((event) => event.enabled !== false).map((event, index) => {
    const from = Math.max(0, Math.round(event.from * fps));
    const duration = Math.max(1, Math.round((event.to - event.from) * fps));
    const shots = event.shots || (event.src ? [event] : []);
    let cursor = 0;
    return <Sequence key={`broll-${index}`} from={from} durationInFrames={duration}>
      {shots.filter((shot) => shot.src).map((shot, shotIndex) => {
        const shotFrames = Math.max(1, Math.round((shot.duration || 1) * fps));
        const shotFrom = cursor;
        cursor += shotFrames;
        return <Sequence key={`shot-${shotIndex}`} from={shotFrom} durationInFrames={shotFrames}>
          <BrollShot shot={shot} durationInFrames={shotFrames} presentation={presentation} />
        </Sequence>;
      })}
    </Sequence>;
  });
};

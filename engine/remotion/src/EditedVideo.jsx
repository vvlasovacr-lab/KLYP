import React from 'react';
import {OffthreadVideo, Sequence, staticFile, useVideoConfig} from 'remotion';

const videoStyle = {position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'};

export const EditedVideo = ({sourceVideo, speechEdit, audioPlan}) => {
  const {fps} = useVideoConfig();
  const source = staticFile(sourceVideo.src);
  const timeline = speechEdit?.timeline || [];
  if (!timeline.length) return <OffthreadVideo src={source} style={videoStyle} />;
  return timeline.map((segment, index) => {
    const from = Math.max(0, Math.round(segment.output_start * fps));
    const duration = Math.max(1, Math.round((segment.output_end - segment.output_start) * fps));
    const hardCutIn = String(segment.transition || '').toUpperCase() === 'JUMP_CUT';
    const hardCutOut = String(timeline[index + 1]?.transition || '').toUpperCase() === 'JUMP_CUT';
    return (
      <Sequence key={`edit-${index}`} from={from} durationInFrames={duration} premountFor={Math.min(fps, 12)}>
        <OffthreadVideo
          src={source}
          startFrom={Math.max(0, Math.round(segment.source_start * fps))}
          playbackRate={segment.speed || 1}
          volume={(localFrame) => {
            // Contiguous speed sections must not dip in volume: that short dip
            // was perceived as a momentary acceleration in previous renders.
            // Only real source jumps get a one-frame anti-click envelope.
            const fadeIn = hardCutIn && localFrame === 0 ? 0.72 : 1;
            const fadeOut = hardCutOut && localFrame >= duration - 1 ? 0.72 : 1;
            return Math.min(fadeIn, fadeOut) * Math.max(0.5, Math.min(1.5, Number(audioPlan?.voiceGain || 1)));
          }}
          style={videoStyle}
        />
      </Sequence>
    );
  });
};

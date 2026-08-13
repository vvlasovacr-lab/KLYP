import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';

export const VisualLook = ({profile = {}}) => {
  const frame = useCurrentFrame();
  const vignette = Math.max(0, Math.min(0.35, Number(profile.vignette || 0)));
  const grain = Math.max(0, Math.min(0.10, Number(profile.filmGrain || 0)));
  if (!vignette && !grain) return null;
  const grainShift = ((frame * 17) % 29) - 14;
  return <AbsoluteFill style={{pointerEvents: 'none', overflow: 'hidden'}}>
    {vignette ? <AbsoluteFill style={{background: `radial-gradient(circle at 50% 43%, transparent 42%, rgba(0,0,0,${vignette}) 100%)`}} /> : null}
    {grain ? <AbsoluteFill style={{opacity: grain, mixBlendMode: 'soft-light', transform: `translate(${grainShift}px, ${-grainShift / 2}px) scale(1.04)`, backgroundImage: 'repeating-radial-gradient(circle at 30% 40%, rgba(255,255,255,.45) 0 1px, rgba(0,0,0,.42) 1px 2px, transparent 2px 5px)', backgroundSize: '7px 7px'}} /> : null}
  </AbsoluteFill>;
};

import React from 'react';
import {interpolate, random, useCurrentFrame, useVideoConfig} from 'remotion';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

const trackedAnchor = (facePlan, anchor, time, polish = {}) => {
  const frames = facePlan?.cropKeyframes || [];
  if (!frames.length) return anchor || {x: 0.5, y: 0.42};
  const windowSize = Math.max(1, Math.round(Number(polish.camera_smoothing_window || 5)));
  const nearestIndex = frames.reduce((best, item, index) => (
    Math.abs(Number(item.time) - time) < Math.abs(Number(frames[best].time) - time) ? index : best
  ), 0);
  const half = Math.floor(windowSize / 2);
  const window = frames.slice(Math.max(0, nearestIndex - half), nearestIndex + half + 1);
  const smooth = window.reduce((value, item) => ({x: value.x + Number(item.x), y: value.y + Number(item.y)}), {x: 0, y: 0});
  const smoothed = {x: smooth.x / window.length, y: smooth.y / window.length};
  const baseline = anchor || {x: 0.5, y: 0.42};
  const deadZone = Math.max(0, Number(polish.camera_dead_zone || 0.014));
  if (Math.abs(smoothed.x - Number(baseline.x)) <= deadZone) smoothed.x = Number(baseline.x);
  if (Math.abs(smoothed.y - Number(baseline.y)) <= deadZone * 0.75) smoothed.y = Number(baseline.y);
  const afterIndex = frames.findIndex((item) => Number(item.time) >= time);
  if (afterIndex === -1 || afterIndex === 0) return smoothed;
  const before = frames[afterIndex - 1];
  const after = frames[afterIndex];
  const span = Math.max(0.001, Number(after.time) - Number(before.time));
  const progress = Math.max(0, Math.min(1, (time - Number(before.time)) / span));
  return {
    x: smoothed.x * 0.72 + (Number(before.x) + (Number(after.x) - Number(before.x)) * progress) * 0.28,
    y: smoothed.y * 0.72 + (Number(before.y) + (Number(after.y) - Number(before.y)) * progress) * 0.28,
  };
};

export const Camera = ({events, visualEvents = [], transitions = [], drift = 0, baseScale = 1, anchor, facePlan, visualProfile = {}, polishProfile = {}, children}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const calmDrift = Math.max(0, Number(drift)) < 0.006 ? 0 : Math.max(0, Number(drift));
  let scale = Math.max(1, baseScale) + calmDrift * (0.5 + 0.5 * Math.sin(frame / (fps * 2.8)));
  let x = Math.sin(frame / (fps * 3.6)) * 6 * Math.min(1, calmDrift / 0.01);
  let y = Math.cos(frame / (fps * 4.1)) * 3 * Math.min(1, calmDrift / 0.01);
  let filter = `contrast(${Number(visualProfile.contrast || 1)}) saturate(${Number(visualProfile.saturation || 1)}) brightness(${Number(visualProfile.brightness || 1)})`;
  let transitionBlur = 0;
  let activeAnchor = trackedAnchor(facePlan, anchor, frame / fps, polishProfile);

  for (const event of events) {
    const effect = String(event.effect || event.type || '').toUpperCase();
    const start = Math.round(event.time * fps);
    const activeDuration = Math.max(4, Math.round((event.duration || 0.8) * fps));
    const settleDuration = Math.max(2, Math.round(Number(event.settle_duration || 0.34) * fps));
    const duration = activeDuration + settleDuration;
    const local = frame - start;
    if (local < 0 || local > duration) continue;
    const strength = event.strength ?? event.intensity ?? 0.5;
    const movement = Math.max(0, Math.min(1, Number(event.movement || 0)));
    const movementArc = Math.sin(Math.PI * Math.max(0, Math.min(1, local / duration)));
    x += (Number(event.anchor?.x || activeAnchor.x) < 0.5 ? 1 : -1) * movementArc * movement * 4;
    y -= movementArc * movement * 1.8;
    if (event.anchor) {
      const anchorBlend = interpolate(local, [0, duration * 0.24, duration * 0.76, duration], [0, 1, 1, 0], clamp);
      activeAnchor = {
        x: activeAnchor.x + (Number(event.anchor.x) - activeAnchor.x) * anchorBlend,
        y: activeAnchor.y + (Number(event.anchor.y) - activeAnchor.y) * anchorBlend,
      };
    }

    if (effect === 'SHAKE') {
      const decay = 1 - local / duration;
      const seed = String(event.id || event.segment_id || `${start}-${duration}`);
      x += (random(`${seed}-x-${local}`) - 0.5) * 12 * strength * decay;
      y += (random(`${seed}-y-${local}`) - 0.5) * 6 * strength * decay;
      continue;
    }

    const target = event.scale || (
      effect === 'PUNCH_ZOOM' ? 1.08 + strength * 0.04 :
      effect === 'SUBTLE_ZOOM' || effect === 'ZOOM' ? 1.03 + strength * 0.02 : 1
    );
    const attack = Math.max(2, Math.round(Number(event.attack_duration || event.duration * 0.30 || 0.22) * fps));
    const holdEnd = Math.max(attack + 1, activeDuration);
    const value = interpolate(
      local,
      [0, attack, holdEnd, duration],
      [1, target, target, Number(event.return_scale || 1)],
      clamp,
    );
    scale = Math.max(scale, value);
  }

  for (const event of visualEvents) {
    const type = String(event.type || '').toUpperCase();
    const start = Math.round(event.time * fps);
    const duration = Math.max(1, Math.round((event.duration || 0.2) * fps));
    const local = frame - start;
    if (local < 0 || local > duration || event.enabled === false) continue;
    if (type === 'MONOCHROME') filter = 'grayscale(1) contrast(1.12)';
    if (type === 'GLITCH') {
      const decay = 1 - local / duration;
      x += Math.sin(local * 7.3) * 14 * (event.intensity || 0.5) * decay;
      filter = `contrast(1.2) saturate(1.35) hue-rotate(${Math.sin(local * 3) * 14}deg)`;
    }
    if (type === 'BLUR_IMPACT') {
      const decay = 1 - local / duration;
      filter += ` blur(${Math.max(0, Number(event.intensity || 0.3) * 7 * decay)}px)`;
    }
  }

  for (const event of transitions) {
    const start = Math.round(Number(event.time || 0) * fps);
    const duration = Math.max(2, Math.round(Number(event.duration || 0.2) * fps));
    const local = frame - start;
    if (local < 0 || local > duration) continue;
    const progress = Math.max(0, Math.min(1, local / duration));
    const arc = Math.sin(Math.PI * progress);
    scale = Math.max(scale, 1 + Number(event.punch || 0) * arc);
    // A contained symmetric arc avoids the old one-sided blur tail:
    // stable frame -> brief semantic impact -> fully stable frame.
    transitionBlur = Math.max(transitionBlur, Number(event.blur || 0) * Math.sin(Math.PI * progress));
  }

  if (transitionBlur > 0.01) filter += ` blur(${transitionBlur}px)`;

  return (
    <div style={{position: 'absolute', inset: 0, transform: `translate(${x}px, ${y}px) scale(${scale})`, transformOrigin: `${(activeAnchor?.x || 0.5) * 100}% ${(activeAnchor?.y || 0.42) * 100}%`, filter}}>
      {children}
    </div>
  );
};

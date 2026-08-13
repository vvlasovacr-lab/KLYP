import {interpolate, random, spring} from 'remotion';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};
const stable = {scale: 1, x: 0, y: 0, rotate: 0, opacity: 1, brightness: 1};

export const motionPreset = ({
  preset = 'POP',
  frame,
  fps,
  intensity = 0.6,
  duration = 0.22,
  peakScale,
  definition = {},
}) => {
  if (frame < 0) return {...stable, opacity: 0, scale: 0.96};

  const name = String(preset).toUpperCase();
  const safeIntensity = Math.max(0, Math.min(1, intensity));
  const configuredDuration = Number(definition.duration || duration);
  const frames = Math.max(2, configuredDuration * fps);
  const progress = spring({
    frame,
    fps,
    durationInFrames: Math.ceil(frames),
    config: {
      damping: Number(definition.damping || 16 + (1 - safeIntensity) * 8),
      stiffness: Number(definition.stiffness || 190 + safeIntensity * 100),
      mass: Number(definition.mass || 0.55),
    },
  });
  const fade = interpolate(frame, [0, Math.min(4, frames)], [0, 1], clamp);
  const peak = peakScale || Number(definition.peakScale) || 1 + safeIntensity * 0.14;
  const startScale = Number(definition.startScale || 0);
  const offsetX = Number(definition.offset?.x || 0);
  const offsetY = Number(definition.offset?.y || 0);
  const settle = 1 - Math.min(1, frame / frames);
  const presets = {
    SOFT_POP: {scale: interpolate(progress, [0, 0.72, 1], [startScale || 0.96, Math.min(peak, 1.06), 1], clamp), x: 0, y: interpolate(progress, [0, 1], [offsetY || 4, 0], clamp), rotate: 0},
    HARD_POP: {scale: interpolate(progress, [0, 0.68, 1], [startScale || 0.82, Math.min(peak, 1.15), 1], clamp), x: 0, y: interpolate(progress, [0, 1], [offsetY || 8, 0], clamp), rotate: 0},
    IMPACT_SCALE: {scale: interpolate(progress, [0, 0.58, 1], [startScale || 0.78, Math.min(peak, 1.16), 1], clamp), x: 0, y: interpolate(progress, [0, 1], [offsetY || 5, 0], clamp), rotate: 0},
    SPRING_IN: {scale: interpolate(progress, [0, 0.78, 1], [startScale || 0.86, Math.min(peak, 1.09), 1], clamp), x: 0, y: interpolate(progress, [0, 1], [offsetY || 9, 0], clamp), rotate: 0},
    WORD_STAGGER: {scale: interpolate(progress, [0, 1], [startScale || 0.98, 1], clamp), x: 0, y: interpolate(progress, [0, 1], [offsetY || 6, 0], clamp), rotate: 0},
    SLIDE_SIDE: {scale: 1, x: interpolate(progress, [0, 1], [offsetX || 18, 0], clamp), y: 0, rotate: 0},
    BLUR_REVEAL: {scale: interpolate(progress, [0, 1], [startScale || 0.98, 1], clamp), x: 0, y: interpolate(progress, [0, 1], [offsetY || 4, 0], clamp), rotate: 0},
    CALM_REVEAL: {scale: interpolate(progress, [0, 1], [startScale || 0.98, 1], clamp), x: 0, y: interpolate(progress, [0, 1], [offsetY || 6, 0], clamp), rotate: 0},
    STAGGER: {scale: interpolate(progress, [0, 1], [startScale || 0.96, 1], clamp), x: interpolate(progress, [0, 1], [offsetX, 0], clamp), y: interpolate(progress, [0, 1], [offsetY || 9, 0], clamp), rotate: 0},
    POP: {scale: interpolate(progress, [0, 0.7, 1], [startScale || 0.84, peak, 1], clamp), x: 0, y: 0, rotate: 0},
    BOUNCE: {scale: interpolate(progress, [0, 0.65, 1], [startScale || 0.8, peak + 0.03, 1], clamp), x: 0, y: interpolate(progress, [0, 0.7, 1], [offsetY || 16, -5, 0], clamp), rotate: 0},
    SCALE_IN: {scale: interpolate(progress, [0, 1], [startScale || 0.78, 1], clamp), x: 0, y: 0, rotate: 0},
    SLIDE_UP: {scale: 1, x: 0, y: interpolate(progress, [0, 1], [offsetY || 20, 0], clamp), rotate: 0},
    SLIDE_LEFT: {scale: 1, x: interpolate(progress, [0, 1], [offsetX || 24, 0], clamp), y: 0, rotate: 0},
    SLIDE_RIGHT: {scale: 1, x: interpolate(progress, [0, 1], [-24, 0], clamp), y: 0, rotate: 0},
    SHAKE: {
      scale: 1,
      x: (random(`shortsai-shake-x-${Math.max(0, Math.floor(frame))}`) - 0.5) * 9 * safeIntensity * settle,
      y: (random(`shortsai-shake-y-${Math.max(0, Math.floor(frame))}`) - 0.5) * 5 * safeIntensity * settle,
      rotate: (random(`shortsai-shake-r-${Math.max(0, Math.floor(frame))}`) - 0.5) * 0.7 * safeIntensity * settle,
    },
    FLASH: {scale: interpolate(progress, [0, 0.45, 1], [0.96, peak, 1], clamp), x: 0, y: 0, rotate: 0, brightness: 1 + 0.2 * safeIntensity * settle},
    ROTATE: {scale: interpolate(progress, [0, 0.7, 1], [0.9, peak, 1], clamp), x: 0, y: 0, rotate: interpolate(progress, [0, 0.7, 1], [-7 * safeIntensity, 2 * safeIntensity, 0], clamp)},
    PUNCH: {scale: interpolate(progress, [0, 0.58, 1], [0.75, peakScale || 1.18, 1], clamp), x: 0, y: interpolate(progress, [0, 1], [10, 0], clamp), rotate: 0},
  };
  const blur = interpolate(frame, [0, Math.min(frames, 8)], [Number(definition.blur || 0), 0], clamp);
  return {...stable, ...(presets[name] || presets.POP), opacity: fade, blur};
};

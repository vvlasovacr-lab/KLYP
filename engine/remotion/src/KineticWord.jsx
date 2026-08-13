import React from 'react';
import {motionPreset} from './effects/motion';

export const KineticWord = ({
  item,
  scene,
  frame,
  fps,
  fontSize,
  emphasisSize,
  defaultColor,
  uppercase = false,
  margin = '0 9px',
  animateOrdinary = false,
  entryPreset = 'STAGGER',
  presetDefinitions = {},
}) => {
  const emphasized = item.role && item.role !== 'ordinary';
  const localFrame = frame - Math.round(((item.start ?? scene.start) - scene.start) * fps);
  const shouldAnimate = Boolean(item.effect) || animateOrdinary;
  const presetName = item.effect || entryPreset;
  const motion = shouldAnimate ? motionPreset({
    preset: presetName,
    frame: localFrame,
    fps,
    intensity: item.effect ? item.intensity ?? scene.motionIntensity ?? 0.6 : 0.2,
    duration: item.duration || (item.effect ? 0.24 : 0.16),
    peakScale: item.scale,
    definition: presetDefinitions?.[String(presetName).toUpperCase()] || {},
  }) : {scale: 1, x: 0, y: 0, rotate: 0, brightness: 1, opacity: 1};
  const text = uppercase ? String(item.word).toUpperCase() : item.word;
  return (
    <span style={{
      display: 'inline-block', margin,
      color: item.color || defaultColor,
      fontSize: emphasized ? emphasisSize : fontSize,
      opacity: motion.opacity,
      filter: `brightness(${motion.brightness}) blur(${motion.blur || 0}px)`,
      transform: `translate(${motion.x}px, ${motion.y}px) scale(${motion.scale}) rotate(${motion.rotate}deg)`,
      transformOrigin: 'center bottom',
      willChange: 'transform, opacity',
    }}>
      {text}
    </span>
  );
};

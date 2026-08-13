import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {motionPreset} from './effects/motion';
import {fontStack} from './fonts';
import {outlineShadow, scaledFont, sceneTextBox, typographyWeight} from './styles/text';

export const NumberScene = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const numberWord = (scene.words || []).find((word) => word.word === scene.number) || scene.words?.[0];
  const local = frame - Math.round(((numberWord?.start ?? scene.start) - scene.start) * fps);
  const motion = motionPreset({
    preset: numberWord?.effect || scene.animation || 'SCALE_IN', frame: local, fps,
    intensity: numberWord?.intensity ?? scene.motionIntensity ?? 0.8,
    peakScale: numberWord?.scale || 1.18,
    definition: styleConfig.motionPresets?.[String(numberWord?.effect || scene.animation || 'SCALE_IN').toUpperCase()] || {},
  });
  return (
    <div style={{...sceneTextBox(scene, styleConfig, 'lower'), flexDirection: 'column', textAlign: 'center'}}>
      <div style={{
        display: 'inline-block', padding: '10px 28px 14px', borderRadius: 10,
        fontFamily: fontStack(styleConfig, 'hero'), fontWeight: typographyWeight(styleConfig, 'hero'),
        fontSize: scaledFont(scene, styleConfig.fontSize.punch), color: '#101010',
        background: numberWord?.color || styleConfig.colors.accent,
        boxShadow: '0 10px 24px rgba(0,0,0,0.42)',
        letterSpacing: -2,
        opacity: motion.opacity, filter: `brightness(${motion.brightness})`,
        transform: `translate(${motion.x}px, ${motion.y}px) scale(${motion.scale}) rotate(${motion.rotate}deg)`,
      }}>{scene.number || scene.text}</div>
      {scene.label ? <div style={{
        marginTop: 18, fontFamily: fontStack(styleConfig, 'body'), fontWeight: styleConfig.font.weight,
        fontSize: scaledFont(scene, styleConfig.fontSize.normal), color: styleConfig.colors.text, lineHeight: 1,
        textTransform: 'uppercase', letterSpacing: -0.8, ...outlineShadow(styleConfig),
      }}>{scene.label}</div> : null}
    </div>
  );
};

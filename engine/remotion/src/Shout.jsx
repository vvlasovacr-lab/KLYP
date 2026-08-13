import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {motionPreset} from './effects/motion';
import {fontStack} from './fonts';
import {KineticWord} from './KineticWord';
import {outlineShadow, scaledFont, sceneTextBox} from './styles/text';
import {activeSceneWords} from './textLayout';

export const Shout = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const words = activeSceneWords(scene, scene.start + frame / fps);
  const motion = motionPreset({
    preset: scene.animation || 'PUNCH', frame, fps, intensity: scene.importance || 0.9,
    duration: 0.2 / (styleConfig.animationSpeed || 1), peakScale: scene.scale || 1.14,
    definition: styleConfig.motionPresets?.[String(scene.animation || 'PUNCH').toUpperCase()] || {},
  });
  return (
    <div style={{
      ...sceneTextBox(scene, styleConfig, 'center_lower'), flexWrap: 'wrap', textAlign: 'center', fontFamily: fontStack(styleConfig, 'punch'),
      fontWeight: styleConfig.font.weight, fontSize: scaledFont(scene, styleConfig.fontSize.punch), lineHeight: 0.92,
      color: scene.color || styleConfig.colors.accent, opacity: motion.opacity,
      transform: `translate(${motion.x}px, ${motion.y}px) scale(${motion.scale}) rotate(${motion.rotate}deg)`,
      ...outlineShadow(styleConfig),
    }}>
      {words.map((item) => <KineticWord
        key={`${item.word}-${item._index}`} item={item} scene={scene} frame={frame} fps={fps}
        fontSize={scaledFont(scene, styleConfig.fontSize.punch)} emphasisSize={scaledFont(scene, styleConfig.fontSize.punch)}
        defaultColor={scene.color || styleConfig.colors.accent} uppercase margin="0 6px" presetDefinitions={styleConfig.motionPresets}
      />)}
    </div>
  );
};

import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {motionPreset} from './effects/motion';
import {fontStack} from './fonts';
import {KineticWord} from './KineticWord';
import {outlineShadow, sceneTextBox, scaledFont} from './styles/text';
import {activeSceneWords} from './textLayout';

export const TitleCard = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const absoluteTime = scene.start + frame / fps;
  const words = activeSceneWords(scene, absoluteTime);
  const motion = motionPreset({
    preset: scene.animation || 'BOUNCE', frame, fps, intensity: scene.importance || 1,
    duration: 0.38 / (styleConfig.animationSpeed || 1), peakScale: scene.scale || 1.1,
    definition: styleConfig.motionPresets?.[String(scene.animation || 'BOUNCE').toUpperCase()] || {},
  });
  return (
    <div style={{
      ...sceneTextBox(scene, styleConfig, 'center_lower'), flexWrap: 'wrap', textAlign: 'center', fontFamily: fontStack(styleConfig, 'hero'),
      fontWeight: styleConfig.font.weight, fontSize: scaledFont(scene, styleConfig.fontSize.hero), lineHeight: 0.94,
      color: scene.color || styleConfig.colors.text, opacity: motion.opacity,
      transform: `translate(${motion.x}px, ${motion.y}px) scale(${motion.scale}) rotate(${motion.rotate}deg)`,
      ...outlineShadow(styleConfig),
    }}>
      {words.map((item) => <KineticWord
        key={`${item.word}-${item._index}`} item={item} scene={scene} frame={frame} fps={fps}
        fontSize={scaledFont(scene, styleConfig.fontSize.hero)} emphasisSize={scaledFont(scene, styleConfig.fontSize.hero)}
        defaultColor={scene.color || styleConfig.colors.text} uppercase animateOrdinary entryPreset="STAGGER" presetDefinitions={styleConfig.motionPresets}
      />)}
    </div>
  );
};

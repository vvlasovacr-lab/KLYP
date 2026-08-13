import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {motionPreset} from './effects/motion';
import {fontStack} from './fonts';
import {KineticWord} from './KineticWord';
import {activeSceneWords} from './textLayout';
import {outlineShadow, safeTextBox, scaledFont} from './styles/text';

export const Subtitles = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const absoluteTime = scene.start + frame / fps;
  const enter = motionPreset({
    preset: scene.animation || 'SLIDE_UP',
    frame,
    fps,
    intensity: Math.min(0.55, scene.importance || 0.4),
    duration: 0.28 / (styleConfig.animationSpeed || 1),
    definition: styleConfig.motionPresets?.[String(scene.animation || 'SLIDE_UP').toUpperCase()] || {},
  });
  const words = activeSceneWords(scene, absoluteTime);

  return (
    <div style={safeTextBox(styleConfig, scene)}>
      <div style={{
        maxWidth: 930,
        width: '100%', display: 'flex', flexWrap: 'wrap', justifyContent: scene.layout?.position === 'side_left' ? 'flex-start' : scene.layout?.position === 'side_right' ? 'flex-end' : 'center',
        alignItems: 'baseline', columnGap: 12, rowGap: 5,
        textAlign: scene.layout?.position === 'side_left' ? 'left' : scene.layout?.position === 'side_right' ? 'right' : 'center',
        fontFamily: fontStack(styleConfig, 'body'),
        fontWeight: styleConfig.font.weight,
        fontSize: scaledFont(scene, styleConfig.fontSize.normal),
        lineHeight: styleConfig.lineHeight,
        color: styleConfig.colors.text,
        opacity: enter.opacity,
        transform: `translate(${enter.x}px, ${enter.y}px) scale(${enter.scale})`,
        ...outlineShadow(styleConfig),
      }}>
        {words.map((item) => {
          const emphasized = item.role !== 'ordinary' || scene.emphasis?.includes(item._index);
          return <KineticWord
            key={`${item.word}-${item._index}`} item={item} scene={scene} frame={frame} fps={fps}
            fontSize={scaledFont(scene, styleConfig.fontSize.normal)} emphasisSize={scaledFont(scene, styleConfig.fontSize.accent)}
            defaultColor={emphasized ? styleConfig.colors.accent : styleConfig.colors.text}
            uppercase={emphasized} margin="0" animateOrdinary entryPreset="STAGGER" presetDefinitions={styleConfig.motionPresets}
          />;
        })}
      </div>
    </div>
  );
};

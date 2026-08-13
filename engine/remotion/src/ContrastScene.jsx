import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {motionPreset} from './effects/motion';
import {fontStack} from './fonts';
import {KineticWord} from './KineticWord';
import {outlineShadow, scaledFont, sceneTextBox, typographyWeight} from './styles/text';

export const ContrastScene = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const enter = motionPreset({preset: scene.animation || 'SLIDE_LEFT', frame, fps, intensity: scene.motionIntensity || 0.6, definition: styleConfig.motionPresets?.[String(scene.animation || 'SLIDE_LEFT').toUpperCase()] || {}});
  const marker = scene.contrast?.marker;
  const words = scene.words || [];
  const literalMarkerIndex = marker ? words.findIndex((word) => word.word === marker) : -1;
  const emphasisIndex = scene.emphasis?.[0] ?? words.findIndex((word) => word.role && word.role !== 'ordinary');
  const markerIndex = literalMarkerIndex > 0 ? literalMarkerIndex : emphasisIndex > 0 ? emphasisIndex : Math.ceil(words.length / 2);
  if (words.length < 2 || markerIndex <= 0 || markerIndex >= words.length) return null;
  const renderWords = (words, defaultColor) => words.map((item, index) => <KineticWord
    key={`${item.word}-${item.start}-${index}`} item={item} scene={scene} frame={frame} fps={fps}
    fontSize={scaledFont(scene, styleConfig.fontSize.normal)} emphasisSize={scaledFont(scene, styleConfig.fontSize.accent)}
    defaultColor={defaultColor} margin="0 5px" presetDefinitions={styleConfig.motionPresets}
  />);
  return (
    <div style={{
      ...sceneTextBox(scene, styleConfig, 'lower'), display: 'grid', width: '86%', gridTemplateColumns: '1fr auto 1fr',
      alignItems: 'center', gap: 18, textAlign: 'center', fontFamily: fontStack(styleConfig, 'display'),
      fontWeight: typographyWeight(styleConfig, 'display'), fontSize: scaledFont(scene, styleConfig.fontSize.normal), lineHeight: 0.98,
      opacity: enter.opacity, transform: `translate(${enter.x}px, ${enter.y}px) scale(${enter.scale})`,
      ...outlineShadow(styleConfig),
    }}>
      <div>{renderWords(words.slice(0, markerIndex), styleConfig.colors.text)}</div>
      <div style={{color: styleConfig.colors.danger}}>{literalMarkerIndex > 0 ? words[markerIndex].word : '→'}</div>
      <div>{renderWords(words.slice(literalMarkerIndex > 0 ? markerIndex + 1 : markerIndex), styleConfig.colors.accent)}</div>
    </div>
  );
};

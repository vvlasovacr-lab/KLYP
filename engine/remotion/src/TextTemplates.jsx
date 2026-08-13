import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {fontStack} from './fonts';
import {KineticWord} from './KineticWord';
import {outlineShadow, scaledFont, sceneTextBox, typographyProfile, typographyRole, typographyWeight} from './styles/text';

const Word = ({item, scene, frame, fps, styleConfig, size, emphasisSize, uppercase = false}) => (
  <KineticWord item={item} scene={scene} frame={frame} fps={fps} fontSize={size} emphasisSize={emphasisSize}
    defaultColor={styleConfig.colors.text} uppercase={uppercase} margin="0 7px" presetDefinitions={styleConfig.motionPresets} />
);

export const KeywordHero = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const index = scene.emphasis?.[0] ?? 0;
  const item = scene.words?.[index] || {word: scene.heroWord || scene.text, start: scene.start, role: 'strong_emphasis', color: styleConfig.colors.accent};
  return <div style={{...sceneTextBox(scene, styleConfig, 'center_lower'), textAlign: 'center', fontFamily: fontStack(styleConfig, 'punch'), fontWeight: styleConfig.font.weight, ...outlineShadow(styleConfig)}}>
    <Word item={item} scene={scene} frame={frame} fps={fps} styleConfig={styleConfig} size={scaledFont(scene, styleConfig.fontSize.punch)} emphasisSize={scaledFont(scene, styleConfig.fontSize.punch)} uppercase />
  </div>;
};

export const StackedText = ({scene, styleConfig}) => {
  const profileName = scene.layout?.compositionSafety?.font_profile || 'hero';
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const words = scene.words || [];
  const rows = [];
  for (let index = 0; index < words.length; index += 2) rows.push(words.slice(index, index + 2));
  return <div style={{...sceneTextBox(scene, styleConfig, 'center_lower'), flexDirection: 'column', textAlign: 'center', fontFamily: fontStack(styleConfig, profileName), fontWeight: typographyWeight(styleConfig, profileName), lineHeight: typographyProfile(styleConfig, profileName).lineHeight || 0.96, ...outlineShadow(styleConfig, profileName, scene)}}>
    {rows.map((row, rowIndex) => <div key={rowIndex}>{row.map((item, index) => <Word key={`${item.word}-${index}`} item={item} scene={scene} frame={frame} fps={fps} styleConfig={styleConfig} size={scaledFont(scene, styleConfig.fontSize.hero * 0.82)} emphasisSize={scaledFont(scene, styleConfig.fontSize.hero * 0.96)} uppercase />)}</div>)}
  </div>;
};

export const SideText = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const side = scene.layout?.position === 'side_right' ? 'right' : 'left';
  const words = scene.words || [];
  const explicit = scene.layout?.side_layout || scene.layout?.sideLayout;
  const maxWords = Number(styleConfig.layout?.sideMaxWords || 4);
  const valid = explicit?.valid !== false && words.length <= maxWords && Number(explicit?.estimated_lines || explicit?.estimatedLines || 2) <= Number(styleConfig.layout?.sideMaxLines || 2);
  const target = valid ? scene : {...scene, layout: {...(scene.layout || {}), position: 'center_lower'}};
  const body = typographyProfile(styleConfig, 'body');
  const role = typographyRole(styleConfig, scene.type || 'ACCENT');
  return <div style={{...sceneTextBox(target, styleConfig, valid ? `side_${side}` : 'center_lower'), flexWrap: 'wrap', textAlign: valid ? side : 'center', fontFamily: fontStack(styleConfig, 'body'), fontWeight: typographyWeight(styleConfig, 'body'), lineHeight: Number(role.lineHeight || body.lineHeight || 1), letterSpacing: Number(role.tracking ?? body.tracking ?? 0), ...outlineShadow(styleConfig, 'body', scene)}}>
    {words.map((item, index) => <Word key={`${item.word}-${index}`} item={item} scene={scene} frame={frame} fps={fps} styleConfig={styleConfig} size={scaledFont(scene, styleConfig.fontSize.normal)} emphasisSize={scaledFont(scene, styleConfig.fontSize.accent)} />)}
  </div>;
};

export const TopCaption = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return <div style={{...sceneTextBox(scene, styleConfig, 'top'), flexWrap: 'wrap', textAlign: 'center', fontFamily: fontStack(styleConfig, 'body'), fontWeight: typographyWeight(styleConfig, 'body'), lineHeight: 0.95, ...outlineShadow(styleConfig, 'body', scene)}}>
    {(scene.words || []).map((item, index) => <Word key={`${item.word}-${index}`} item={item} scene={scene} frame={frame} fps={fps} styleConfig={styleConfig} size={scaledFont(scene, styleConfig.fontSize.normal * 0.78)} emphasisSize={scaledFont(scene, styleConfig.fontSize.accent * 0.82)} uppercase />)}
  </div>;
};

export const QuoteCard = ({scene, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  return <div style={{...sceneTextBox(scene, styleConfig, 'lower'), padding: '28px 34px', borderLeft: `7px solid ${styleConfig.colors.accent}`, background: 'rgba(0,0,0,0.52)', borderRadius: 16, fontFamily: fontStack(styleConfig, 'body'), fontWeight: styleConfig.font.weight, fontSize: scaledFont(scene, styleConfig.fontSize.normal), lineHeight: 1.04, ...outlineShadow(styleConfig)}}>
    {(scene.words || []).map((item, index) => <Word key={`${item.word}-${index}`} item={item} scene={scene} frame={frame} fps={fps} styleConfig={styleConfig} size={scaledFont(scene, styleConfig.fontSize.normal)} emphasisSize={scaledFont(scene, styleConfig.fontSize.accent)} />)}
  </div>;
};

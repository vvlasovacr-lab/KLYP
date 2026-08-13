import React from 'react';
import {interpolate, spring, useCurrentFrame, useVideoConfig} from 'remotion';
import {fontStack} from './fonts';
import {motionPreset} from './effects/motion';
import {compositionScale, outlineShadow, scaledFont, sceneTextBox, typographyProfile, typographyRole, typographyWeight} from './styles/text';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

const safeScene = (scene) => {
  const safety = scene.layout?.compositionSafety;
  const position = safety?.valid === false ? (safety?.fallback_position || 'center_lower') : scene.layout?.position;
  return {...scene, layout: {...(scene.layout || {}), position: position || 'center_lower'}};
};

const measuredFont = (scene, fallback) => Number(scene.layout?.compositionSafety?.font_size || fallback);

const measuredWidth = (scene, fallback) => Number(scene.layout?.compositionSafety?.static_bounding_box_px?.w || fallback);

const lineGroups = (scene, words) => {
  const groups = scene.layout?.compositionSafety?.line_word_indices;
  if (!Array.isArray(groups) || !groups.length) return [words];
  return groups.map((indices) => indices.map((index) => words[index]).filter(Boolean)).filter((line) => line.length);
};

const hybridWord = ({item, scene, frame, fps, styleConfig, adapter, fontSize, component = 'PHRASE_BUILD'}) => {
  const emphasized = item.role !== 'ordinary' || (scene.emphasis || []).includes(item._index);
  const timed = component === 'PHRASE_BUILD' || (component === 'ACCENT_WORD' && emphasized);
  const wordStart = timed ? Math.round(((item.start ?? scene.start) - scene.start) * fps) : 0;
  const local = frame - wordStart;
  const sceneType = String(scene.type || scene.semanticRole || 'NORMAL').toUpperCase();
  const accentScene = ['ACCENT', 'HOOK', 'HERO', 'PUNCH', 'NUMBER', 'CONTRAST'].includes(sceneType);
  const preset = component === 'PHRASE_BUILD' ? 'WORD_STAGGER' : emphasized ? (item.effect || scene.animation || 'SOFT_POP') : 'CALM_REVEAL';
  const animate = component === 'PHRASE_BUILD' || (component === 'ACCENT_WORD' && emphasized);
  const motion = animate ? motionPreset({
    preset, frame: local, fps,
    intensity: emphasized ? Number(item.intensity ?? scene.motionIntensity ?? 0.55) : 0.16,
    duration: Number(item.duration || 0.18), peakScale: item.scale,
    definition: styleConfig.motionPresets?.[String(preset).toUpperCase()] || {},
  }) : {scale: 1, x: 0, y: 0, rotate: 0, opacity: 1, brightness: 1, blur: 0};
  const accentLimit = Number(adapter?.typography?.accentMaxScale || 1.34);
  const allowedScale = accentScene ? accentLimit : 1.08;
  const size = emphasized ? Math.min(fontSize * allowedScale, scaledFont(scene, styleConfig.fontSize.accent)) : fontSize;
  const dangerous = String(item.color || '').toLowerCase() === String(styleConfig.colors.danger || '').toLowerCase();
  const color = accentScene && emphasized ? (item.color || styleConfig.colors.accent) : styleConfig.colors.text;
  const gradient = accentScene && emphasized && styleConfig.colors.gradientAccents === true && adapter?.typography?.colors
    ? `linear-gradient(180deg, ${dangerous ? styleConfig.colors.danger : color} 0%, ${dangerous ? '#B91C1C' : '#F1B92F'} 100%)`
    : null;
  return (
    <span key={`${item.word}-${item._index}`} style={{
      display: 'inline-block',
      textAlign: 'center', fontSize: size, fontWeight: emphasized ? 900 : styleConfig.font.weight,
      color, opacity: motion.opacity,
      filter: `brightness(${motion.brightness || 1}) blur(${motion.blur || 0}px)`,
      transform: `translate(${motion.x || 0}px, ${motion.y || 0}px) scale(${motion.scale}) rotate(${motion.rotate || 0}deg)`, transformOrigin: 'center bottom',
      ...(gradient ? {backgroundImage: gradient, backgroundClip: 'text', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent'} : {}),
      willChange: 'transform, opacity',
    }}>{emphasized ? String(item.word).toUpperCase() : item.word}</span>
  );
};

const fadeOut = (frame, fps, scene) => {
  const duration = Math.max(1, Math.round((scene.end - scene.start) * fps));
  return interpolate(frame, [Math.max(0, duration - Math.round(fps * 0.12)), duration], [1, 0], clamp);
};

export const HybridSubtitles = ({scene, styleConfig, adapter}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const words = (scene.words || []).map((item, index) => ({...item, _index: index}));
  const roleName = String(scene.type || scene.semanticRole || 'NORMAL').toUpperCase();
  const role = typographyRole(styleConfig, roleName);
  const profileName = role.fontProfile || 'body';
  const profile = typographyProfile(styleConfig, profileName);
  const widthRatio = Number(role.maxWidth || profile.maxWidth || adapter?.typography?.maxWidth || 0.74);
  const maxWidth = measuredWidth(scene, width * widthRatio);
  const requestedSize = Number(styleConfig.fontSize[role.sizeKey || 'normal'] || styleConfig.fontSize.normal) * Number(role.scale || 1) * compositionScale(scene);
  const fontSize = measuredFont(scene, requestedSize);
  const target = safeScene(scene);
  const component = String(adapter?.sceneStyles?.[scene.actionId]?.component || scene.template || 'PHRASE_BUILD').toUpperCase();
  const outerPreset = component === 'NORMAL' || component === 'ACCENT_WORD' ? 'CALM_REVEAL' : null;
  const outer = outerPreset ? motionPreset({preset: outerPreset, frame, fps, intensity: 0.16, definition: styleConfig.motionPresets?.[outerPreset] || {}}) : {opacity: 1, scale: 1, x: 0, y: 0};
  const lines = lineGroups(scene, words);
  return (
    <div style={sceneTextBox(target, styleConfig, 'center_lower')}>
      <div style={{
        width: maxWidth, maxWidth: '100%',
        display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center',
        rowGap: 6, textAlign: 'center', transform: `translate(${outer.x || 0}px, ${outer.y || 0}px) scale(${outer.scale || 1})`,
        fontFamily: fontStack(styleConfig, profileName), fontWeight: typographyWeight(styleConfig, profileName),
        fontSize, lineHeight: Number(role.lineHeight || profile.lineHeight || styleConfig.lineHeight),
        letterSpacing: Number(role.tracking ?? profile.tracking ?? 0), color: styleConfig.colors.text,
        opacity: fadeOut(frame, fps, scene) * outer.opacity, ...outlineShadow(styleConfig, profileName, scene),
      }}>
        {lines.map((line, lineIndex) => <div key={`line-${lineIndex}`} style={{display: 'flex', justifyContent: 'center', alignItems: 'baseline', columnGap: 12, whiteSpace: 'nowrap'}}>
          {line.map((item) => hybridWord({item, scene, frame, fps, styleConfig, adapter, fontSize, component}))}
        </div>)}
      </div>
    </div>
  );
};

export const HybridTitleCard = ({scene, styleConfig, adapter}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  const words = (scene.words || []).map((item, index) => ({...item, _index: index}));
  const lines = lineGroups(scene, words);
  const roleName = String(scene.type || scene.semanticRole || 'HERO').toUpperCase();
  const role = typographyRole(styleConfig, roleName);
  const profileName = scene.layout?.compositionSafety?.font_profile || role.fontProfile || 'hero';
  const profile = typographyProfile(styleConfig, profileName);
  const widthRatio = Number(role.maxWidth || profile.maxWidth || 0.80);
  const fontSize = measuredFont(scene, styleConfig.fontSize.hero * Number(role.scale || 1) * compositionScale(scene));
  const target = safeScene(scene);
  return (
    <div style={{...sceneTextBox(target, styleConfig, 'center_lower'), flexDirection: 'column', textAlign: 'center', opacity: fadeOut(frame, fps, scene)}}>
      {lines.map((line, lineIndex) => {
        const delay = Math.round(lineIndex * fps * 0.055);
        const presetName = String(scene.animation || 'SPRING_IN').toUpperCase();
        const motion = motionPreset({preset: presetName, frame: frame - delay, fps, intensity: scene.motionIntensity || 0.72, definition: styleConfig.motionPresets?.[presetName] || {}});
        return <div key={`line-${lineIndex}`} style={{
          display: 'flex', flexWrap: 'wrap', justifyContent: 'center', alignItems: 'baseline', gap: 10,
          marginTop: lineIndex ? -8 : 0, padding: '2px 14px',
          fontFamily: fontStack(styleConfig, profileName), fontWeight: typographyWeight(styleConfig, profileName), fontSize,
          lineHeight: Number(role.lineHeight || profile.lineHeight || 0.92),
          letterSpacing: Number(role.tracking ?? profile.tracking ?? -1.2), color: styleConfig.colors.text,
          opacity: motion.opacity,
          transform: `translate(${motion.x}px, ${motion.y}px) scale(${motion.scale})`,
          ...outlineShadow(styleConfig, profileName, scene),
        }}>{line.map((item) => hybridWord({item, scene, frame, fps, styleConfig, adapter, fontSize, component: 'TITLE'}))}</div>;
      })}
    </div>
  );
};

export const HybridShout = ({scene, styleConfig, adapter}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const definition = styleConfig.typographyProfiles?.motion?.springs?.strong || adapter?.typography?.springs?.strong || {};
  const progress = spring({frame, fps, config: {damping: Number(definition.damping || 18), stiffness: Number(definition.stiffness || 255), mass: Number(definition.mass || 0.46)}});
  const target = safeScene(scene);
  return <div style={{
    ...sceneTextBox(target, styleConfig, 'center_lower'), justifyContent: 'center', textAlign: 'center',
    transform: `scale(${interpolate(progress, [0, 1], [0.78, 1], clamp)})`,
    opacity: fadeOut(frame, fps, scene), fontFamily: fontStack(styleConfig, 'punch'), fontWeight: 900,
    fontSize: measuredFont(scene, scaledFont(scene, styleConfig.fontSize.punch)), lineHeight: 0.9, color: styleConfig.colors.accent,
    ...outlineShadow(styleConfig, 'display', scene),
  }}>{String(scene.text || '').toUpperCase()}</div>;
};

export const HybridNumberScene = ({scene, styleConfig, adapter}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const definition = styleConfig.typographyProfiles?.motion?.springs?.strong || {};
  const progress = spring({frame, fps, config: {damping: Number(definition.damping || 18), stiffness: Number(definition.stiffness || 255), mass: Number(definition.mass || 0.46)}});
  const glare = interpolate(frame, [Math.round(fps * 0.10), Math.round(fps * 0.32)], [-130, 150], clamp);
  const target = safeScene(scene);
  const semanticNumber = (scene.words || []).find((item) => String(item.category || '').toLowerCase() === 'number');
  const numberText = scene.number || semanticNumber?.word || scene.text;
  const labelText = Object.prototype.hasOwnProperty.call(scene, 'label') ? scene.label : (semanticNumber
    ? (scene.words || []).filter((item) => item !== semanticNumber).map((item) => item.word).join(' ')
    : '');
  return <div style={{...sceneTextBox(target, styleConfig, 'center_lower'), flexDirection: 'column', textAlign: 'center', opacity: fadeOut(frame, fps, scene)}}>
    <div style={{
      position: 'relative', overflow: 'hidden', padding: '10px 30px 14px', borderRadius: 8,
      background: styleConfig.colors.accent, color: '#111', boxShadow: '0 12px 30px rgba(0,0,0,.46)',
      maxWidth: '100%', boxSizing: 'border-box',
      fontFamily: fontStack(styleConfig, 'hero'), fontWeight: typographyWeight(styleConfig, 'hero'), fontSize: measuredFont(scene, scaledFont(scene, styleConfig.fontSize.punch)),
      letterSpacing: Number(typographyRole(styleConfig, 'NUMBER').tracking ?? -2), transform: `rotate(-1.5deg) scale(${interpolate(progress, [0, 1], [0.72, 1], clamp)})`,
    }}>
      {numberText}
      <span style={{position: 'absolute', top: '-35%', bottom: '-35%', left: `${glare}%`, width: '24%', transform: 'skewX(-18deg)', background: 'linear-gradient(90deg, transparent, rgba(255,255,255,.58), transparent)'}} />
    </div>
    {labelText ? <div style={{maxWidth: '78%', marginTop: 14, fontFamily: fontStack(styleConfig, 'body'), fontWeight: typographyWeight(styleConfig, 'body'), fontSize: scaledFont(scene, styleConfig.fontSize.normal), lineHeight: typographyProfile(styleConfig, 'body').lineHeight || 1, color: styleConfig.colors.text, ...outlineShadow(styleConfig, 'body', scene)}}>{String(labelText).toUpperCase()}</div> : null}
  </div>;
};

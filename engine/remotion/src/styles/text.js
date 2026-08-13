export const typographyRole = (style, role = 'NORMAL') => {
  const roles = style.typographyProfiles?.roles || {};
  return roles[String(role || 'NORMAL').toUpperCase()] || roles.NORMAL || {};
};

export const typographyProfile = (style, name = 'body') => (
  style.typographyProfiles?.[name] || style.typographyProfiles?.body || {}
);

export const outlineShadow = (style, profileName = 'body', scene = null) => {
  const profile = typographyProfile(style, profileName);
  const shadow = profile.shadow || style.shadow;
  const measuredStroke = Number(scene?.layout?.compositionSafety?.stroke_px);
  const stroke = Number.isFinite(measuredStroke) ? measuredStroke : Number(profile.stroke ?? style.outline);
  return {
  WebkitTextStroke: `${stroke}px ${style.colors.outline}`,
  paintOrder: 'stroke fill',
  textShadow: `${shadow.x}px ${shadow.y}px ${shadow.blur}px ${style.colors.shadow}`,
  };
};

export const typographyWeight = (style, profileName = 'body') => (
  Number(typographyProfile(style, profileName).weight || style.font.weight || 800)
);

export const compositionScale = (scene) => {
  const value = Number(scene?.layout?.compositionSafety?.font_scale ?? 1);
  return Number.isFinite(value) ? Math.max(0.6, Math.min(1, value)) : 1;
};

export const scaledFont = (scene, value) => Number(value || 0) * compositionScale(scene);

export const sceneTextBox = (scene, style, fallback = 'lower') => {
  const position = scene?.layout?.position || fallback;
  const base = {position: 'absolute', display: 'flex', pointerEvents: 'none'};
  const safety = scene?.layout?.compositionSafety;
  const box = safety?.bounding_box;
  if (box) return {...base, left: `${Number(box.x) * 100}%`, top: `${Number(box.y) * 100}%`, width: `${Number(box.w) * 100}%`, height: `${Number(box.h) * 100}%`, alignItems: 'center', justifyContent: position === 'side_left' ? 'flex-start' : position === 'side_right' ? 'flex-end' : 'center'};
  const horizontal = Number(style?.safeZone?.horizontal || 104);
  const left = Number(style?.safeZone?.left || horizontal);
  const right = Number(style?.safeZone?.right || horizontal);
  if (position === 'top') return {...base, left, right, top: '8%', height: '22%', alignItems: 'center', justifyContent: 'center'};
  if (position === 'side_left') return {...base, left, width: '34%', top: '34%', height: '34%', alignItems: 'center', justifyContent: 'flex-start'};
  if (position === 'side_right') return {...base, right, width: '34%', top: '34%', height: '34%', alignItems: 'center', justifyContent: 'flex-end'};
  if (position === 'center') return {...base, left, right, top: '43%', height: '25%', alignItems: 'center', justifyContent: 'center'};
  if (position === 'center_lower') return {...base, left, right, top: '54%', height: '24%', alignItems: 'center', justifyContent: 'center'};
  return {...base, left, right, top: '61%', height: '21%', alignItems: 'center', justifyContent: 'center'};
};

export const safeTextBox = (style, scene) => sceneTextBox(scene, style, 'lower');

import React from 'react';
import {AbsoluteFill, Img, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {fontStack} from './fonts';
import {outlineShadow} from './styles/text';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};

const VisualEvent = ({event, styleConfig}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const type = String(event.type || event.effect || '').toUpperCase();
  const duration = Math.max(2, (event.duration || 0.2) * fps);
  if (type === 'FLASH') {
    const opacity = interpolate(frame, [0, duration * 0.22, duration], [0, 0.55 * (event.intensity || 0.7), 0], clamp);
    return <AbsoluteFill style={{backgroundColor: event.color || '#FFFFFF', opacity, pointerEvents: 'none'}} />;
  }
  if (type === 'GLEAM') {
    const travel = interpolate(frame, [0, duration], [-45, 145], clamp);
    const opacity = interpolate(frame, [0, duration * 0.18, duration * 0.72, duration], [0, 0.22 * (event.intensity || 0.35), 0.14 * (event.intensity || 0.35), 0], clamp);
    return <AbsoluteFill style={{overflow: 'hidden', pointerEvents: 'none', mixBlendMode: 'screen'}}>
      <div style={{
        position: 'absolute', top: '-20%', bottom: '-20%', left: 0, width: '28%',
        opacity, transform: `translateX(${travel}vw) rotate(14deg)`,
        background: 'linear-gradient(90deg, rgba(255,255,255,0), rgba(255,248,220,0.72), rgba(255,255,255,0))',
        filter: 'blur(10px)',
      }} />
    </AbsoluteFill>;
  }
  if (type === 'TEXT_CARD') {
    const opacity = interpolate(frame, [0, Math.min(5, duration * 0.2), duration - 4, duration], [0, 1, 1, 0], clamp);
    return (
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity, pointerEvents: 'none'}}>
        <div style={{
          maxWidth: 900,
          padding: '28px 42px',
          borderRadius: 22,
          textAlign: 'center',
          background: event.background || 'rgba(0,0,0,0.72)',
          color: event.color || styleConfig.colors.text,
          fontFamily: fontStack(styleConfig, 'display'),
          fontWeight: styleConfig.font.weight,
          fontSize: event.fontSize || styleConfig.fontSize.hero,
          ...outlineShadow(styleConfig),
        }}>
          {event.text}
        </div>
      </AbsoluteFill>
    );
  }
  if (['IMAGE', 'ICON', 'GIF', 'MEME'].includes(type) && event.src) {
    const opacity = interpolate(frame, [0, Math.min(5, duration * 0.2), duration - 4, duration], [0, 1, 1, 0], clamp);
    const contain = type === 'ICON';
    return (
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity, pointerEvents: 'none'}}>
        <Img src={staticFile(event.src)} style={{
          width: contain ? '42%' : '100%', height: contain ? '42%' : '100%',
          objectFit: contain ? 'contain' : 'cover',
        }} />
      </AbsoluteFill>
    );
  }
  return null;
};

export const VisualEvents = ({events, styleConfig}) => {
  const {fps} = useVideoConfig();
  return (events || []).filter((event) => event.enabled !== false && ['FLASH', 'GLEAM', 'TEXT_CARD', 'IMAGE', 'ICON', 'GIF', 'MEME'].includes(String(event.type || event.effect).toUpperCase())).map((event, index) => (
    <Sequence key={`visual-${index}`} from={Math.max(0, Math.round(event.time * fps))} durationInFrames={Math.max(1, Math.round((event.duration || 0.2) * fps))}>
      <VisualEvent event={event} styleConfig={styleConfig} />
    </Sequence>
  ));
};

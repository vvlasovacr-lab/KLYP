import React from 'react';
import {AbsoluteFill, Sequence, useVideoConfig} from 'remotion';
import {BrollLayer} from './BrollLayer';
import {BackgroundMusic} from './BackgroundMusic';
import {Camera} from './Camera';
import {ContrastScene} from './ContrastScene';
import {EditedVideo} from './EditedVideo';
import {NumberScene} from './NumberScene';
import {SfxTrack} from './SfxTrack';
import {Shout} from './Shout';
import {Subtitles} from './Subtitles';
import {TitleCard} from './TitleCard';
import {KeywordHero, QuoteCard, SideText, StackedText, TopCaption} from './TextTemplates';
import {VisualEvents} from './VisualEvents';
import {VisualLook} from './VisualLook';
import {HybridNumberScene, HybridShout, HybridSubtitles, HybridTitleCard} from './HybridTypography';
import {HybridTransitionEffects} from './HybridTransitionEffects';
import {LocalFonts} from './LocalFonts';

const sceneComponent = (scene, hybrid = false, sceneStyle = {}) => {
  if (hybrid) {
    const component = String(sceneStyle.component || '').toUpperCase();
    if (component === 'TITLE_COMPOSITION') return HybridTitleCard;
    if (component === 'SHOUT') return HybridShout;
    if (component === 'NUMBER_STAMP') return HybridNumberScene;
    if (['KINETIC', 'NORMAL', 'PHRASE_BUILD', 'ACCENT_WORD'].includes(component)) return HybridSubtitles;
  }
  const template = String(scene.template || '').toUpperCase();
  if (template === 'KEYWORD_HERO') return KeywordHero;
  if (template === 'STACKED_TEXT') return StackedText;
  if (template === 'SIDE_TEXT') return SideText;
  if (template === 'NUMBER_HERO') return NumberScene;
  if (template === 'TOP_CAPTION') return TopCaption;
  if (template === 'QUOTE_CARD') return QuoteCard;
  if (template === 'CONTRAST_SPLIT') return ContrastScene;
  const type = String(scene.type || '').toUpperCase();
  if (type === 'HERO' || type === 'TITLE') return TitleCard;
  if (type === 'PUNCH') return Shout;
  if (type === 'NUMBER') return NumberScene;
  if (type === 'CONTRAST') return ContrastScene;
  return Subtitles;
};

export const Reel = ({montagePlan, sourceVideo, config, styleConfig}) => {
  const {fps} = useVideoConfig();
  const styles = config || styleConfig;
  const video = sourceVideo || {src: montagePlan.source?.src || 'source.mp4'};
  const execution = montagePlan.execution || {};
  const adapter = montagePlan.visualAdapter || {};
  const hybrid = montagePlan.rendererMode === 'hybrid' && adapter.mode === 'hybrid';
  const executionActive = Number(execution.version || 0) >= 2;
  const textScenes = (montagePlan.scenes || []).filter((scene) => !executionActive || scene.actionType === 'text_action');
  const visualEvents = executionActive ? (execution.visual_actions || []) : (montagePlan.visual || []);
  const cameraEvents = executionActive ? (execution.camera_actions || []) : (montagePlan.camera || []);
  const brollEvents = executionActive ? (execution.broll_actions || []) : (montagePlan.broll || []);
  const audioEvents = executionActive ? (execution.audio_actions || []) : (montagePlan.sfx || []);
  const visualCamera = visualEvents
    .filter((event) => event.enabled !== false && ['SHAKE', 'CAMERA_PUNCH'].includes(String(event.type || event.effect).toUpperCase()))
    .map((event) => ({...event, effect: String(event.type).toUpperCase() === 'CAMERA_PUNCH' ? 'PUNCH_ZOOM' : 'SHAKE'}));
  return (
    <AbsoluteFill style={{backgroundColor: '#000', overflow: 'hidden'}}>
      <LocalFonts styleConfig={styles} />
      <Camera
        events={[...cameraEvents, ...visualCamera]}
        visualEvents={visualEvents}
        drift={montagePlan.config?.cameraDrift || 0}
        baseScale={montagePlan.config?.baseCameraScale || 1}
        anchor={montagePlan.face?.cropAnchor}
        facePlan={montagePlan.face}
        visualProfile={styles.visualProfile}
        polishProfile={styles.visualPolish}
        transitions={hybrid ? (adapter.transitions || []) : []}
      >
        <EditedVideo sourceVideo={video} speechEdit={montagePlan.speechEdit} audioPlan={montagePlan.audio} />
      </Camera>
      <VisualLook profile={styles.visualProfile} />
      <BackgroundMusic music={montagePlan.audio?.music} scenes={textScenes} duration={montagePlan.output?.duration || 0} />
      <BrollLayer events={brollEvents} presentation={hybrid ? adapter.brollPresentation : null} />
      {textScenes.filter((scene) => scene.enabled !== false).map((scene, index) => {
        const from = Math.max(0, Math.round(scene.start * fps));
        const duration = Math.max(1, Math.round((scene.end - scene.start) * fps));
        const sceneStyle = adapter.sceneStyles?.[scene.actionId] || {};
        const Component = sceneComponent(scene, hybrid, sceneStyle);
        const fontScale = Number(scene.executionAction?.motion?.font_scale || 1);
        const actionStyles = fontScale === 1 ? styles : {
          ...styles,
          fontSize: Object.fromEntries(Object.entries(styles.fontSize || {}).map(([key, value]) => [key, Math.round(value * fontScale)])),
        };
        const componentStyles = hybrid ? styles : actionStyles;
        return (
          <Sequence key={`scene-${index}`} from={from} durationInFrames={duration} premountFor={fps}>
            <Component scene={scene} styleConfig={componentStyles} adapter={adapter} sceneStyle={sceneStyle} />
          </Sequence>
        );
      })}
      <VisualEvents events={visualEvents} styleConfig={styles} />
      {hybrid ? <HybridTransitionEffects events={adapter.transitions || []} /> : null}
      <SfxTrack events={audioEvents} />
    </AbsoluteFill>
  );
};

import React from 'react';
import {
  AbsoluteFill,
  Easing,
  interpolate,
  random,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'};
const safe = {left: 52, right: 75, top: 48, bottom: 150};
const body = 'Bahnschrift, Arial, sans-serif';
const display = 'Bahnschrift Condensed, Bahnschrift, Arial Black, sans-serif';
const white = '#f2f2f2';
const yellow = '#e4c654';

const Stage = ({children, label, treatment}) => <AbsoluteFill style={{
  background: 'linear-gradient(165deg,#18191d 0%,#0b0c0f 60%,#111318 100%)',
  overflow: 'hidden', color: white, fontFamily: body,
}}>
  <div style={{position: 'absolute', left: safe.left, right: safe.right, top: safe.top, bottom: safe.bottom, border: '1px solid rgba(228,198,84,.13)', borderRadius: 18}} />
  <div style={{position: 'absolute', left: 24, top: 22, padding: '5px 9px', borderRadius: 6, background: '#24262c', fontSize: 11, letterSpacing: 1.2, color: '#aeb2bd'}}>{label}</div>
  {children}
  {treatment}
</AbsoluteFill>;

const Center = ({children, style = {}}) => <div style={{position: 'absolute', left: safe.left, right: safe.right, top: 300, textAlign: 'center', ...style}}>{children}</div>;
const Text = ({children, style = {}}) => <div style={{fontFamily: display, fontWeight: 900, fontSize: 54, lineHeight: .94, textShadow: '0 4px 9px rgba(0,0,0,.75)', WebkitTextStroke: '1.8px #090909', ...style}}>{children}</div>;

const progressCurrent = (frame, fps) => spring({frame, fps, durationInFrames: 8, config: {damping: 24, stiffness: 205, mass: .68}});
const progressSmooth = (frame, fps, duration = 18) => spring({frame, fps, durationInFrames: duration, config: {damping: 200, stiffness: 100, mass: 1}});

const SoftReveal = ({variant}) => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  const p = variant === 'donor' ? progressSmooth(frame, fps) : progressCurrent(frame, fps);
  const opacity = interpolate(p, [0, 1], [0, 1], clamp);
  const y = interpolate(p, [0, 1], [variant === 'donor' ? 10 : 6, 0], clamp);
  const blur = variant === 'donor' ? interpolate(p, [0, 1], [6, 0], clamp) : 0;
  return <Stage label={`${variant.toUpperCase()} · SOFT REVEAL`}><Center><Text style={{opacity, filter: `blur(${blur}px)`, transform: `translateY(${y}px)`}}>СИЛЬНАЯ МЫСЛЬ</Text></Center></Stage>;
};

const PhraseBuild = ({variant}) => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig(); const words = ['мы', 'создаём', 'понятный', 'ритм'];
  return <Stage label={`${variant.toUpperCase()} · PHRASE BUILD`}><Center style={{display: 'flex', flexWrap: 'wrap', gap: '0 10px', justifyContent: 'center'}}>{words.map((word, i) => {
    const delay = i * (variant === 'donor' ? 4 : 2); const local = Math.max(0, frame - delay);
    const p = variant === 'donor' ? progressSmooth(local, fps, 14) : progressCurrent(local, fps);
    const scale = variant === 'current' ? interpolate(p, [0, .7, 1], [.92, 1.06, 1], clamp) : 1;
    return <Text key={word} style={{fontSize: 48, opacity: interpolate(p,[0,1],[0,1],clamp), transform: `translateY(${interpolate(p,[0,1],[variant === 'donor' ? 9 : 5,0],clamp)}px) scale(${scale})`}}>{word}</Text>;
  })}</Center></Stage>;
};

const AccentHighlight = ({variant}) => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig(); const p = progressSmooth(Math.max(0, frame - 5), fps, 14);
  const bar = interpolate(p,[0,1],[0,100],clamp);
  const pop = spring({frame, fps, durationInFrames: 10, config:{damping:19,stiffness:275,mass:.4}});
  return <Stage label={`${variant.toUpperCase()} · ACCENT`}><Center><Text style={{fontSize:46}}>это <span style={variant === 'current' ? {display:'inline-block', color:yellow, transform:`scale(${interpolate(pop,[0,.7,1],[.88,1.18,1],clamp)})`} : {position:'relative', display:'inline-block', color:'#101010', padding:'0 7px', zIndex:1}}>{variant === 'donor' ? <><span style={{position:'absolute',inset:'3px -2px 1px',width:`${bar}%`,background:yellow,zIndex:-1}}/><span style={{opacity:interpolate(p,[0,1],[0,1],clamp)}}>важно</span></> : 'важно'}</span></Text></Center></Stage>;
};

const NumberPunch = ({variant}) => {
  const frame = useCurrentFrame(); const {fps} = useVideoConfig();
  const p = variant === 'donor' ? progressSmooth(frame,fps,16) : spring({frame,fps,durationInFrames:12,config:{damping:18,stiffness:255,mass:.46}});
  const labelP = progressSmooth(Math.max(0, frame - (variant === 'donor' ? 12 : 4)),fps,14);
  const scale = variant === 'donor' ? interpolate(p,[0,1],[.86,1],clamp) : interpolate(p,[0,.68,1],[.78,1.14,1],clamp);
  return <Stage label={`${variant.toUpperCase()} · NUMBER`}><Center style={{top:270}}><div style={{display:'inline-block',padding:'9px 18px 13px',borderRadius:8,background:yellow,color:'#101010',fontFamily:display,fontWeight:900,fontSize:88,lineHeight:.9,transform:`scale(${scale})`}}>70 тысяч</div><Text style={{fontSize:35,marginTop:14,opacity:interpolate(labelP,[0,1],[0,1],clamp),transform:`translateY(${interpolate(labelP,[0,1],[8,0],clamp)}px)`}}>рублей в месяц</Text></Center></Stage>;
};

const DecayingShake = ({variant}) => {
  const frame = useCurrentFrame(); const duration = 18; const decay = Math.max(0,1-frame/duration); let x=0,y=0;
  if (frame <= duration) {
    if (variant === 'donor') { x=(random(`x-${frame}`)-.5)*9*decay; y=(random(`y-${frame}`)-.5)*5*decay; }
    else { x=Math.sin(frame*2.7)*7*decay; y=Math.cos(frame*2.2)*3.5*decay; }
  }
  return <Stage label={`${variant.toUpperCase()} · MICRO SHAKE`}><Center><Text style={{fontSize:72,color:yellow,transform:`translate(${x}px,${y}px)`}}>СТОП</Text></Center></Stage>;
};

const TwoScenes = ({variant, mode}) => {
  const frame=useCurrentFrame(); const t=interpolate(frame,[15,30],[0,1],clamp); const smooth=Easing.inOut(Easing.cubic)(t);
  let a={opacity:1-smooth}, b={opacity:smooth};
  if(mode==='blur'){const arc=Math.sin(Math.PI*smooth); a.filter=`blur(${(variant==='donor'?7:4)*arc}px)`; b.filter=a.filter;}
  if(mode==='push'){const distance=variant==='donor'?42:16; a.transform=`translateX(${-smooth*distance}px) scale(${1-smooth*.015})`;b.transform=`translateX(${(1-smooth)*distance}px) scale(${.985+smooth*.015})`;}
  if(mode==='whip'){const arc=Math.sin(Math.PI*smooth); const dist=variant==='donor'?150:0;a.transform=`translateX(${-smooth*dist}px)`;b.transform=`translateX(${(1-smooth)*dist}px)`;a.filter=b.filter=`blur(${variant==='donor'?arc*14:0}px)`;}
  return <Stage label={`${variant.toUpperCase()} · ${mode.toUpperCase()}`}><AbsoluteFill style={{...a,background:'#20232b',display:'flex',alignItems:'center',justifyContent:'center'}}><Text>ПРОБЛЕМА</Text></AbsoluteFill><AbsoluteFill style={{...b,background:'#161b18',display:'flex',alignItems:'center',justifyContent:'center'}}><Text style={{color:yellow}}>РЕШЕНИЕ</Text></AbsoluteFill></Stage>;
};

const UiCallout = ({variant}) => {const frame=useCurrentFrame();const {fps}=useVideoConfig();const p=progressSmooth(frame,fps,16);return <Stage label={`${variant.toUpperCase()} · UI CALLOUT`}><div style={{position:'absolute',left:82,top:310,opacity:interpolate(p,[0,1],[0,1],clamp),transform:`translateY(${interpolate(p,[0,1],[10,0],clamp)}px) scale(${interpolate(p,[0,1],[.94,1],clamp)})`,padding:'14px 18px',borderRadius:variant==='donor'?14:5,background:variant==='donor'?'rgba(25,27,33,.94)':'#e4c654',color:variant==='donor'?white:'#111',border:variant==='donor'?'1px solid rgba(228,198,84,.6)':'none',fontWeight:800,fontSize:28}}>Проверенный факт</div>{variant==='donor'?<div style={{position:'absolute',left:190,top:370,width:90,height:2,background:yellow,transformOrigin:'left',transform:`rotate(22deg) scaleX(${interpolate(p,[0,1],[0,1],clamp)})`}}/>:null}</Stage>};

const Vignette = ({variant}) => <Stage
  label={`${variant.toUpperCase()} · VIGNETTE`}
  treatment={<AbsoluteFill style={{background:variant==='donor'?'radial-gradient(circle at 50% 43%,transparent 48%,rgba(0,0,0,.25) 100%)':'radial-gradient(circle at 50% 50%,transparent 40%,rgba(0,0,0,.34) 100%)',pointerEvents:'none'}} />}
><Center><Text>ЧИСТЫЙ КАДР</Text></Center></Stage>;

export const MotionDonorAB = ({candidate, variant}) => {
  if(candidate==='soft-reveal') return <SoftReveal variant={variant}/>;
  if(candidate==='phrase-build') return <PhraseBuild variant={variant}/>;
  if(candidate==='accent-highlight') return <AccentHighlight variant={variant}/>;
  if(candidate==='number-punch') return <NumberPunch variant={variant}/>;
  if(candidate==='decaying-micro-shake') return <DecayingShake variant={variant}/>;
  if(candidate==='clean-dissolve') return <TwoScenes variant={variant} mode="dissolve"/>;
  if(candidate==='controlled-blur-transition') return <TwoScenes variant={variant} mode="blur"/>;
  if(candidate==='clean-push') return <TwoScenes variant={variant} mode="push"/>;
  if(candidate==='ui-callout') return <UiCallout variant={variant}/>;
  if(candidate==='subtle-vignette') return <Vignette variant={variant}/>;
  return <TwoScenes variant={variant} mode="whip"/>;
};

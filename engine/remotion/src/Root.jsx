import React from 'react';
import {Composition} from 'remotion';
import {Reel} from './Reel';
import defaultPlan from './data/montage_plan.json';
import defaultChunks from './data/chunks.json';
import defaultConfig from './styles/config.json';

const duration = (props) => props.montagePlan?.output?.duration || props.sourceVideo?.duration || props.montagePlan?.source?.duration || 10;
const output = (props) => props.montagePlan?.output || {};

export const Root = () => (
  <Composition
    id="Reel"
    component={Reel}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={300}
    defaultProps={{chunks: defaultChunks, montagePlan: defaultPlan, sourceVideo: null, config: defaultConfig}}
    calculateMetadata={({props}) => ({
      durationInFrames: Math.max(1, Math.ceil(duration(props) * (output(props).fps || 30))),
      fps: output(props).fps || 30,
      width: output(props).width || 1080,
      height: output(props).height || 1920,
    })}
  />
);

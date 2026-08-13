import React from 'react';
import {Composition} from 'remotion';
import {MotionDonorAB} from './MotionDonorAB';

const candidates = [
  'soft-reveal', 'phrase-build', 'accent-highlight', 'number-punch',
  'decaying-micro-shake', 'clean-dissolve', 'controlled-blur-transition',
  'clean-push', 'ui-callout', 'subtle-vignette', 'rare-whip-pan',
];

export const Root = () => <>
  {candidates.flatMap((candidate) => ['current', 'donor'].map((variant) => (
    <Composition
      key={`${candidate}-${variant}`}
      id={`${candidate}-${variant}`}
      component={MotionDonorAB}
      defaultProps={{candidate, variant}}
      durationInFrames={54}
      fps={30}
      width={540}
      height={960}
    />
  )))}
</>;

import React, {useEffect, useRef} from 'react';
import {cancelRender, continueRender, delayRender, staticFile} from 'remotion';

const proof = 'ДЕНЬГИ 70 ТЫСЯЧ — ДИСЦИПЛИНА / РЕЗУЛЬТАТ №5 ₽';

export const LocalFonts = ({styleConfig}) => {
  const handle = useRef(null);
  if (handle.current === null) handle.current = delayRender('Loading ShortsAI project-local fonts');
  const assets = styleConfig?.font?.assets || {};
  const signature = JSON.stringify(Object.values(assets).map((asset) => [asset.resolvedFamily, asset.src, asset.weight, asset.variable]));

  useEffect(() => {
    const unique = new Map();
    Object.values(assets).forEach((asset) => {
      if (asset?.resolvedFamily && asset?.src) unique.set(asset.resolvedFamily, asset);
    });
    const load = async () => {
      for (const asset of unique.values()) {
        const descriptors = {style: 'normal', weight: asset.variable ? '100 900' : String(asset.weight || 400), display: 'block'};
        const face = new FontFace(asset.resolvedFamily, `url(${staticFile(asset.src)})`, descriptors);
        const loaded = await face.load();
        document.fonts.add(loaded);
        if (!document.fonts.check(`64px "${asset.resolvedFamily}"`, proof)) {
          throw new Error(`Local font did not validate in browser: ${asset.resolvedFamily}`);
        }
      }
      await document.fonts.ready;
      continueRender(handle.current);
    };
    load().catch((error) => cancelRender(error));
  }, [signature]);
  return null;
};

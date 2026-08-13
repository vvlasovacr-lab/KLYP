export const activeSceneWords = (scene, absoluteTime) => {
  const source = (scene.words || []).map((word, index) => ({...word, _index: index}));
  if (!source.length) {
    return String(scene.text || '').trim().split(/\s+/).filter(Boolean).map((word, index) => ({
      word,
      start: scene.start,
      end: scene.end,
      role: 'ordinary',
      _index: index,
    }));
  }
  const step = (scene.compositionSteps || []).find((item) => absoluteTime >= item.start && absoluteTime <= item.end + 0.04);
  if (step?.visibleWords?.length) {
    const visible = new Set(step.visibleWords);
    return source.filter((word) => visible.has(word._index));
  }
  return source;
};

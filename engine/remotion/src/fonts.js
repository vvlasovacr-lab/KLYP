const quoteFamily = (name) => name.includes(' ') ? `"${name}"` : name;

export const fontStack = (styleConfig, role = 'body') => {
  const configured = styleConfig.font?.families?.[role];
  const legacy = role === 'body' ? styleConfig.font?.family : styleConfig.font?.displayFamily;
  const families = Array.isArray(configured) ? configured : legacy ? legacy.split(',').map((item) => item.trim()) : [];
  const fallbacks = role === 'body'
    ? ['Arial Black', 'Arial', 'sans-serif']
    : ['Impact', 'Arial Black', 'Arial', 'sans-serif'];
  return [...families, ...fallbacks]
    .filter((value, index, all) => value && all.indexOf(value) === index)
    .map(quoteFamily)
    .join(', ');
};

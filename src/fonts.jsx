import {staticFile} from 'remotion';

const face = (family, file) => `
@font-face {
	font-family: '${family}';
	src: url('${staticFile(`fonts/${file}`)}') format('truetype');
	font-weight: 100 900;
	font-display: swap;
}`;

// Если свой шрифт почему-то не приехал, текст должен нарисоваться хоть
// чем-то. В контейнере системных шрифтов может не быть вовсе, поэтому
// подпираем стандартными именами — их подставит fontconfig.
const FALLBACK = `
* { font-synthesis: weight style; }
body { font-family: 'Montserrat', 'DejaVu Sans', 'Liberation Sans', sans-serif; }`;

export const Fonts = () => (
	<style>
		{[
			face('Montserrat', 'Montserrat.ttf'),
			face('Oswald', 'Oswald.ttf'),
			face('Unbounded', 'Unbounded.ttf'),
			face('GolosText', 'GolosText.ttf'),
			face('Manrope', 'Manrope.ttf'),
		].join('\n') + FALLBACK}
	</style>
);

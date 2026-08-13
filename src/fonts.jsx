import {staticFile} from 'remotion';

const face = (family, file) => `
@font-face {
	font-family: '${family}';
	src: url('${staticFile(`fonts/${file}`)}') format('truetype');
	font-weight: 100 900;
	font-display: block;
}`;

export const Fonts = () => (
	<style>
		{[
			face('Montserrat', 'Montserrat.ttf'),
			face('Oswald', 'Oswald.ttf'),
			face('Unbounded', 'Unbounded.ttf'),
			face('GolosText', 'GolosText.ttf'),
			face('Manrope', 'Manrope.ttf'),
		].join('\n')}
	</style>
);

// Генератор служебных звуков.
// Короткие интерфейсные призвуки под склейки, наезды и появление слов.
// Запуск: node tools/make-sfx.mjs

import {mkdirSync, writeFileSync} from 'node:fs';

const SR = 48000;

const wav = (samples) => {
	const n = samples.length;
	const buf = Buffer.alloc(44 + n * 2);
	buf.write('RIFF', 0);
	buf.writeUInt32LE(36 + n * 2, 4);
	buf.write('WAVEfmt ', 8);
	buf.writeUInt32LE(16, 16);
	buf.writeUInt16LE(1, 20);
	buf.writeUInt16LE(1, 22);
	buf.writeUInt32LE(SR, 24);
	buf.writeUInt32LE(SR * 2, 28);
	buf.writeUInt16LE(2, 32);
	buf.writeUInt16LE(16, 34);
	buf.write('data', 36);
	buf.writeUInt32LE(n * 2, 40);
	samples.forEach((v, i) => {
		const c = Math.max(-1, Math.min(1, v));
		buf.writeInt16LE(Math.round(c * 32000), 44 + i * 2);
	});
	return buf;
};

const make = (seconds, fn) => {
	const n = Math.round(SR * seconds);
	const out = new Float32Array(n);
	for (let i = 0; i < n; i++) out[i] = fn(i / SR, i / n);
	return out;
};

// мягкий вход и плавный хвост — щелчков на краях быть не должно
const shape = (p, attack = 0.06, curve = 3) =>
	p < attack ? p / attack : Math.pow(1 - (p - attack) / (1 - attack), curve);

// резонансный фильтр, чтобы шум звучал как воздух, а не как помеха
const bandpass = (input, freqAt, q = 3) => {
	const out = new Float32Array(input.length);
	let low = 0;
	let band = 0;
	for (let i = 0; i < input.length; i++) {
		const f = 2 * Math.sin((Math.PI * freqAt(i / input.length)) / SR);
		const high = input[i] - low - q * band;
		band += f * high;
		low += f * band;
		out[i] = band;
	}
	return out;
};

const noise = (seconds) => make(seconds, () => Math.random() * 2 - 1);

// пролёт воздуха. Два тона, чтобы соседние врезки не звучали одинаково;
// reverse — нарастающий, под возврат с перебивки на лицо
const whoosh = ({low = 320, high = 3900, seconds = 0.42, reverse = false} = {}) => {
	const raw = noise(seconds);
	const filtered = bandpass(
		raw,
		(p) => low + (high - low) * Math.pow(reverse ? 1 - p : p, 1.6),
		1.4
	);
	return filtered.map((v, i, a) => {
		const p = i / a.length;
		const env = reverse ? shape(1 - p, 0.14, 2.2) : shape(p, 0.18, 2.4);
		return v * env * 0.55;
	});
};

// сухой щелчок — под появление акцентного слова. Высота чередуется,
// иначе четырнадцать одинаковых щелчков превращаются в стук
const tick = (freq = 2100) =>
	make(0.07, (t, p) => {
		const body = Math.sin(2 * Math.PI * freq * t) * Math.exp(-t * 90);
		const edge = (Math.random() * 2 - 1) * Math.exp(-t * 400) * 0.5;
		return (body + edge) * 0.42 * shape(p, 0.02, 2);
	});

// мягкий «поп» — под выезд карточки
const pop = () =>
	make(0.2, (t, p) => {
		const f = 880 * Math.exp(-t * 12) + 240;
		return Math.sin(2 * Math.PI * f * t) * Math.exp(-t * 16) * 0.5 * shape(p, 0.03, 2);
	});

// низкий удар — под жёсткую склейку
const impact = () =>
	make(0.55, (t, p) => {
		const f = 92 * Math.exp(-t * 7) + 44;
		const sub = Math.sin(2 * Math.PI * f * t) * Math.exp(-t * 6);
		const snap = (Math.random() * 2 - 1) * Math.exp(-t * 260) * 0.28;
		return (sub * 0.75 + snap) * shape(p, 0.008, 2);
	});

mkdirSync('public/sfx', {recursive: true});
for (const [name, data] of [
	['whoosh-hi', whoosh({low: 420, high: 4400})],
	['whoosh-lo', whoosh({low: 220, high: 2400, seconds: 0.5})],
	['whoosh-back', whoosh({low: 300, high: 3000, seconds: 0.36, reverse: true})],
	['tick-a', tick(2100)],
	['tick-b', tick(1550)],
	['pop', pop()],
	['impact', impact()],
]) {
	writeFileSync(`public/sfx/${name}.wav`, wav(Array.from(data)));
	console.log(`public/sfx/${name}.wav — ${(data.length / SR).toFixed(2)}с`);
}

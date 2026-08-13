// ЗВУКОВЫЕ АКЦЕНТЫ.
//
// Расставляются не вручную, а выводятся из уже размеченных событий:
// вход и выход врезки, наезд камеры на акценте, выкрик.
// Меняешь тайминг события — звук едет за ним сам.
//
// Два правила, без которых звук начинает мешать:
//   один момент — один звук (пара подряд слышится как ошибка);
//   соседние события звучат разной высотой, иначе выходит стук.
//
// Файлы генерируются: node tools/make-sfx.mjs

export const SFX = {
	on: true,
	master: 0.9, // общая громкость всех призвуков
	minGap: 0.22, // ближе этого два звука не ставим
};

// Строит дорожку призвуков из монтажного плана.
export const buildCues = ({broll = [], accents = [], shouts = []}) => {
	const cues = [];

	broll.forEach((shot, i) => {
		// вход в перебивку — один пролёт, тон чередуется через раз
		cues.push({
			at: shot.from,
			name: i % 2 === 0 ? 'whoosh-hi' : 'whoosh-lo',
			volume: 0.7,
		});
		// возврат на лицо — нарастающий, тише
		cues.push({at: shot.to - 0.22, name: 'whoosh-back', volume: 0.42});
	});

	// наезд камеры на акцентном слове
	accents.forEach(([start], i) => {
		cues.push({at: start, name: i % 2 === 0 ? 'tick-a' : 'tick-b', volume: 0.3});
	});

	// выкрик — единственное место, где бьёт низкий удар
	for (const shout of shouts) {
		cues.push({at: shout.from, name: 'pop', volume: 0.6});
		cues.push({at: shout.from + 0.02, name: 'impact', volume: 0.5});
	}

	// прореживаем: если два звука сошлись слишком близко, тихий уступает
	const sorted = cues.sort((a, b) => a.at - b.at);
	const kept = [];
	for (const cue of sorted) {
		const prev = kept[kept.length - 1];
		if (prev && cue.at - prev.at < SFX.minGap) {
			// исключение — пара «поп + удар» на выкрике, она задумана как один звук
			const paired = cue.name === 'impact' && prev.name === 'pop';
			if (!paired) {
				if (cue.volume > prev.volume) kept[kept.length - 1] = cue;
				continue;
			}
		}
		kept.push(cue);
	}

	return kept;
};

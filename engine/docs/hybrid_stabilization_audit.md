# Clip Visual Adapter / AI Director Execution audit

Source: `input/video.mp4`  
Corrected render: `output/video_CORRECTED_HYBRID.mp4`

## Result

The existing pipeline remains unchanged:

`Whisper -> Speech Edit -> AI Director -> Execution Plan -> Clip Visual Adapter -> Montage Plan -> Remotion`

The stabilization removed the two main causes of artificial editing:

1. One B-roll asset is no longer expanded into three consecutive one-second shots.
2. Clip Visual Adapter no longer overrides semantic typography templates or adds timing outside the Director execution interval.

## Responsibility boundaries

- **AI Director** estimates semantic need and emits a pre-asset B-roll necessity score.
- **B-roll planner / Execution Layer** verifies the actual asset match, spacing, coverage and reuse limits, then creates the final execution event.
- **Clip Visual Adapter** maps approved actions to visual components without retiming them or replacing Director-selected templates.
- **Remotion** executes the supplied text, camera, visual, B-roll and audio actions; it does not invent montage decisions.

## B-roll decision model

`broll_necessity` is separate from phrase importance and contains:

- visualizability;
- semantic change;
- explanatory value;
- novelty;
- actual asset match;
- final necessity score.

For talking-head videos the current policy is:

- 1.4-2.0 seconds per insertion;
- at least 8 seconds between insertions;
- no more than three bursts for a 45-60 second video;
- no more than 12% total coverage;
- no repeated asset;
- weak asset matches are skipped without breaking the render.

## Three-way comparison

| Metric | Legacy | Hybrid before stabilization | Corrected hybrid |
|---|---:|---:|---:|
| B-roll events | 3 | 3 | 2 |
| B-roll duration | 8.96 s | 9.00 s | 4.00 s |
| B-roll coverage | 17.35% | 17.43% | 7.75% |
| Camera actions | 11 | 5 | 6 |
| Visual actions | 3 | 1 | 1 |
| SFX actions | 17 | 6 | 6 |
| Speaker-only coverage | 62.10% | 69.59% | 77.59% |

The corrected version retains intentional calm intervals while keeping semantic changes within roughly 2-5 seconds. It does not reward a plan merely for having more effects.

## Corrected B-roll events

- `5.080-7.080`: `luxury/inheritance_property.mp4`, necessity `0.846`.
- `48.424-50.424`: `money/service_value.mp4`, necessity `0.787`.
- Candidates at `24.752` and `36.972` were skipped because the best available asset match was only `0.506`.

## Typography and camera audit

- NORMAL emphasis stays white and uses only a restrained scale change.
- Accent color and stronger scale are reserved for ACCENT, HOOK, HERO, PUNCH, NUMBER and CONTRAST.
- Director templates such as `SIDE_TEXT`, `TOP_CAPTION`, `QUOTE_CARD` and `CONTRAST_SPLIT` survive the adapter boundary.
- Camera actions use decision strength and semantic importance, include a settle/return to `1.0`, and do not collide with executed B-roll intervals.
- Face-safe placement remains active; inspected preview frames contain no text-over-face failure.

## Verification

- Unit tests: 21 passed.
- Final output: H.264 + AAC, 1080x1920, 30 fps, 51.8 seconds.
- Full FFmpeg decode: passed.
- Quality score: `0.968`.
- Audio: approximately `-14.06 LUFS`, true peak `-1.41 dBTP`.
- B-roll coverage: `7.75%`.
- Effects density: `0.232/s`.
- Calm-space score: `1.0`.

## Remaining limitations

- Asset relevance is still limited by the size and labeling quality of the local B-roll library.
- Semantic scoring is heuristic and can be improved later with a dedicated evaluation set, without changing the current pipeline.
- A future polish pass may tune individual typography presets and SFX loudness, but should keep the execution boundary and B-roll limits introduced here.

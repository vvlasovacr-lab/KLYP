# Clip visual integration audit

## Decision

ShortsAI remains the main editing engine. The inspected Clip main project is used only as a visual-reference implementation. Its source-specific timings and planner are not imported.

## Layer comparison

| Layer | Decision | Reason |
|---|---|---|
| Whisper / word timestamps | KEEP SHORTSAI | Clip main has silence detection but no complete speech recognition layer. |
| Speech edit / retime | KEEP + selective MERGE | ShortsAI owns semantic boundaries, pauses and connector preservation. Clip's stable visual word slots are adopted in the renderer, not as transcript logic. |
| AI planning / Director | KEEP SHORTSAI | Clip's template planner uses periodic counters and is not semantic. |
| Typography | MERGE | Keep ShortsAI scene meaning and face-safe layout; adopt fitted text, reserved word positions, spring tuning and stronger Title/Shout/Number compositions. |
| Motion | MERGE | Clip-like curves execute existing motion intensity; they do not create new semantic events. |
| Camera | MERGE | Keep semantic and face-aware camera; add planned focus blur/punch transitions. |
| B-roll | MERGE | Keep ShortsAI asset selection and timing; add fade/blur/zoom presentation. |
| SFX | KEEP SHORTSAI | Existing resolver, missing-file safety and semantic cue selection are stronger. |
| Backend / Telegram / payments | IGNORE | Unrelated to output visual quality. |

## Hardcoded Clip main data rejected

- `src/accents.js`: fixed accent words and timestamps for one video.
- `src/broll.js`: fixed clips and intervals.
- `src/cuts.json`: manual cut list.
- `src/chunks.json`: one source transcript.
- `src/style.js`: source-specific title copy/timing and face coordinate.
- `src/Root.jsx`: fixed demo duration.
- `src/Reel.jsx`: static `base.mp4` and imported demo events.
- `src/TitleCard.jsx` and `src/Shout.jsx`: content coming from static demo definitions.

## Integrated architecture

```text
Whisper / Speech Edit / Semantic Analysis
                    |
              AI Director
                    |
        director_execution_plan.json
                    |
     shortsai/clip_visual_adapter.py
                    |
 montage_plan.json + clip_visual_plan.json
                    |
   Remotion legacy | hybrid feature flag
                    |
                 MP4
```

The adapter is deliberately renderer-only: it maps existing action IDs, times, scene types and intensities to visual parameters. It does not inspect phrases to invent accents and contains no video-specific timestamps.

## Feature flag

Set `remotion.renderer_mode` in `config.json`, or use:

```powershell
python run.py --file input/video.mp4 --renderer-mode legacy
python run.py --file input/video.mp4 --renderer-mode hybrid
```

`legacy` executes the previous ShortsAI Remotion components. `hybrid` enables stable kinetic word slots, text fitting, hybrid Title/Shout/Number scenes, semantic transition polish and B-roll presentation.

## Current validation result

- Input: `input/video.mp4`
- Output: 1080x1920, 30 fps, H.264 video + AAC audio
- Duration: 51.8 seconds
- Scenes: 52
- Hybrid styled scenes: 52
- Strong compositions: 8
- Semantic transitions: 7
- B-roll entry/return transitions: 6
- Full decode: passed
- Automated quality score: 0.929 in both modes (the current score measures technical/plan quality, not typography aesthetics)

## Remaining risks

- Font rendering still depends on installed Windows fonts and fallbacks.
- The quality report needs perceptual typography/layout metrics to score visual differences.
- Width fitting is deterministic and safe, but a future DOM measurement pass can be more exact for unusual fonts.
- Blur/flash limits should be tuned on a broader set of calm, dark and high-motion source videos.

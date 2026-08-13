# ShortsAI

Local batch pipeline for vertical TikTok, Reels, and Shorts editing.

Primary path:

```text
input -> faster-whisper -> Raw Session Analysis -> Episode Extraction -> child jobs -> speech edit -> AI Director -> Execution -> montage plan -> Remotion -> QC -> output
```

Long recording sessions are classified as `RAW_MULTI_TAKE_SESSION`; short ready
sources remain `SINGLE_READY_CLIP` and pass through unchanged. Raw-session analysis
uses pauses, punctuation, recording-side cues, semantic continuity and repeated-take
quality to label `NON_CONTENT`, `RETAKE`, `EPISODE` and `REVIEW_REQUIRED` ranges.
Each selected episode becomes an isolated child job with its own AUTO style decision,
Director/Execution plans, face tracking, render and quality report. The parent job writes
`raw_session_analysis.json`, `raw_session_summary.json` and an interactive
`previews/raw_session_timeline.html`. `source_map.json` in every child preserves the
mapping from final episode words and ranges back to the original source timeline.

Place one or more `.mp4`, `.mov`, `.mkv`, or `.webm` files in `input`, then run:

```powershell
python run.py
```

Process one file or build debug data without rendering:

```powershell
python run.py --file "input/name.mp4"
python run.py --preview
python run.py --style AUTO
python run.py --style AGGRESSIVE_RED
```

`output` contains final MP4 files only. Each source has an isolated directory in
`work/jobs/<job_id>` containing transcript, corrected word chunks, retimed blocks,
the v4 montage plan, Director decisions, speech-edit decisions, face plan, audio plan, preview events,
render props, and temporary files. Batch status
is written to `logs/run_manifest.json`.

The model is loaded lazily once per batch. `corrections.json` changes text without
changing or deleting word timestamps. Remotion receives all editorial decisions
through props and does not select emphasis, scene types, camera events, or assets.

`speech_edit_plan.json` contains both the stable snake_case `timeline` consumed by
Remotion and a human-readable `cuts` / `segments` view. Long pauses are shortened
without removing the configured breathing room, contextual fillers are retained,
and low-information clauses may use conservative boundary-aligned compression.
Hook analysis records a score and semantic signals for the first three seconds.

Style profiles live in `style_profiles.json`: `AGGRESSIVE_RED`, `CLEAN_YELLOW`,
and `PODCAST`. Use `"profile": "AUTO"` in `config.json` to let the Director select
a profile from topic, emotional density, speech tempo, audience and format, or override
one run with `--style`. Legacy names `MONEY` and `AGGRESSIVE` remain aliases. The
selection rationale and confidence are saved in `director_style.json`.

`director_plan.json` is the editorial source of truth. It records semantic segments,
retention scores and reasons, text roles/templates, camera, B-roll and SFX proposals,
plus optional speech-compression recommendations. The montage-plan builder translates
these decisions into the existing renderer schema; Remotion remains a deterministic
executor and contains no semantic selection rules. Speech editing removes safe filler/pause ranges,
can tighten weak spans, and maps every original word onto the edited output timeline.

`director_execution_plan.json` translates every semantic decision into explicit
`text_action`, `camera_action`, `visual_action`, `audio_action`, and `broll_action`
objects. It resolves face-safe layout, semantic zoom strength, motion intensity,
local B-roll assets and optional SFX cues before rendering. Remotion reads these
actions directly; the previous montage behavior remains available only as a legacy
fallback when an execution plan is absent. Preview mode also writes
`montage_plan.before_execution.json`, `preview_events.before_execution.json`, and
`preview_comparison.json` for before/after plan inspection.
OpenCV face samples determine the camera anchor and safe text side. If OpenCV is not
available, a deterministic safe-zone fallback is used.

Audio is finalized with denoise, compression, and two-pass EBU loudness normalization.
Source loudness is measured before rendering and drives conservative automatic voice gain.
The final chain is high-pass, voice presence EQ, FFT denoise, compressor, limiter and
two-pass EBU normalization. Defaults target -14 LUFS with AAC-safe true-peak headroom,
stereo AAC at 48 kHz. Optional `background_music.json` selects a local track from
`assets/music`; Remotion ducks it from word timestamps and smoothly restores it in pauses.

Local optional assets:

```text
assets/broll/   local videos selected by semantic filename and sidecar tags
assets/sfx/     categorized pop, whoosh, impact, click, bass_hit and transition sounds
assets/music/   optional background music selected by background_music.json
```

The searchable indexes are `assets/broll/broll_index.json` and `assets/sfx/index.json`.
B-roll bursts use 3-6 second semantic blocks where the library can support them, with
multiple cuts, pan/zoom motion and a fade back to the speaker. Missing or irrelevant
assets are skipped.

Missing assets are skipped safely. The previous `py -m shortsai` ASS/FFmpeg path is
kept as a legacy fallback while Remotion is the primary renderer.

Typography, camera and output settings are controlled in `config.json`. Profile-level
colors, scene thresholds, camera strengths, typography scale and B-roll cadence are in
`style_profiles.json`. The renderer receives these values through JSON props and does
not infer editorial meaning.

Semantic camera calibration lives in `camera_profiles.json`. Available styles include
`AGGRESSIVE_RED`, `CLEAN_YELLOW`, `PODCAST`, `VIRAL_SHORTS`, and `CINEMATIC`.
Every run writes `quality_report.json` with hook, visual cadence, B-roll coverage,
measured LUFS/true peak and a weighted final quality score.
## Autonomous AI editing layer

With `"profile": "AUTO"` in `config.json`, ShortsAI now creates two explicit decisions before AI Director:

- `content_analysis.json` — topic, keywords, audience, delivery pace/energy, questions, numbers, conflicts, hook and face composition;
- `style_intelligence.json` — selected profile, confidence, competing scores, human-readable reasons and recommended edit intensity.

The compatible `director_style.json` contract is still written, so existing AI Director and Execution Layer integrations continue to work.

Professional profiles in `style_profiles.json`:

- `AGGRESSIVE_SOCIAL` — fast business/money/conflict Shorts;
- `CLEAN_EXPERT` — clean expert and educational content;
- `PODCAST_PREMIUM` — sparse premium talking-head/podcast edit;
- `CINEMATIC_STORY` — restrained story and documentary treatment;
- `HIGH_RETENTION` — maximum controlled semantic activity.

Each profile controls typography scale, word timing, camera intensity, edit cadence, B-roll density, transitions, visual effects, SFX policy and color grade. Existing profiles remain available for older jobs.

### Adding styles, fonts and looks

1. Add a complete behavior profile to `style_profiles.json`.
2. Reference a font set with `font_profile`; define the set in `font_profiles.json`.
3. Reference a visual treatment with `visual_profile`; define contrast, saturation, brightness, vignette and film grain in `visual_profiles.json`.
4. Add or tune reusable JSON motion definitions in `motion_profiles.json`. Remotion receives the resolved preset values through props.
5. Run `python run_remotion.py --preview --force --style PROFILE_NAME`, inspect `style_intelligence.json`, `director_execution_plan.json` and `quality_report.json`, then render without `--preview`.

### Adding assets

Place local files under `assets/`. The catalog supports video, images, overlays, particles, light leaks, glitch, film grain, motion graphics, SFX and music. Add a sidecar named `asset.ext.json` with optional fields:

```json
{
  "category": "money",
  "topic": "wealth",
  "emotion": "aspirational",
  "keywords": ["money", "business", "success"],
  "styles": ["AGGRESSIVE_SOCIAL", "HIGH_RETENTION"],
  "importance": 0.85,
  "description": "Close-up business payment visual"
}
```

`assets/asset_index.json` is rebuilt automatically. B-roll selection remains semantic and deterministic; if no relevant asset reaches the threshold, the event is skipped without failing the render.

### Quality control

After rendering, `quality_report.json` reports `hook_score`, `visual_score`, `retention_score`, `readability_score`, `face_safety_score`, effect balance, audio level and `overall_score`. It also identifies long static intervals, risky text blocks and actionable recommendations. The report is advisory: it does not silently mutate a completed render.

## Isolated jobs and multi-video evaluation

Every `run.py` attempt now has a unique workspace under `work/jobs/<job_id>`; transcript,
Director/Execution/Montage plans, Remotion props, diagnostics and output cannot collide
with another source or retry. Use `py run.py --file input/video.mp4 --debug` for a Director
Inspector, or put multiple real sources into `input_tests/` and run
`py batch_eval.py --input input_tests`. Full commands, artifact layout, job statuses,
holdout usage and failure diagnostics are documented in
[`docs/JOB_BATCH_DEBUG.md`](docs/JOB_BATCH_DEBUG.md).

## Editorial Quality Gate

Raw-session processing keeps semantic selection and editorial boundaries separate:

```text
Whisper -> Raw Session Analysis -> Episode Extraction
        -> Editorial Quality Gate -> Speech Edit -> AI Director
        -> Execution Plan -> Montage Plan -> Text Safety -> Remotion
```

`editorial_quality_plans.json` records the original semantic boundary, the selected
editorial in/out, speech and visual readiness, confidence, reasons, warnings, removed
fragments and every considered start candidate. The gate uses local OpenCV face
detection and five-point landmarks when the bundled YuNet model is available; it
falls back safely when visual analysis is unavailable. It never trims solely because
the subject briefly looks away. Low-confidence starts are preserved and flagged for
review instead of being cut blindly.

The full source mapping chain is retained in `source_map.json`:

```text
original source -> episode proxy -> speech-edit timeline -> final output
```

`text_composition` in `config.json` controls symmetric safe-area margins, animation
padding, minimum side width, body/display auto-fit limits and maximum line counts.
Every text template is measured before render. Unsafe side layouts, edge collisions,
face overlap and excessive vertical stacks follow a deterministic fallback chain and
are reported in `montage_plan.json` under `compositionSafety`. The same measured box
is consumed by Remotion; the renderer does not invent a second placement decision.

### Internal Performance Quality Pass

The Editorial Quality Gate also evaluates every semantic phrase inside a child
episode. Measured evidence includes sustained camera engagement/head-pose quality,
face presence, pose stability, frame usability/blur, Whisper word confidence,
speech completeness and transition risk. A short natural glance is retained. A
sustained weak interval creates one of four explicit `editorial_internal_actions`:
`KEEP`, `TRIM`, `REPLACE_TAKE`, or `REVIEW_REQUIRED`.

`REPLACE_TAKE` is allowed only for a semantically equivalent, complete raw-session
take with a configured performance gain. `TRIM` is restricted to complete technical,
duplicate or filler-heavy phrases at safe word/punctuation boundaries. Important
continuous speech without a safe alternative remains on screen and receives
`REVIEW_REQUIRED`; it is never hidden by random B-roll. Source, proxy and final
speech-edited output coordinates are retained for every action.

`editorial_quality` in `config.json` controls sampling cadence, sustained-gaze
windows, performance threshold, retake similarity/gain, safe shot duration and
jump-cut cadence. `--episodes 001,002,004` can restrict a raw-session regression run
without changing production episode extraction.

Typography preflight uses the installed font file when available and measures final
font size, tracking, line-height, proportional stroke/shadow, animation envelope,
temporal face envelope and phone-legibility threshold. The report exposes
`text_edge_violation`, `animation_edge_violation`, `body_text_too_small`,
`stroke_too_heavy`, `narrow_text_column`, `excessive_line_count`,
`face_text_collision`, `layout_balance`, and `typography_readability`.

B-roll requests now include `insert_value` and `insert_type`. Automatic insertion is
limited to local `SEMANTIC_BROLL`; decorative inserts are disabled and editorial
cover requires an explicit future cut-cover request plus a strong asset match.

After encoding, `rendered_frame_qc.json` samples opening frames, settled strong
typography, B-roll transitions and editorial actions. It verifies frame decode,
sharpness and local text-region contrast and writes full-resolution JPG previews to
`previews/rendered_frame_qc`.

## Offline Reference Intelligence

Reference evaluation is an isolated, read-only learning workflow. It never receives a
reference FINAL during the ordinary AUTO baseline and never rewrites production
configuration automatically:

```powershell
py reference_eval.py --dataset reference_dataset --build-candidate --render-comparison
```

The evaluator discovers nested `raw_to_final` pairs and `final_only` examples, probes
media, aligns RAW and FINAL by normalized word timestamps, measures visual structure,
runs an independent ShortsAI BEFORE, and writes a reversible candidate AFTER. Outputs
are under `output/reference_analysis/` and include the manifest, aggregate
distributions, per-layer JSON reports, semantic difference timeline, four-video HTML
inspector, preview gallery, detailed report and executive summary.

Final-only examples contribute visual/style statistics only. A candidate is never
promoted with fewer than three independent RAW→FINAL pairs and a holdout validation;
unknown, unaligned or low-confidence observations stay explicit instead of being
converted into editorial rules.

The evidence-aware pass also writes `visual_behavior_profiles/`,
`reference_priors.json`, `evidence_hypotheses.json`, `broll_evidence_rules.json` and
`reference_evidence_dashboard.html`. Candidate v1 remains available as a numerical
control; Candidate v2 uses multi-objective evidence, composition transitions,
type-specific camera distributions, semantic rest opportunities and explicit B-roll
states (`DIRECTOR_MISSED_BROLL`, `BROLL_WANTED_BUT_ASSET_MISSING`, and
`CANDIDATE_REJECTED_LOW_CONFIDENCE`). LOW evidence is suggestion-only. Final-only
references never acquire editorial authority, even when their transcript is used to
describe the phrase accompanying an observable visual event.

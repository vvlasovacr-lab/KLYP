# ShortsAI: fixed AI editor pipeline

The production order is fixed. A downstream layer may execute upstream
decisions, but it may not silently change them.

## 1. Input video

Contract: a probed media source. No editorial or visual decisions.

## 2. Transcription

Artifacts:

- `transcript.raw.json` — immutable Whisper output;
- `transcript.corrected.json` — dictionary corrections;
- `transcript.normalized.json` — conversational number normalization;
- `transcript.normalization.json` — auditable normalization changes.

Word timestamps remain the timing authority.

## 3. Speech analysis

Finds pauses, clauses, hook signals, delivery quality and semantic phrase
boundaries. It describes speech and does not select typography or effects.

## 4. Editorial director

Artifacts:

- `content_map.json`;
- `editorial_quality_plan.json`.

The content map assigns each phrase a narrative function (`HOOK`, `POINT`,
`EXAMPLE`, `EVIDENCE`, `CONTRAST`, `CONCLUSION`, `CTA`) and an episode-wide
decision (`KEEP`, `TRIM`, `REPLACE_TAKE`, `REVIEW_REQUIRED`). Semantic duplicate
detection compares the argument and narrative function across the entire
episode. A broad topic keyword alone is never sufficient for removal.

Only this layer may decide what viewer-facing speech is kept. The visual AI
Director is deliberately invoked after the speech timeline has been fixed.

## 5. Timeline builder

Artifact: `timeline_plan.json`.

Owns sequence, source/output time mapping, duration and semantic B-roll slots.
It contains no font, animation, camera or effect decisions. Speech compression
uses transcript/pause evidence, not visual Director events.

## 6. Caption engine

Artifact: `caption_plan.json`.

Owns normalized caption text, line wrapping, measured font geometry, face
avoidance and platform safe-area validation. For a 1080x1920 canvas the default
reserved UI margins are 104 px left, 150 px right, 96 px top and 300 px bottom.
The engine reflows, moves or scales the complete composition; it never clips it.

## 7. Visual polish

Artifacts: `director_plan.json`, `director_execution_plan.json`,
`clip_visual_plan.json`, `montage_plan.json`.

Owns typography role, animation, highlight, camera, B-roll execution, SFX and
other effects. It may not reinsert editorially removed speech or alter timeline
order. Remotion executes the resolved plan and does not invent semantic edits.

## 8. Quality control

Artifact: `quality_report.json`.

QC has three independent dimensions:

- content: structure and unresolved semantic duplicates;
- visual: measured safe area, face overlap, readability and effect density;
- technical: 1080x1920, 30 fps and post-render decode checks.

The final score includes all three, so a technically valid render cannot hide a
weak content map or unsafe caption layout.

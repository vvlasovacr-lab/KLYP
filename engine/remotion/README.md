# ShortsAI Remotion renderer

This is the deterministic renderer used by `python run.py`. Its only editorial
contract is `montage_plan.json`; runtime props also provide `chunks`, `sourceVideo`,
and typography `config`.

Supported text templates: `PHRASE_BUILD`, `KEYWORD_HERO`, `STACKED_TEXT`,
`SIDE_TEXT`, `NUMBER_HERO`, `TOP_CAPTION`, `QUOTE_CARD`, and `CONTRAST_SPLIT`.
Semantic scene roles remain `NORMAL`, `ACCENT`, `HERO`, `PUNCH`, `NUMBER`,
`CONTRAST`, and `TITLE`. Supported word motion includes `POP`, `BOUNCE`,
`SCALE_IN`, `SLIDE_UP`, `SLIDE_LEFT`, `SHAKE`, `PUNCH`, `FLASH`, and `ROTATE`.

Camera, visual, B-roll, and SFX events come only from the plan. Local missing assets
are disabled by the Python runner before render. No video-specific timestamps or
accent lists are stored in React components.

`EditedVideo.jsx` executes `speechEdit.timeline`: source ranges, jump cuts, and
playback-rate changes therefore stay synchronized with all retimed text scenes.

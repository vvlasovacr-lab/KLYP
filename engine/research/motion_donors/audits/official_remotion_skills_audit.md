# Official Remotion Skills Audit

Source: `remotion-dev/skills` at `b12104ef5f1b1ca2ca5590fcc7c1804fbc85556f`.

The skills were used as engineering reference only. Their repository license is unclear, so no source was copied.

| Area | Verdict | ShortsAI evidence / action |
|---|---|---|
| Frame-driven animation | ALREADY_GOOD | `useCurrentFrame()`, `spring()` and `interpolate()` are used; no CSS keyframes or wall-clock timing |
| Spring animation | IMPROVEMENT_CANDIDATE | Existing presets were coherent but impact shake used periodic sinusoids; replaced only that curve with deterministic decaying displacement |
| Text animation | ALREADY_GOOD | Word timestamps, active element, semantic roles, no karaoke recoloring, bounded word motion |
| Caption timing | ALREADY_GOOD | Whisper word timestamps and retimed transcript remain the source of timing |
| Safe zones | ALREADY_GOOD | 1080x1920 platform-safe box and preflight text bounding boxes are enforced before render |
| Text measurement | ALREADY_GOOD | Python preflight computes bounded layout against the exact selected font profile; `@remotion/layout-utils` would duplicate this and was not added |
| Local fonts | ALREADY_GOOD | Job-scoped local fonts, deterministic font profile selection, and runtime fallback checks already exist |
| Sequencing | ALREADY_GOOD | `Sequence` is used for timed events; semantic timeline remains external JSON |
| Transitions | IMPROVEMENT_CANDIDATE | Official `TransitionSeries` is useful for overlapping full scenes but would require timeline contract changes. Kept semantic registry and improved only existing `CONTROLLED_BLUR` math |
| Audio/SFX | ALREADY_GOOD | Local SFX, explicit cue timing, fades, cooldowns, and safe skip for missing files |
| Media primitives | ALREADY_GOOD | Existing renderer uses deterministic local media and avoids render-time network requests |
| Effects | NOT_RELEVANT for v1 RC | Official WebGL effects add GPU/server risk. No clear win over current CSS treatments for talking-head |
| Rendering determinism | ALREADY_GOOD | Persisted seed, no `Math.random`, no remote CDN dependency, complete decode checks |

Not adopted: constant animation on social hooks suggested by the prompt template. It conflicts with the ShortsAI visual-rest policy.

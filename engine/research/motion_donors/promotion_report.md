# Motion Donor Promotion Report

Final verdict: **DONOR_INTEGRATION_PARTIALLY_USEFUL**.

The stop condition was reached after two genuine wins. The audit did not force a
third promotion merely to reach the nominal 3–6 range.

## Promoted into the existing semantic API

1. **Deterministic decaying shake**
   - Semantic names remain `MICRO_SHAKE` / `SHAKE`.
   - Implementation now uses Remotion's seeded `random()` per local frame and a
     linear decay to a stable frame.
   - Production files: `remotion/src/effects/motion.js`,
     `remotion/src/Camera.jsx`.
   - Source pattern: Onda `CameraShake.tsx` at commit
     `3c814051269597b31fee1603bef7ccfb93d091b6` (MIT).

2. **Symmetric controlled blur**
   - Semantic name remains `CONTROLLED_BLUR`.
   - Blur now follows a contained sine arc: sharp → peak blur → sharp. The
     Director trigger, timing, and maximum blur value are unchanged.
   - Production file: `remotion/src/Camera.jsx`.
   - Source pattern: Onda blur transition at the same pinned MIT commit, checked
     against official Remotion transition conventions.

No donor component is imported directly. No donor font, image, logo, music, or
SFX was copied. No runtime dependency was added. Remotion stayed on `4.0.507`.

## Why only these two won

- Shake no longer resembles a periodic sine wobble; it creates impact, decays
  quickly, is deterministic, and preserves existing semantic cooldowns.
- Controlled blur no longer leaves a one-sided soft tail; it peaks at the event
  center and returns exactly to a sharp frame.
- Both changes remain local to the renderer, keep Cyrillic typography and safe
  zones untouched, and measured within 1.3% of the current short-composition
  render time.

The remaining candidates were equal, profile-mismatched, dependent on a missing
semantic contract, visually excessive, or license-unclear. See
`MOTION_DONOR_BACKLOG_V1_1.md` and `donor_registry.json`.

## Validation

- Unit/regression tests: **98/98 passed** (`95` existing + `3` donor contracts).
- Remotion composition bundling: passed; composition `Reel` discovered at
  1080×1920 / 30 fps.
- A/B previews: **22/22 fully decoded**.
- Frozen RC visual regression: Kitchen, RAW Episode, and Studio rendered from
  their exact existing `remotion_props.json` plans.
- POST files: **3/3 fully decoded**, H.264/AAC, 1080×1920, 30 fps.
- Same Director, transcript, timeline, B-roll, typography, fonts, source media,
  and semantic event plans were used. Only renderer motion math changed.

The ordinary end-to-end AUTO command was attempted, but the desktop sandbox
refused access to the installed user Python and the approval service had reached
its usage limit. To avoid bypassing that boundary, regression used the exact
frozen production props for all three RC jobs. This validates the changed visual
layer, but a future unrestricted run should repeat the full AUTO entrypoint.

## Performance

In 1.8-second 540×960 A/B compositions:

- decaying shake: 7.467 s current → 7.499 s donor (**+0.4%**);
- controlled blur: 7.550 s current → 7.450 s donor (**−1.3%**).

The production POST renders completed without runtime or decode failure. Cache
write warnings were environmental and non-fatal; the implementation has no GPU,
WebGL, network, or remote-CDN dependency.

## Regression output

- `output/showcase_motion_donor/pre/`: frozen RC videos.
- `output/showcase_motion_donor/post/`: renderer-regression videos.
- `output/showcase_motion_donor/ab/`: winning A/B snippets.
- `output/showcase_motion_donor/frames/`: nine representative POST frames.
- `output/showcase_motion_donor/motion_donor_ab.html`: visual inspector.

## A–Z final answers

**A.** ShortsAI uses Remotion `4.0.507`.

**B.** Remotion was not upgraded. The audited upstream packages were `4.0.508`,
but neither promoted improvement requires them.

**C–D.** Exact repositories and pinned revisions:

| Repository | Revision |
|---|---|
| `remotion-dev/remotion` | `c824c3b7c04a7a5ccf4292475a2e52d42f15515e` |
| `remotion-dev/skills` | `b12104ef5f1b1ca2ca5590fcc7c1804fbc85556f` |
| `remotion-dev/codex-plugin` | `87295e538e3761e0d592100af67a26afec8d50ef` |
| `remotion-dev/template-prompt-to-motion-graphics-saas` | `341afb0d9aa9d837cb58b9c802d89ac105a42a6c` |
| `degueba/onda` | `3c814051269597b31fee1603bef7ccfb93d091b6` |
| `reactvideoeditor/remotion-templates` | `6209b724798e48ff395f8df1a6fa2d26082372b5` |
| `av/remotion-bits` | `6c71169aa061f15313fadbdc6e29a3a3a87f2c03` |
| `lifeprompt-team/remotion-scenes` | `02c7a84241da7010b5f59c420b0110aafd1d6f0d` |

**E.** Confirmed license files: Onda MIT, Remotion Scenes MIT, Codex Plugin
MIT, and the special Remotion License for the official repository.

**F.** License concerns remain for `skills`, the prompt template, RVE
templates, and Remotion Bits because a repository-level license file was absent
or evidence existed only in README/package metadata. None of their code was
promoted. The Remotion License may require a company license depending on the
organization using it; see the dedicated license report.

**G.** 23 concrete components/patterns were inspected.

**H.** The 11-item shortlist was: soft reveal, phrase build, accent highlight,
number punch, decaying micro-shake, clean dissolve, controlled blur, clean push,
UI callout, subtle vignette, and rare whip-pan.

**I.** Official Remotion supplied compatibility and engineering references for
`spring`, `interpolate`, seeded `random`, effects, transitions, layout/text
measurement, fonts, media, and rendering. No official package was added.

**J.** Onda supplied the strongest reusable motion language: shared restraint,
fast settling, deterministic shake decay, contained blur, stagger/callout/stat
patterns, and one focal moment per scene.

**K.** RVE supplied useful recipe comparisons for camera shake, whip-pan,
dissolve, push, zoom-through, highlight, stat counter, notification, PiP, and
split screen. Whip-pan did not clear the visual or license bar.

**L.** Remotion Bits candidates reviewed included `BlurSlideWord`, `FadeIn`,
`WordByWord`, and its animated-text contract.

**M.** Remotion Scenes was reference-only for text-mask reveal, giant-number,
split-contrast, glow, toast, and UI-card composition patterns.

**N.** The Codex plugin was marked `NOT_NEEDED`: it duplicated the official
skills audit and was neither installed nor added to runtime.

**O.** Rejected: rare whip-pan.

**P.** Reference-only / keep-current: accent highlight, number punch, clean
dissolve, and subtle vignette. Soft reveal, phrase build, clean push, and UI
callout are backlog candidates rather than production promotions.

**Q.** All 11 candidates received an actual current-vs-donor render; 22 clips
were rendered and fully decoded.

**R.** Two primitives were promoted: deterministic decaying shake and symmetric
controlled blur.

**S.** Shake now feels like impact followed by rest instead of periodic motion;
blur now has an intentional midpoint peak and exact sharp settle. Both retain
the existing Director semantics and measured negligible render-time change.

**T.** Visual delivery is calmer after an impact: less residual trembling and
no lingering blur tail. Typography, composition, and content selection are
unchanged.

**U.** Promoted short-composition deltas were `+0.4%` for shake and `-1.3%` for
blur. This is inside the run-to-run noise band and introduces no material render
penalty.

**V.** New runtime dependencies: none.

**W.** No new server-render concern: no WebGL/GPU requirement, network access,
remote CDN, manual browser state, or unseeded randomness. The only warning seen
was a non-fatal local webpack-cache permission warning.

**X.** Kitchen, RAW Episode, and Studio passed frozen-plan visual renderer
regression. The ordinary AUTO entrypoint still needs one unrestricted rerun for
strict end-to-end confirmation because desktop approval limits blocked it.

**Y.** All three POST MP4 files and all 22 A/B MP4 files fully decode.

**Z.** The HTML inspector is at
`research/motion_donors/comparisons/motion_donor_ab.html` and is copied into
`output/showcase_motion_donor/motion_donor_ab.html`.

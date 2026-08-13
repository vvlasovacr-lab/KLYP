# GitHub Motion Donor Audit

Baseline: `PRE_MOTION_DONOR_RC` / frozen `TALKING_HEAD_V1_RC`.

## Exact repositories

| Repository | Branch | Commit | Commit date | Requirements | License verdict |
|---|---|---|---|---|---|
| remotion-dev/remotion | main | `c824c3b7c04a7a5ccf4292475a2e52d42f15515e` | 2026-08-12 | Node >=16, Bun 1.3.3; audited packages 4.0.508 | special Remotion License |
| remotion-dev/skills | main | `b12104ef5f1b1ca2ca5590fcc7c1804fbc85556f` | 2026-08-11 | package 4.0.508 | unclear |
| remotion-dev/codex-plugin | main | `87295e538e3761e0d592100af67a26afec8d50ef` | 2026-08-11 | Codex plugin 4.0.508; no runtime requirement | MIT |
| remotion-dev/template-prompt-to-motion-graphics-saas | main | `341afb0d9aa9d837cb58b9c802d89ac105a42a6c` | 2026-08-04 | React 19.2.1, Remotion ^4, Next 16.2.11 | unclear |
| degueba/onda | main | `3c814051269597b31fee1603bef7ccfb93d091b6` | 2026-06-16 | Node >=20, pnpm 9, React ^19, Remotion ^4.0.466 | MIT; trademark exclusion |
| reactvideoeditor/remotion-templates | main | `6209b724798e48ff395f8df1a6fa2d26082372b5` | 2026-04-21 | standalone Remotion recipes; no package metadata | unclear |
| av/remotion-bits | master | `6c71169aa061f15313fadbdc6e29a3a3a87f2c03` | 2026-03-11 | Node >=18, React >=18, Remotion >=4 | MIT metadata only; unclear notice evidence |
| lifeprompt-team/remotion-scenes | main | `02c7a84241da7010b5f59c420b0110aafd1d6f0d` | 2026-02-05 | Node 18+ (README), React 18+, Remotion 4+ | MIT |

## Scope reviewed

23 concrete components/patterns were inspected in source:

- Official Remotion: fade, linear blur, slide/push/zoom families, effect inventory, spring, layout fit helpers.
- Onda: motion tokens, blur reveal, word stagger, highlight, stat card, camera shake, callout, vignette, blur/push transitions.
- RVE templates: camera shake, whip pan, cross dissolve, push, zoom-through, text highlight, stat counter, notification pop, PiP/split screen.
- Remotion Bits: `BlurSlideWord`, `FadeIn`, `WordByWord`, animated-text contract.
- Remotion Scenes: `TextMaskReveal`, `LayoutGiantNumber`, `LayoutSplitContrast`, `EffectGlow`, UI toast/card categories.
- Prompt template: constants-first design, typography, sequencing, spring physics, social-safe guidance.

11 were shortlisted for real A/B; all 22 current/donor clips rendered and decoded.

## Repository verdicts

- Official Remotion: current core APIs are sufficient. No upgrade and no new package.
- Official skills: useful audit checklist; most ShortsAI practices are already good.
- Codex plugin: `NOT_NEEDED`. It duplicates the audited skills and is not required by production or this task.
- Onda: strongest donor. Useful motion language is restraint, shared timing, seeded decay, and one focal moment. Fonts/colors/branding were ignored.
- RVE templates: useful recipe catalog, but license evidence is insufficient and whip-pan failed visual A/B.
- Remotion Bits: searchable catalog was useful, but animated-text recipes overlap Onda/current behavior and the missing LICENSE file blocks promotion.
- Remotion Scenes: visual reference only; scenes are tied to a broader design system and some use heavier dependencies.
- Prompt template: constants-first and deterministic sequencing are compatible; its AI generation architecture is not relevant to the deterministic Director.

## A/B verdict

Promoted:

1. Existing `MICRO_SHAKE` / `SHAKE` implementation now uses deterministic seeded displacement and linear decay.
2. Existing `CONTROLLED_BLUR` transition now follows a symmetric contained blur arc and always returns to a sharp frame.

Backlog V1.1: `SOFT_REVEAL`, `PHRASE_BUILD`, `CLEAN_PUSH`, `UI_CALLOUT`.

KEEP_CURRENT: accent highlight, number punch, clean dissolve, vignette.

Rejected: rare whip-pan. It was over-blurred, composition-risky, and license-unclear.

See `comparisons/motion_donor_ab.html`, `performance/motion_performance_report.json`, and `donor_registry.json` for evidence.

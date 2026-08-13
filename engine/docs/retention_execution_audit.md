# Retention Decision Audit

## Scope

The existing pipeline is preserved:

```text
Whisper -> Speech Edit -> AI Director -> Execution Plan -> Visual Adapter -> Remotion
```

This audit changes decision quality only. It does not introduce another planner or move semantic decisions into Remotion.

## Problems found

1. AI Director treated semantic categories as effects. A MONEY, RESULT, PROBLEM or NUMBER label could directly produce ACCENT, B-roll, camera and SFX even when the whole thought was not visually important.
2. B-roll candidates were produced for nine of sixteen blocks. The asset planner reduced them later, but the Director intent was still noisy.
3. Retention score combined importance and a category bonus, but did not expose hook strength, information value, assertion strength, semantic change or visual importance.
4. Eleven of sixteen segments had camera movement. Normal and supporting passages did not get enough visual rest.
5. Some subtle camera actions happened underneath full-screen B-roll and therefore had no visible purpose.
6. Role alone selected several SFX pairs, causing seventeen audio actions in a 51-second video.
7. A first scoring revision accidentally increased speech compression. Compression was decoupled from visual scores and is now limited to long, low-information NORMAL blocks. Final duration is unchanged.

## Corrected decisions

Each semantic segment now contains:

- `hook_strength`
- `emotional_intensity`
- `information_value`
- `visual_importance`
- `assertion_strength`
- `semantic_change`
- combined `retention_score`
- combined `decision_strength`

HERO, NUMBER, ACCENT, camera, B-roll and SFX require appropriate score combinations. A semantic label is supporting evidence, not an automatic trigger.

## B-roll policy

- planning unit: semantic block;
- one request may contain multiple related search terms;
- minimum gap comes from the style profile and is never below the duration-aware safety floor;
- 30-60 second videos are capped to roughly 3-6 events, additionally bounded by the profile;
- nearby candidates compete by `broll_value`; the stronger block can replace a weaker one;
- failed asset resolution does not suppress a later candidate;
- a camera move hidden under B-roll is removed;
- missing or weak semantic asset matches remain unresolved and are skipped.

## Current video comparison

| Metric | Before | After |
|---|---:|---:|
| Director B-roll candidates | 9 | 4 |
| Resolved B-roll actions | 3 | 3 |
| Camera actions | 11 | 5 |
| Visual actions | 3 | 1 |
| Audio actions | 17 | 6 |
| Explicit calm segments | not tracked | 6 |
| Output duration | 51.636 s | 51.636 s |

The quality evaluator was also corrected. It previously rewarded an effect rate close to 0.42 events per second and ignored B-roll exits, camera returns and planned word-motion beats. That biased the score toward over-animation. The evaluator now counts executed visual changes and rewards a controlled range; the recalculated score is 0.967 with 0.232 major effects per second and a 4.592-second maximum meaningful static gap.

The important change is not merely the same final B-roll count. The Director now proposes four coherent blocks instead of nine keyword-driven opportunities, and the planner resolves three strong matches.

## Remaining limitations

- Scores are deterministic semantic heuristics, not an LLM judgment. They are auditable and stable, but nuanced irony or implicit emotion can be missed.
- The current local B-roll library has only three strong content groups; an unresolved NUMBER request is correctly skipped.
- Visual QA should next be repeated on calm expert content and a high-emotion source to tune thresholds across profiles without increasing event density globally.

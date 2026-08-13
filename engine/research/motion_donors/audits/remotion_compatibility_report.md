# Remotion Compatibility Report

## Frozen runtime

- Remotion: `4.0.507`
- React / React DOM: `19.2.8`
- Node: `24.14.0`
- pnpm: `11.16.0`
- lockfile SHA-256: `F906E0AB6C116270AD89C961A630BADD4C6BE7A73F3F0C6728DDDB92433A1D9F`

## Official repository snapshot

Commit `c824c3b7c04a7a5ccf4292475a2e52d42f15515e` contains Remotion packages at `4.0.508`:

| Feature/package | Current | Audited source | Potential breakage | Expected benefit | Decision |
|---|---:|---:|---|---|---|
| core `spring`, `interpolate`, `Easing`, seeded `random` | 4.0.507 | 4.0.508 | None when using current API | Sufficient for selected adaptations | USE CURRENT |
| `@remotion/transitions` | not installed | 4.0.508 | Adds packages and requires scene-overlap integration | Clean fades/slides; not clearly better in A/B | DO NOT INSTALL |
| `@remotion/effects` | not installed | 4.0.508 | WebGL/GPU/headless complexity; version mismatch | Many decorative effects | DO NOT INSTALL |
| `@remotion/layout-utils` | not installed | 4.0.508 | Duplicates existing caption preflight | Browser-side fit helpers | DO NOT INSTALL |
| media/audio utilities | transitive/current project paths | 4.0.508 | Version mismatch if added directly | No missing RC capability | KEEP CURRENT |

Remotion was **not upgraded**. The selected changes use only APIs already present in `4.0.507`.

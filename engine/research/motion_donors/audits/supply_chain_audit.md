# Supply-chain audit

- Eight repositories were shallow-cloned into `research/motion_donors/sources` and pinned by commit SHA.
- No donor `npm install`, `pnpm install`, CLI fetch, MCP server, build script, postinstall, prepack, or deploy script was run.
- Package scripts were inspected before any execution decision.
- The A/B harness reuses the frozen ShortsAI Remotion installation through local junctions; it downloads nothing at render time.
- No package from a donor was added to `remotion/package.json` or `pnpm-lock.yaml`.
- No production file imports from `research/motion_donors/sources`; this is enforced by `tests/test_motion_donor_contracts.py`.
- No donor branding, fonts, images, music, SFX, or sample data were promoted.

High-risk packages/features avoided: Three.js catalogs, WebGL effects, remote font/CDN loading, MCP/runtime services, full template design systems, and random/non-seeded animation.

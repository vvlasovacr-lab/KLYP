# Motion Donor Backlog V1.1

These candidates were visually useful but did not clear the production bar for
the frozen `TALKING_HEAD_V1_RC` profile.

| Candidate | Why it stays in backlog | Re-entry condition |
|---|---|---|
| `SOFT_REVEAL` | The donor entrance is calmer and more polished, but too slow and blurry for current `AGGRESSIVE_SOCIAL` speech. | Validate against `SOCIAL_CLEAN` or `PODCAST_PREMIUM` with real word timestamps. |
| `PHRASE_BUILD` | The four-frame stagger reads clearly, but may visually lag Whisper timing and can over-animate BODY captions. | Add profile-aware timing and prove no caption lag on three independent sources. |
| `CLEAN_PUSH` | Restrained motion is promising, but the current transition contract does not expose overlapping source/target scenes. | Introduce only if an existing semantic transition can support overlap without changing Director decisions. |
| `UI_CALLOUT` | Looks polished, but requires real evidence and anchor geometry; generic data would risk invented proof. | Promote only with transcript-backed facts and an explicit Director UI-proof action. |

No backlog candidate is imported by production code.

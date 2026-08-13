# Local media assets

- `broll/`: searchable local B-roll library. Subfolders and descriptive filenames become tags automatically.
- `sfx/`: optional `POP`, `WHOOSH`, `IMPACT`, and `CLICK` sounds.

For better matching, place an optional sidecar next to a clip: `clip.mp4.json`.

```json
{
  "description": "Business owner reviewing monthly revenue",
  "category": "business",
  "tags": ["деньги", "доход", "бизнес", "finance"],
  "focalPoint": {"x": 0.5, "y": 0.42}
}
```

`assets/broll/index.json` is rebuilt automatically. The renderer never selects a random asset; unmatched requests use the scene's camera fallback.
## Asset metadata

Any supported asset can have a JSON sidecar named `filename.ext.json`. Recommended fields are `category`, `topic`, `emotion`, `keywords`, `styles`, `importance`, `description` and (for B-roll) `focalPoint`.

Supported library groups include `broll`, `images`, `overlays`, `particles`, `light_leaks`, `glitch`, `film_grain`, `motion_graphics`, `sfx` and `music`. Missing optional groups never stop rendering.

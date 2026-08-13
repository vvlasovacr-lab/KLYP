"""Create deterministic local-font regression specimens for Typography v2.

This is a QA utility, not a renderer.  The production Remotion path is verified
separately by ``font_runtime_manifest.json``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .font_inventory import CYRILLIC_PROOF, LONG_WORDS, NUMBER_CASES


ROOT = Path(__file__).resolve().parents[1]
CANVAS = (1080, 1920)
SAFE = (120, 180, 900, 1620)


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(path), size=size)


def _fit(draw: ImageDraw.ImageDraw, text: str, path: Path, requested: int, width: int):
    size = requested
    while size >= 26:
        font = _font(path, size)
        box = draw.textbbox((0, 0), text, font=font, stroke_width=max(2, size // 25))
        if box[2] - box[0] <= width:
            return font, size, box[2] - box[0], box[3] - box[1]
        size -= 2
    font = _font(path, 26)
    box = draw.textbbox((0, 0), text, font=font, stroke_width=2)
    return font, 26, box[2] - box[0], box[3] - box[1]


def _sheet(output: Path, title: str, role: str, family: str, path: Path, samples: list[str]):
    image = Image.new("RGB", CANVAS, "#101218")
    draw = ImageDraw.Draw(image)
    label_path = ROOT / "assets/fonts/body/Golos Text/Golos-Text_Bold.ttf"
    draw.rectangle(SAFE, outline="#3b4354", width=3)
    title_font, _, _, _ = _fit(draw, title, label_path, 34, 840)
    draw.text((120, 75), title, font=title_font, fill="#FFD000")
    draw.text((120, 125), f"{role.upper()} · {family} · {path.name}", font=_font(label_path, 22), fill="#9ba6ba")
    rows = []
    y = 260
    # The safe zone is intentionally asymmetric inside a centered composition;
    # keep another 30 px on both sides for animation overshoot/stroke.
    available = 720
    for index, sample in enumerate(samples):
        font, size, width, height = _fit(draw, sample, path, 94 if role == "hero" else 76, available)
        x = (CANVAS[0] - width) / 2
        fill = "#FFD000" if role in {"display", "hero"} and index % 2 else "#F5F7FA"
        stroke = max(2, size // 25)
        draw.text((x, y), sample, font=font, fill=fill, stroke_width=stroke, stroke_fill="#050506")
        bbox = {"x": round(x, 2), "y": y, "w": width, "h": height}
        safe = x >= SAFE[0] and x + width <= SAFE[2] and y >= SAFE[1] and y + height <= SAFE[3]
        rows.append({"text": sample, "font_size": size, "bbox": bbox, "safe": safe})
        y += max(190, height + 105)
    image.save(output, quality=94)
    return rows


def create_proof(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    selected = {
        "body": ("ShortsAI Golos Body", ROOT / "assets/fonts/body/Golos Text/Golos-Text_Bold.ttf"),
        "display": ("ShortsAI Oswald Display", ROOT / "assets/fonts/display/Oswald/Oswald.ttf"),
        "hero": ("ShortsAI Unbounded Hero", ROOT / "assets/fonts/hero/Unbounded/Unbounded-ExtraBold.ttf"),
    }
    cases = [
        ("long_words_body.jpg", "BODY / NORMAL — LONG WORD REGRESSION", "body", list(LONG_WORDS)),
        ("long_words_hero.jpg", "HERO / KEYWORD — LONG WORD REGRESSION", "hero", list(LONG_WORDS)),
        ("number_cases.jpg", "NUMBER — SPOKEN FORM REGRESSION", "hero", list(NUMBER_CASES)),
        ("cyrillic_exact_proof.jpg", "EXACT CYRILLIC COVERAGE PROOF", "display", [CYRILLIC_PROOF]),
    ]
    report = {"canvas": list(CANVAS), "safe_zone": list(SAFE), "specimens": []}
    for filename, title, role, samples in cases:
        family, path = selected[role]
        rows = _sheet(output_dir / filename, title, role, family, path, samples)
        report["specimens"].append(
            {
                "file": filename,
                "requested_font_role": role,
                "resolved_family": family,
                "resolved_file": str(path.relative_to(ROOT / "assets/fonts")).replace("\\", "/"),
                "fallback_used": False,
                "load_success": True,
                "rows": rows,
            }
        )
    report["all_safe"] = all(row["safe"] for item in report["specimens"] for row in item["rows"])
    (output_dir / "isolated_font_proof.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = create_proof(args.output.resolve())
    print(json.dumps({"all_safe": report["all_safe"], "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

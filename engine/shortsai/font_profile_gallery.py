from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from .automated_pipeline import AutomatedPipeline
from .config import load_config
from .font_profile_selector import load_font_library, resolve_profile_variant
from .media import probe_media, resolve_ffmpeg, resolve_ffprobe
from .remotion_runner import RemotionRenderer
from .style_profiles import get_style_profile
from .text_composition import validate_text_compositions


def _words(text: str, start: float, end: float, emphasis: bool = False) -> list[dict[str, Any]]:
    tokens = text.split()
    step = (end - start) / max(1, len(tokens))
    return [{
        "word": token, "start": round(start + index * step, 3),
        "end": round(start + (index + 1) * step, 3), "role": "strong_emphasis" if emphasis and index == 0 else "ordinary",
        "effect": "POP" if emphasis and index == 0 else None, "intensity": 0.68 if emphasis and index == 0 else 0.18,
        "scale": 1.12 if emphasis and index == 0 else 1.0,
    } for index, token in enumerate(tokens)]


def _scene(index: int, start: float, end: float, role: str, template: str, text: str, component: str) -> tuple[dict[str, Any], dict[str, Any]]:
    strong = role in {"ACCENT", "HOOK", "HERO", "NUMBER"}
    words = _words(text, start, end, strong)
    scene = {
        "id": f"font-proof-{index}", "actionId": f"font-proof-{index}", "actionType": "text_action",
        "start": start, "end": end, "type": role, "semanticRole": role, "template": template,
        "text": text, "words": words, "emphasis": [0] if strong else [], "importance": 0.9 if strong else 0.55,
        "motionIntensity": 0.72 if strong else 0.22, "animation": "SPRING_IN" if role in {"HOOK", "HERO"} else "POP" if strong else "SLIDE_UP",
        "layout": {"position": "center_lower"}, "enabled": True,
    }
    if role == "NUMBER":
        scene["number"] = "70"
        scene["label"] = "ТЫСЯЧ"
        words[0]["category"] = "number"
    return scene, {"component": component}


def _proof_plan(style: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    definitions = [
        (0.0, 1.2, "HOOK", "STACKED_TEXT", "Почему ты всё ещё не миллионер?", "TITLE_COMPOSITION"),
        (1.2, 2.2, "NORMAL", "NORMAL", "Главное — сохранять фокус", "NORMAL"),
        (2.2, 3.3, "NORMAL", "PHRASE_BUILD", "Результат строится каждый день", "PHRASE_BUILD"),
        (3.3, 4.3, "ACCENT", "ACCENT_WORD", "ДИСЦИПЛИНА", "ACCENT_WORD"),
        (4.3, 5.4, "HERO", "KEYWORD_HERO", "ДИСЦИПЛИНА", "TITLE_COMPOSITION"),
        (5.4, 6.5, "NUMBER", "NUMBER_HERO", "70 ТЫСЯЧ", "NUMBER_STAMP"),
        (6.5, 7.6, "HERO", "KEYWORD_HERO", "5 ОШИБОК", "TITLE_COMPOSITION"),
        (7.6, 8.9, "NORMAL", "NORMAL", "ПРЕДПРИНИМАТЕЛЬ", "NORMAL"),
        (8.9, 10.2, "ACCENT", "ACCENT_WORD", "ЭФФЕКТИВНОСТЬ", "ACCENT_WORD"),
    ]
    scenes, scene_styles = [], {}
    for index, values in enumerate(definitions):
        scene, adapter = _scene(index, *values)
        scenes.append(scene); scene_styles[scene["actionId"]] = adapter
    validate_text_compositions(scenes, style, {"detected": False}, 1080, 1920, metrics)
    return {
        "version": 1, "output": {"duration": 10.2, "width": 1080, "height": 1920, "fps": 30},
        "styleProfile": style, "rendererMode": "hybrid", "speechEdit": {}, "audio": {"enabled": False},
        "face": {"detected": False}, "camera": [], "visual": [], "sfx": [], "broll": [],
        "execution": {"version": 2, "camera_actions": [], "visual_actions": [], "audio_actions": [], "broll_actions": []},
        "scenes": scenes, "visualAdapter": {"version": 1, "mode": "hybrid", "sceneStyles": scene_styles, "typography": {"accentMaxScale": 1.28}, "transitions": []},
        "config": {"cameraDrift": 0, "baseCameraScale": 1},
    }


def _write_html(root: Path, report: dict[str, Any]) -> None:
    cards = []
    for item in report["profiles"]:
        profile = item["font_profile_id"]
        images = "".join(f'<figure><img src="{profile}/{shot["file"]}"><figcaption>{shot["label"]} · {shot["time"]:.2f}s</figcaption></figure>' for shot in item["shots"])
        cards.append(f'''<section><h2>{profile} / {item["variant_id"]}</h2><p>{item["files"]["body"]}<br>{item["files"]["display"]}<br>{item["files"]["hero"]}</p><video controls src="{profile}/motion.mp4"></video><div class="grid">{images}</div></section>''')
    html = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>ShortsAI Production Font Library</title><style>body{{margin:0;background:#0b0d12;color:#f5f7fa;font:16px system-ui}}main{{max-width:1380px;margin:auto;padding:32px}}section{{background:#151923;border:1px solid #2b3342;border-radius:18px;padding:22px;margin:28px 0}}h1,h2{{color:#ffd000}}p{{color:#aab3c2;line-height:1.6}}video{{width:300px;max-height:540px;border-radius:12px}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:20px}}figure{{margin:0}}img{{width:100%;border-radius:10px}}figcaption{{padding:7px;color:#aab3c2}}@media(max-width:800px){{.grid{{grid-template-columns:1fr 1fr}}}}</style></head><body><main><h1>Production Font Style Library</h1><p>Одинаковый реальный фон, сцены, текст, timing и motion. Меняется только один job-level Font Profile. Все MP4 прошли реальный Remotion FontFace loading.</p>{''.join(cards)}</main></body></html>'''
    (root / "index.html").write_text(html, encoding="utf-8")


def build_gallery(config_path: Path, source: Path, output: Path) -> dict[str, Any]:
    config = load_config(config_path)
    renderer = RemotionRenderer(config)
    pipeline = AutomatedPipeline(config)
    ffmpeg = resolve_ffmpeg(config.render.ffmpeg)
    ffprobe = resolve_ffprobe(ffmpeg)
    media = probe_media(source, ffprobe)
    output.mkdir(parents=True, exist_ok=True)
    report = {"version": 1, "source": str(source.resolve()), "profiles": []}
    library = load_font_library(config.project_root / "font_profiles.json")
    settled = [("HOOK", 0.85), ("NORMAL", 1.75), ("PHRASE_BUILD", 2.85), ("ACCENT", 3.90), ("HERO", 4.95), ("NUMBER", 6.05), ("HERO_NUMBER", 7.15), ("LONG_WORD", 8.35), ("LONG_ACCENT", 9.65)]
    for profile_id, definition in library.items():
        variant_id = str(definition["default_variant"]).upper()
        font_profile = resolve_profile_variant(config.project_root / "font_profiles.json", config.assets_dir / "fonts", profile_id, variant_id)
        style = get_style_profile(config.project_root / "style_profiles.json", "AGGRESSIVE_SOCIAL")
        selection = {"font_profile_id": profile_id, "variant_id": variant_id, "seed": "gallery-fixed", "selection_reason": "controlled visual gallery", "font_fallbacks": 0}
        style.update({"font_profile": profile_id, "fontProfile": font_profile, "fontSelection": selection})
        plan = _proof_plan(style, pipeline._text_metrics(style))
        profile_root = output / profile_id
        runtime_root = output / "_runtime" / profile_id
        if runtime_root.exists(): shutil.rmtree(runtime_root)
        for directory in (runtime_root / "artifacts", runtime_root / "temp", runtime_root / "output"):
            directory.mkdir(parents=True, exist_ok=True)
        video = profile_root / "motion.mp4"; profile_root.mkdir(parents=True, exist_ok=True)
        renderer.render(source, media, [], plan, runtime_root, video, f"font-gallery-{profile_id.lower()}")
        runtime_path = runtime_root / "artifacts" / "font_runtime_manifest.json"
        runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
        shutil.copy2(runtime_path, profile_root / "font_runtime_manifest.json")
        shots = []
        for index, (label, timestamp) in enumerate(settled, start=1):
            filename = f"{index:02d}_{label.lower()}.jpg"
            subprocess.run([str(ffmpeg), "-hide_banner", "-loglevel", "error", "-y", "-ss", str(timestamp), "-i", str(video), "-frames:v", "1", "-q:v", "2", str(profile_root / filename)], check=True)
            shots.append({"label": label, "time": timestamp, "file": filename})
        report["profiles"].append({
            "font_profile_id": profile_id, "variant_id": variant_id,
            "files": {role: font_profile["font_assets"][role]["relativePath"] for role in ("body", "display", "hero")},
            "weights": {role: font_profile[f"{role}_profile"]["weight"] for role in ("body", "display", "hero")},
            "runtime_fallbacks": runtime.get("fallback_count"), "render_success": runtime.get("render_success"),
            "shots": shots,
        })
    (output / "font_profile_gallery.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_html(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--source", type=Path, default=Path("input/video.mp4"))
    parser.add_argument("--output", type=Path, default=Path("output/production_font_library_gallery"))
    args = parser.parse_args()
    report = build_gallery(args.config.resolve(), args.source.resolve(), args.output.resolve())
    print(json.dumps({"profiles": len(report["profiles"]), "output": str(args.output.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from typing import Any

from .config import AppConfig
from .media import MediaInfo
from .style_profiles import merge_render_style
from .font_inventory import build_font_manifest, resolve_manifest_font


# Windows зовёт бинарники через .cmd, Linux и macOS — напрямую.
# Раньше расширение было зашито, и на сервере рендер не запускался вовсе.
_WINDOWS = os.name == "nt"
_BIN_SUFFIX = ".cmd" if _WINDOWS else ""


def _installer() -> list[str] | None:
    """Чем ставить зависимости Remotion: чем угодно, что есть в системе."""
    for name in ("pnpm", "npm"):
        found = shutil.which(name)
        if found:
            return [found, "install"]
    return None


def _runtime_paths() -> tuple[Path | None, list[str] | None]:
    node_path = shutil.which("node")
    node = Path(node_path).resolve() if node_path else None

    bundled = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies"
    bundled_node = bundled / "node" / "bin" / ("node.exe" if _WINDOWS else "node")

    return (
        node if node and node.is_file() else bundled_node if bundled_node.is_file() else None,
        _installer(),
    )


def _hardlink_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


class RemotionRenderer:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.project = (config.project_root / config.remotion.project_dir).resolve()
        self.public_jobs = (self.project / "public" / "jobs").resolve()

    def _ensure_dependencies(self, env: dict[str, str], installer: list[str] | None) -> Path:
        binaries = self.project / "node_modules" / ".bin"
        cli = binaries / f"remotion{_BIN_SUFFIX}"
        esbuild = binaries / f"esbuild{_BIN_SUFFIX}"

        if not (cli.is_file() and esbuild.is_file()):
            if installer is None:
                raise RuntimeError(
                    "Зависимости Remotion не установлены, а ни pnpm, ни npm не найдены в PATH"
                )
            subprocess.run(installer, cwd=self.project, env=env, check=True)

        if not cli.is_file():
            raise RuntimeError(f"После установки не нашёлся {cli}")
        return cli

    @staticmethod
    def _safe_asset(root: Path, file_value: Any) -> Path | None:
        if not file_value:
            return None
        root = root.resolve()
        candidate = (root / str(file_value)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate if candidate.is_file() else None

    def _stage_plan_assets(self, plan: dict[str, Any], stage: Path, public_prefix: str) -> None:
        execution = plan.get("execution", {})
        execution_active = int(execution.get("version", 0)) >= 2
        sfx_events = execution.get("audio_actions", []) if execution_active else plan.get("sfx", [])
        broll_events = execution.get("broll_actions", []) if execution_active else plan.get("broll", [])
        visual_events = execution.get("visual_actions", []) if execution_active else plan.get("visual", [])
        music = plan.get("audio", {}).get("music")
        if music and music.get("enabled"):
            asset = self._safe_asset(self.config.assets_dir / "music", music.get("track"))
            if asset is None:
                music["enabled"] = False
            else:
                destination = stage / "music" / asset.name
                _hardlink_or_copy(asset, destination)
                music["src"] = f"{public_prefix}/music/{asset.name}"
        last_sfx_by_cue: dict[str, float] = {}
        for event in sorted(sfx_events, key=lambda item: float(item.get("time", 0))):
            cue = str(event.get("type", "")).upper()
            if cue not in {"POP", "WHOOSH", "IMPACT", "CLICK", "BASS_HIT"}:
                event["enabled"] = False
                continue
            file_value = event.get("file") or f"{cue.lower()}/{cue.lower()}.wav"
            asset = self._safe_asset(self.config.assets_dir / "sfx", file_value)
            timestamp = float(event.get("time", 0))
            if asset is None or timestamp - last_sfx_by_cue.get(cue, -100.0) < self.config.remotion.sfx_min_gap:
                event["enabled"] = False
                continue
            destination = stage / "sfx" / asset.name
            _hardlink_or_copy(asset, destination)
            event["src"] = f"{public_prefix}/sfx/{asset.name}"
            event["enabled"] = True
            last_sfx_by_cue[cue] = timestamp

        for event in broll_events:
            staged_shots: list[dict[str, Any]] = []
            for shot in event.get("shots", [event]):
                asset = self._safe_asset(self.config.assets_dir / "broll", shot.get("file"))
                if asset is None:
                    continue
                relative = asset.relative_to((self.config.assets_dir / "broll").resolve())
                destination = stage / "broll" / relative
                if not destination.exists():
                    _hardlink_or_copy(asset, destination)
                shot["src"] = f"{public_prefix}/broll/{relative.as_posix()}"
                staged_shots.append(shot)
            if event.get("shots") is not None:
                event["shots"] = staged_shots
            elif staged_shots:
                event.update(staged_shots[0])
            event["enabled"] = bool(staged_shots)

        for event in visual_events:
            if str(event.get("type", "")).upper() not in {"IMAGE", "ICON", "GIF", "MEME"}:
                continue
            asset = self._safe_asset(self.config.assets_dir, event.get("file"))
            if asset is None:
                event["enabled"] = False
                continue
            destination = stage / "visual" / asset.name
            _hardlink_or_copy(asset, destination)
            event["src"] = f"{public_prefix}/visual/{asset.name}"
            event["enabled"] = True

    def _stage_font_assets(
        self, style: dict[str, Any], stage: Path, public_prefix: str,
    ) -> dict[str, Any]:
        assets = style.get("font", {}).get("assets", {})
        runtime: dict[str, Any] = {
            "version": 2, "profile": style.get("profileName"),
            "font_selection": copy.deepcopy(style.get("fontSelection", {})),
            "fonts": [], "scenes": [], "font_role_fallbacks": [],
            "warnings": [], "fallback_count": 0, "typography_qc_penalty": 0.0,
        }
        if not assets:
            runtime["warnings"].append({
                "code": "EMERGENCY_SYSTEM_FONT_FALLBACK",
                "message": "No validated project-local font assets were resolved for this render",
            })
            runtime["fallback_count"] = 1
            runtime["typography_qc_penalty"] = 0.18
            return runtime
        fonts_root = (self.config.assets_dir / "fonts").resolve()
        manifest = build_font_manifest(fonts_root, fonts_root / "font_manifest.json")
        for role, asset in assets.items():
            relative = str(asset.get("relativePath", ""))
            source, record = resolve_manifest_font(fonts_root, manifest, relative)
            if source is None or record is None:
                status = record.get("validation_status") if record else "NOT_FOUND"
                raise ValueError(f"Local font {role} rejected: {relative} ({status})")
            destination = stage / "fonts" / f"{record['sha256'][:16]}{source.suffix.lower()}"
            _hardlink_or_copy(source, destination)
            asset.update({
                "src": f"{public_prefix}/fonts/{destination.name}",
                "resolvedFamily": str(asset.get("alias") or record["family"]),
                "resolvedFile": relative,
                "validationStatus": record["validation_status"],
                "cyrillicSupport": bool(record["cyrillic_support"]),
                "variable": bool(record.get("variable_font")),
                "loadSuccess": None,
                "fallbackUsed": False,
            })
            runtime["fonts"].append({
                "requested_font_role": role,
                "resolved_family": asset["resolvedFamily"],
                "resolved_file": relative,
                "staged_src": asset["src"],
                "weight": int(asset.get("weight", record.get("weight") or 400)),
                "variable": bool(record.get("variable_font")),
                "cyrillic_support": True,
                "validation_status": record["validation_status"],
                "fallback_used": False,
                "load_success": None,
            })
        role_map = style.get("font", {}).get("roleMap", {})
        return runtime | {"role_map": role_map}

    @staticmethod
    def _font_scene_manifest(plan: dict[str, Any], style: dict[str, Any], runtime: dict[str, Any]) -> None:
        assets = style.get("font", {}).get("assets", {})
        role_map = style.get("font", {}).get("roleMap", {})
        for scene in plan.get("scenes", []):
            semantic_role = str(scene.get("semanticRole", scene.get("type", "NORMAL"))).upper()
            measured_role = scene.get("layout", {}).get("compositionSafety", {}).get("font_profile")
            requested = str(measured_role or role_map.get(semantic_role, "hero" if semantic_role in {"HOOK", "HERO", "NUMBER", "PUNCH"} else "body"))
            asset = assets.get(requested, {})
            geometry = scene.get("layout", {}).get("compositionSafety", {})
            record = {
                "scene_start": scene.get("start"), "scene_end": scene.get("end"),
                "scene_type": semantic_role, "template": scene.get("template"),
                "text": scene.get("text"), "requested_font_role": requested,
                "resolved_family": asset.get("resolvedFamily"),
                "resolved_file": asset.get("resolvedFile"),
                "fallback_used": bool(asset.get("fallbackUsed", not bool(asset))),
                "load_success": asset.get("loadSuccess"),
                "rendered_font_size": geometry.get("font_size"),
                "font_weight": geometry.get("font_weight"),
                "stroke_px": geometry.get("stroke_px"), "shadow_px": geometry.get("shadow_px"),
                "line_height": geometry.get("line_height"), "tracking": geometry.get("tracking"),
                "line_count": geometry.get("line_count"),
                "final_bounding_box_px": geometry.get("bounding_box_px"),
            }
            scene["fontRuntime"] = record
            runtime["scenes"].append(record)
            if record["fallback_used"]:
                runtime["font_role_fallbacks"].append({
                    "scene_start": scene.get("start"), "scene_type": semantic_role,
                    "requested_role": requested, "resolved_family": record["resolved_family"],
                    "reason": "requested role asset was unavailable",
                })
        runtime["fallback_count"] = max(
            int(runtime.get("fallback_count", 0)), len(runtime.get("font_role_fallbacks", [])),
        )
        if runtime["fallback_count"]:
            runtime["typography_qc_penalty"] = max(
                float(runtime.get("typography_qc_penalty", 0.0)),
                min(0.30, 0.08 * runtime["fallback_count"]),
            )

    def render(
        self,
        source: Path,
        media: MediaInfo,
        chunks: list[dict[str, Any]],
        montage_plan: dict[str, Any],
        workspace: Path,
        output: Path,
        job_id: str,
    ) -> float:
        if not self.project.is_dir():
            raise RuntimeError(f"Remotion project not found: {self.project}")
        node, installer = _runtime_paths()
        if node is None:
            raise RuntimeError("Node.js не найден в PATH")
        env = os.environ.copy()
        env["PATH"] = str(node.parent) + os.pathsep + env.get("PATH", "")
        cli = self._ensure_dependencies(env, installer)

        self.public_jobs.mkdir(parents=True, exist_ok=True)
        stage = (self.public_jobs / job_id).resolve()
        try:
            stage.relative_to(self.public_jobs)
        except ValueError as error:
            raise RuntimeError("Unsafe Remotion staging path") from error
        if stage.exists():
            shutil.rmtree(stage)
        stage.mkdir(parents=True)

        try:
            staged_source = stage / f"source{source.suffix.lower()}"
            _hardlink_or_copy(source, staged_source)
            public_prefix = f"jobs/{job_id}"
            render_plan = copy.deepcopy(montage_plan)
            self._stage_plan_assets(render_plan, stage, public_prefix)
            style = json.loads((self.project / "src" / "styles" / "config.json").read_text(encoding="utf-8"))
            subtitle_style = self.config.subtitles
            style.setdefault("font", {}).setdefault("families", {})["body"] = list(subtitle_style.font_families)
            style["font"]["families"]["display"] = list(subtitle_style.hero_font_families)
            style["font"]["families"]["punch"] = list(subtitle_style.hero_font_families)
            style["fontSize"] = {
                "normal": subtitle_style.font_size,
                "accent": round(subtitle_style.font_size * subtitle_style.accent_scale),
                "hero": subtitle_style.hero_font_size,
                "punch": round(subtitle_style.hero_font_size * 1.18),
            }
            style["outline"] = subtitle_style.outline
            style.setdefault("shadow", {}).update({
                "y": subtitle_style.shadow,
                "blur": round(subtitle_style.shadow * 2.5),
            })
            composition = self.config.text_composition
            style["safeZone"] = {
                "horizontal": composition.horizontal_margin,
                "topMargin": composition.top_margin,
                "bottomMargin": composition.bottom_margin,
                "animationPadding": composition.animation_padding,
            }
            style = merge_render_style(style, render_plan.get("styleProfile", {"name": "MONEY"}))
            font_runtime = self._stage_font_assets(style, stage, public_prefix)
            self._font_scene_manifest(render_plan, style, font_runtime)
            font_runtime_path = workspace / "artifacts" / "font_runtime_manifest.json"
            font_runtime_path.parent.mkdir(parents=True, exist_ok=True)
            font_runtime_path.write_text(json.dumps(font_runtime, ensure_ascii=False, indent=2), encoding="utf-8")
            props = {
                "chunks": chunks,
                "montagePlan": render_plan,
                "sourceVideo": {
                    "src": f"{public_prefix}/{staged_source.name}",
                    "duration": media.duration,
                    "width": media.width,
                    "height": media.height,
                    "fps": media.fps,
                    "hasAudio": media.has_audio,
                },
                "config": style,
            }
            props_path = workspace / "temp" / "remotion_props.json"
            props_path.parent.mkdir(parents=True, exist_ok=True)
            props_path.write_text(json.dumps(props, ensure_ascii=False, indent=2), encoding="utf-8")
            output.parent.mkdir(parents=True, exist_ok=True)
            command = [
                str(cli), "render", "src/index.jsx", "Reel", str(output.resolve()),
                f"--props={props_path.resolve()}", f"--codec={self.config.remotion.codec}",
                f"--crf={self.config.remotion.crf}",
            ]
            started = time.perf_counter()
            subprocess.run(command, cwd=self.project, env=env, check=True)
            for item in font_runtime.get("fonts", []):
                item["load_success"] = True
            for item in font_runtime.get("scenes", []):
                item["load_success"] = True
            font_runtime["render_success"] = True
            font_runtime_path.write_text(json.dumps(font_runtime, ensure_ascii=False, indent=2), encoding="utf-8")
            return time.perf_counter() - started
        except Exception:
            output.unlink(missing_ok=True)
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)

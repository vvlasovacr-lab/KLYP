from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys

from shortsai.automated_pipeline import AutomatedPipeline
from shortsai.broll_library import build_broll_library
from shortsai.config import load_config
from shortsai.discovery import discover_videos
from shortsai.media import resolve_ffmpeg, resolve_ffprobe


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ShortsAI automatic Whisper -> Remotion pipeline")
    parser.add_argument("--config", type=Path, help="Config JSON (default: ./config.json)")
    parser.add_argument("--file", type=Path, help="Process one source video")
    parser.add_argument("--preview", action="store_true", help="Build work artifacts and preview_events.json without rendering")
    parser.add_argument("--debug", action="store_true", help="Create Director Inspector JSON/HTML (never changes the MP4)")
    parser.add_argument("--force", action="store_true", help="Reprocess even when an idempotent valid output exists")
    parser.add_argument(
        "--episodes", help="Optional raw-session child ids for regression, e.g. 001,002,004",
    )
    parser.add_argument(
        "--style",
        help="Style profile: AUTO, AGGRESSIVE_RED, CLEAN_YELLOW, PODCAST (default from config.json)",
    )
    parser.add_argument(
        "--renderer-mode", choices=("legacy", "hybrid"),
        help="Remotion visual execution: legacy or Clip-inspired hybrid (default from config.json)",
    )
    parser.add_argument("--index-broll", action="store_true", help="Rebuild assets/broll/index.json and exit")
    return parser


def _selected_videos(config, requested: Path | None) -> list[Path]:
    if requested is None:
        return discover_videos(config.input_dir, config.video_extensions)
    path = requested if requested.is_absolute() else (config.project_root / requested)
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Video not found: {path}")
    if path.suffix.lower() not in set(config.video_extensions):
        raise ValueError(f"Unsupported video extension: {path.suffix}")
    return [path]


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        if args.index_broll:
            ffmpeg = resolve_ffmpeg(config.render.ffmpeg)
            library = build_broll_library(config.assets_dir / "broll", resolve_ffprobe(ffmpeg))
            print(f"B-roll library: {config.assets_dir / 'broll'}")
            print(f"Indexed clips: {len(library['assets'])}")
            print(f"Errors: {len(library['errors'])}")
            for error in library["errors"]:
                print(f"ERROR: {error['file']}: {error['error']}", file=sys.stderr)
            return 0 if not library["errors"] else 1
        videos = _selected_videos(config, args.file)
        if not videos:
            print(f"No supported videos found in {config.input_dir}")
            return 0
        pipeline = AutomatedPipeline(config)
        print(f"Mode: {'preview' if args.preview else 'render'}")
        print(f"Videos: {len(videos)}")
        results = pipeline.run(
            videos, preview=args.preview, force=args.force, style_name=args.style,
            renderer_mode=args.renderer_mode, debug=args.debug,
            episode_ids={f"episode-{int(value):03d}" for value in re.findall(r"\d+", args.episodes)} if args.episodes else None,
        )
        manifest = pipeline.write_manifest(results, preview=args.preview)
    except Exception as error:
        print(f"Startup error: {type(error).__name__}: {error}", file=sys.stderr)
        return 2

    for result in results:
        if result.success:
            print(
                f"{result.status.upper()}: {Path(result.input).name} | "
                f"duration={result.duration:.2f}s blocks={result.retimed_blocks} "
                f"scenes={sum(result.summary.get(key, 0) for key in ('NORMAL','ACCENT','HERO','PUNCH','NUMBER','CONTRAST','TITLE'))} "
                f"render={result.render_time:.1f}s output={result.output or '-'}"
            )
            print(f"  job={result.job_id} artifacts={result.workspace}")
            for child in result.children or []:
                print(
                    f"  {child['episode_id']}: {str(child['status']).upper()} "
                    f"source={float(child.get('source_start') or 0):.1f}-{float(child.get('source_end') or 0):.1f}s "
                    f"duration={float(child.get('final_duration') or 0):.1f}s "
                    f"profile={child.get('profile') or '-'} output={child.get('output') or '-'}"
                )
        else:
            print(f"ERROR: {Path(result.input).name}: {result.error}", file=sys.stderr)
    succeeded = sum(result.success for result in results)
    print(f"Completed: {succeeded}/{len(results)}")
    print(f"Manifest: {manifest}")
    return 0 if succeeded == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

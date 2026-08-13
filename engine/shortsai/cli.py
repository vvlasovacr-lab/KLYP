from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import load_config
from .pipeline import Pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="py -m shortsai",
        description="Batch transcription and subtitling for videos in the input directory.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to a JSON configuration file (default: ./config.json)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List discovered videos without processing them",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        pipeline = Pipeline(config)
        videos = pipeline.discover()
    except (OSError, ValueError, TypeError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        return 2

    print(f"Input:  {config.input_dir}")
    print(f"Output: {config.output_dir}")
    print(f"Found videos: {len(videos)}")
    if args.list:
        for video in videos:
            print(f"- {video}")
        return 0
    if not videos:
        print("Nothing to process.")
        return 0

    results = [pipeline.process_one(video) for video in videos]
    for result in results:
        if result.success:
            print(f"OK: {result.source.name} -> {result.output}")
        else:
            print(f"ERROR: {result.source.name}: {result.error}", file=sys.stderr)

    succeeded = sum(result.success for result in results)
    print(f"Completed: {succeeded}/{len(results)}")
    return 0 if succeeded == len(results) else 1

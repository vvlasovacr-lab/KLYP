"""Compatibility entry point for the primary ShortsAI Remotion pipeline.

Use ``python run.py`` for new automation. This wrapper remains so existing local
commands do not fall back to the legacy ASS renderer.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from run import main as run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compatibility wrapper for python run.py")
    parser.add_argument("--input", type=Path, help="One source video (equivalent to run.py --file)")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--style", help="Style profile name")
    parser.add_argument("--renderer-mode", choices=("legacy", "hybrid"))
    args = parser.parse_args(argv)
    forwarded: list[str] = []
    if args.input:
        forwarded.extend(("--file", str(args.input)))
    if args.preview:
        forwarded.append("--preview")
    if args.debug:
        forwarded.append("--debug")
    if args.force:
        forwarded.append("--force")
    if args.style:
        forwarded.extend(("--style", args.style))
    if args.renderer_mode:
        forwarded.extend(("--renderer-mode", args.renderer_mode))
    return run_pipeline(forwarded)


if __name__ == "__main__":
    raise SystemExit(main())

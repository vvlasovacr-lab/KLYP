from __future__ import annotations

import argparse
from pathlib import Path
import sys

from shortsai.config import load_config
from shortsai.reference_evaluation import ReferenceEvaluator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="ShortsAI offline Reference Intelligence and calibration evaluation")
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--dataset", type=Path, default=Path("reference_dataset"))
    parser.add_argument("--build-candidate", action="store_true", help="Build isolated calibration candidate; never changes production config")
    parser.add_argument("--render-comparison", action="store_true", help="Render SOURCE / REFERENCE / BEFORE / AFTER comparison")
    parser.add_argument("--force-baseline", action="store_true", help="Force a fresh ordinary AUTO baseline render")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config.resolve())
        dataset = args.dataset.resolve()
        result = ReferenceEvaluator(config, dataset).run(
            build_candidate=args.build_candidate or args.render_comparison,
            render_comparison=args.render_comparison,
            force_baseline=args.force_baseline,
        )
    except Exception as error:
        print(f"Reference evaluation failed: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    print(f"References: {result['manifest']['objects']}")
    print(f"RAW-to-FINAL pairs: {result['manifest']['raw_to_final_pairs']}")
    print(f"Final-only: {result['manifest']['final_only']}")
    print(f"Source files unchanged: {result['source_files_unchanged']}")
    print(f"Production changed: {result['production_configuration_changed']}")
    print(f"Output: {config.output_dir / 'reference_analysis'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

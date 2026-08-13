from __future__ import annotations

import argparse
from pathlib import Path
import sys

from shortsai.automated_pipeline import AutomatedPipeline
from shortsai.config import load_config
from shortsai.evaluation import run_batch_evaluation, write_batch_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the production ShortsAI pipeline for an evaluation directory")
    parser.add_argument("--config", type=Path, help="Config JSON (default: ./config.json)")
    parser.add_argument("--input", type=Path, default=Path("input_tests"), help="Test or holdout directory")
    parser.add_argument("--report-dir", type=Path, help="Report directory (default: logs/batch/<timestamp handled per run>)")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Also create a Director Inspector for each job")
    parser.add_argument("--style", help="Optional fixed style profile; AUTO remains the default")
    parser.add_argument("--renderer-mode", choices=("legacy", "hybrid"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config)
        input_dir = args.input if args.input.is_absolute() else config.project_root / args.input
        pipeline = AutomatedPipeline(config)
        results, report = run_batch_evaluation(
            pipeline, input_dir.resolve(), force=args.force, style_name=args.style,
            renderer_mode=args.renderer_mode, debug=args.debug,
        )
        report_dir = args.report_dir
        if report_dir is None:
            ids = [result.job_id for result in results if result.job_id]
            run_name = ids[0].split("_")[0] if ids else "empty"
            report_dir = config.logs_dir / "batch" / run_name
        elif not report_dir.is_absolute():
            report_dir = config.project_root / report_dir
        json_path, html_path = write_batch_report(report, report_dir.resolve())
    except Exception as error:
        print(f"Batch startup error: {type(error).__name__}: {error}", file=sys.stderr)
        return 2
    for result in results:
        print(f"{result.status.upper()}: {Path(result.input).name} job={result.job_id} output={result.output or '-'}")
        if result.error:
            print(f"  {result.error}", file=sys.stderr)
    print(f"Processed: {report['processed']}; completed: {report['completed']}; failed: {report['failed']}")
    print(f"JSON report: {json_path}")
    print(f"HTML report: {html_path}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

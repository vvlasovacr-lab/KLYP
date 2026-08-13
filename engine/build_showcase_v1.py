from __future__ import annotations

import argparse
from pathlib import Path

from shortsai.release_candidate import ReleaseCase, build_showcase


def _pairs(values: list[str]) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for value in values:
        label, separator, path = value.partition("=")
        if not separator or not label or not path:
            raise ValueError(f"Expected LABEL=JOB_PATH, received: {value}")
        result[label] = Path(path).resolve()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Build TALKING_HEAD_V1_RC visual showcase from completed AUTO jobs")
    parser.add_argument("--job", action="append", default=[], help="LABEL=AFTER_JOB_PATH")
    parser.add_argument("--before", action="append", default=[], help="LABEL=BEFORE_JOB_PATH")
    parser.add_argument("--ffmpeg", type=Path, default=Path("C:/ffmpeg/bin/ffmpeg.exe"))
    args = parser.parse_args()
    jobs, before = _pairs(args.job), _pairs(args.before)
    if len(jobs) < 3:
        raise SystemExit("At least three real completed AUTO jobs are required")
    cases = [ReleaseCase(label, path, before.get(label)) for label, path in jobs.items()]
    report = build_showcase(Path(__file__).resolve().parent, cases, args.ffmpeg.resolve())
    print(f"{report['verdict']}: {report['real_sources']} sources")
    print(Path(__file__).resolve().parent / "output" / "showcase_v1" / "showcase_inspector.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

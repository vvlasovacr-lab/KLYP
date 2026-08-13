from __future__ import annotations

from pathlib import Path
from typing import Iterable


def discover_videos(input_dir: Path, extensions: Iterable[str]) -> list[Path]:
    """Return all supported videos below input_dir in deterministic order."""
    if not input_dir.exists():
        input_dir.mkdir(parents=True, exist_ok=True)
        return []
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input path is not a directory: {input_dir}")

    supported = {extension.lower() for extension in extensions}
    return sorted(
        (path for path in input_dir.rglob("*") if path.is_file() and path.suffix.lower() in supported),
        key=lambda path: str(path).lower(),
    )

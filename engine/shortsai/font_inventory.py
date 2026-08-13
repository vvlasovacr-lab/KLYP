from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import struct
from typing import Any, Iterable


CYRILLIC_PROOF = "ДЕНЬГИ 70 ТЫСЯЧ — ДИСЦИПЛИНА / РЕЗУЛЬТАТ №5 ₽"
LONG_WORDS = ("ДИСЦИПЛИНА", "ПРЕДПРИНИМАТЕЛЬ", "ЭФФЕКТИВНОСТЬ", "ВОЗМОЖНОСТИ")
NUMBER_CASES = ("70 ТЫСЯЧ", "100 000 ₽", "5 ОШИБОК", "2X")
REQUIRED_CHARACTERS = tuple(sorted(set(CYRILLIC_PROOF + "".join(LONG_WORDS) + "".join(NUMBER_CASES)) - {" "}))


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


@dataclass(frozen=True)
class SfntFont:
    path: Path
    data: bytes
    tables: dict[str, tuple[int, int]]

    @classmethod
    def open(cls, path: Path) -> "SfntFont":
        data = path.read_bytes()
        if len(data) < 12 or data[:4] not in {b"OTTO", b"true", b"typ1", b"\x00\x01\x00\x00"}:
            raise ValueError("unsupported or corrupt sfnt signature")
        count = _u16(data, 4)
        tables: dict[str, tuple[int, int]] = {}
        for index in range(count):
            base = 12 + index * 16
            if base + 16 > len(data):
                raise ValueError("truncated sfnt table directory")
            tag = data[base:base + 4].decode("latin-1")
            offset, length = _u32(data, base + 8), _u32(data, base + 12)
            if offset + length <= len(data):
                tables[tag] = (offset, length)
        return cls(path=path, data=data, tables=tables)

    def table(self, tag: str) -> tuple[int, int]:
        if tag not in self.tables:
            raise ValueError(f"missing {tag} table")
        return self.tables[tag]

    def names(self) -> dict[int, str]:
        offset, length = self.table("name")
        data = self.data
        count, string_offset = _u16(data, offset + 2), _u16(data, offset + 4)
        values: dict[int, list[tuple[int, int, int, str]]] = {}
        for index in range(count):
            record = offset + 6 + index * 12
            if record + 12 > offset + length:
                continue
            platform, encoding, language, name_id, size, relative = struct.unpack_from(">6H", data, record)
            start = offset + string_offset + relative
            raw = data[start:start + size]
            try:
                text = raw.decode("utf-16-be" if platform in {0, 3} else "mac_roman").strip("\x00 ")
            except (UnicodeDecodeError, LookupError):
                continue
            if text:
                values.setdefault(name_id, []).append((platform, language, encoding, text))
        result: dict[int, str] = {}
        for name_id, candidates in values.items():
            candidates.sort(key=lambda item: (item[0] not in {0, 3}, item[1] not in {0x0409, 0}, -len(item[3])))
            result[name_id] = candidates[0][3]
        return result

    def weight(self) -> int:
        try:
            offset, length = self.table("OS/2")
            return _u16(self.data, offset + 4) if length >= 6 else 400
        except ValueError:
            return 400

    def _cmap_subtables(self) -> list[int]:
        offset, length = self.table("cmap")
        count = _u16(self.data, offset + 2)
        candidates: list[tuple[int, int]] = []
        for index in range(count):
            record = offset + 4 + index * 8
            platform, encoding, relative = struct.unpack_from(">HHI", self.data, record)
            subtable = offset + relative
            if subtable + 2 > offset + length:
                continue
            format_value = _u16(self.data, subtable)
            if format_value in {4, 12, 13}:
                priority = 0 if format_value in {12, 13} else 1
                if platform == 3 and encoding in {10, 1}: priority -= 1
                candidates.append((priority, subtable))
        return [value for _, value in sorted(candidates)]

    def glyph_index(self, codepoint: int) -> int:
        for offset in self._cmap_subtables():
            format_value = _u16(self.data, offset)
            if format_value == 4 and codepoint <= 0xFFFF:
                seg_count = _u16(self.data, offset + 6) // 2
                end_codes = offset + 14
                start_codes = end_codes + seg_count * 2 + 2
                deltas = start_codes + seg_count * 2
                ranges = deltas + seg_count * 2
                for index in range(seg_count):
                    start, end = _u16(self.data, start_codes + index * 2), _u16(self.data, end_codes + index * 2)
                    if not start <= codepoint <= end:
                        continue
                    delta = _u16(self.data, deltas + index * 2)
                    range_value = _u16(self.data, ranges + index * 2)
                    if range_value == 0:
                        return (codepoint + delta) & 0xFFFF
                    glyph_offset = ranges + index * 2 + range_value + (codepoint - start) * 2
                    if glyph_offset + 2 > len(self.data):
                        return 0
                    glyph = _u16(self.data, glyph_offset)
                    return ((glyph + delta) & 0xFFFF) if glyph else 0
            elif format_value in {12, 13}:
                groups = _u32(self.data, offset + 12)
                for index in range(groups):
                    base = offset + 16 + index * 12
                    start, end, glyph = struct.unpack_from(">III", self.data, base)
                    if start <= codepoint <= end:
                        return glyph if format_value == 13 else glyph + codepoint - start
        return 0

    def supports(self, characters: Iterable[str]) -> tuple[bool, list[str]]:
        missing = [character for character in characters if self.glyph_index(ord(character)) == 0]
        return not missing, missing

    def text_advance(self, text: str, font_size: float, tracking: float = 0.0) -> float:
        head, _ = self.table("head")
        hhea, _ = self.table("hhea")
        hmtx, _ = self.table("hmtx")
        units_per_em = max(1, _u16(self.data, head + 18))
        metrics_count = max(1, _u16(self.data, hhea + 34))
        last_advance = _u16(self.data, hmtx + (metrics_count - 1) * 4)
        total = 0
        for character in text:
            glyph = self.glyph_index(ord(character))
            total += _u16(self.data, hmtx + glyph * 4) if glyph < metrics_count else last_advance
        return total / units_per_em * font_size + max(0, len(text) - 1) * tracking


def _candidate_role(path: Path, root: Path) -> str:
    parts = [value.lower() for value in path.relative_to(root).parts]
    return next((role.upper() for role in ("body", "display", "hero") if role in parts), "UNASSIGNED")


def inspect_font(path: Path, root: Path) -> dict[str, Any]:
    relative = path.relative_to(root).as_posix()
    try:
        font = SfntFont.open(path)
        names = font.names()
        supported, missing = font.supports(REQUIRED_CHARACTERS)
        cyrillic_basic, missing_basic = font.supports(chr(value) for value in range(0x0410, 0x0450))
        proof_width = round(font.text_advance(CYRILLIC_PROOF, 64), 2)
        return {
            "relative_path": relative,
            "family": names.get(1, path.stem),
            "subfamily": names.get(2, "Regular"),
            "full_name": names.get(4, names.get(1, path.stem)),
            "postscript_name": names.get(6),
            "weight": font.weight(),
            "variable_font": "fvar" in font.tables,
            "extension": path.suffix.lower(),
            "candidate_role": _candidate_role(path, root),
            "cyrillic_support": supported,
            "basic_cyrillic_support": cyrillic_basic,
            "missing_required_characters": missing,
            "missing_basic_cyrillic_count": len(missing_basic),
            "proof_advance_px_at_64": proof_width,
            "load_status": "PARSED",
            "validation_status": "VALID_CYRILLIC" if supported else "CYRILLIC_UNSUPPORTED",
            "sha256": sha256(path.read_bytes()).hexdigest(),
        }
    except (OSError, ValueError, struct.error) as error:
        return {
            "relative_path": relative, "family": path.stem, "subfamily": None,
            "weight": None, "extension": path.suffix.lower(),
            "candidate_role": _candidate_role(path, root), "cyrillic_support": False,
            "load_status": "FAILED", "validation_status": "INVALID_FONT",
            "error": f"{type(error).__name__}: {error}",
        }


def build_font_manifest(root: Path, destination: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    files = sorted(
        (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in {".ttf", ".otf"}),
        key=lambda path: path.as_posix().lower(),
    )
    fonts = [inspect_font(path, root) for path in files]
    manifest = {
        "version": 1, "root": str(root), "proof_string": CYRILLIC_PROOF,
        "long_word_regressions": list(LONG_WORDS), "number_regressions": list(NUMBER_CASES),
        "summary": {
            "total": len(fonts),
            "parsed": sum(item["load_status"] == "PARSED" for item in fonts),
            "cyrillic_supported": sum(bool(item.get("cyrillic_support")) for item in fonts),
            "rejected": sum(item.get("validation_status") != "VALID_CYRILLIC" for item in fonts),
        },
        "fonts": fonts,
    }
    if destination:
        destination.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(manifest, ensure_ascii=False, indent=2)
        if not destination.is_file() or destination.read_text(encoding="utf-8") != payload:
            destination.write_text(payload, encoding="utf-8")
    return manifest


def resolve_manifest_font(root: Path, manifest: dict[str, Any], relative_path: str) -> tuple[Path | None, dict[str, Any] | None]:
    record = next((item for item in manifest.get("fonts", []) if item.get("relative_path") == relative_path), None)
    if not record or record.get("validation_status") != "VALID_CYRILLIC":
        return None, record
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None, record
    return (candidate if candidate.is_file() else None), record


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build ShortsAI local font inventory")
    parser.add_argument("root", nargs="?", default="assets/fonts")
    parser.add_argument("--output", default="assets/fonts/font_manifest.json")
    args = parser.parse_args()
    result = build_font_manifest(Path(args.root), Path(args.output))
    print(json.dumps(result["summary"], ensure_ascii=False))

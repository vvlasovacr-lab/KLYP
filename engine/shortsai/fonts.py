from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def _installed_font_names() -> set[str]:
    names: set[str] = set()
    if os.name != "nt":
        return names
    try:
        import winreg

        locations = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        )
        for hive, location in locations:
            try:
                with winreg.OpenKey(hive, location) as key:
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        display_name = winreg.EnumValue(key, index)[0]
                        names.add(display_name.split("(")[0].strip().lower())
            except OSError:
                continue
    except (ImportError, OSError):
        pass
    return names


def _installed_font_files() -> dict[str, Path]:
    records: dict[str, Path] = {}
    if os.name != "nt":
        return records
    try:
        import winreg
        windows_fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        locations = (
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"),
        )
        for hive, location in locations:
            try:
                with winreg.OpenKey(hive, location) as key:
                    for index in range(winreg.QueryInfoKey(key)[1]):
                        name, value, _ = winreg.EnumValue(key, index)
                        path = Path(str(value))
                        if not path.is_absolute():
                            path = windows_fonts / path
                        if path.is_file():
                            records[name.split("(")[0].strip().lower()] = path
            except OSError:
                continue
    except (ImportError, OSError):
        pass
    return records


def resolve_font_family(preferred: Iterable[str], fallback: str = "Arial") -> str:
    installed = _installed_font_names()
    for family in preferred:
        normalized = family.lower()
        if any(normalized == name or normalized in name or name in normalized for name in installed):
            return family
    return fallback


def resolve_font_file(preferred: Iterable[str]) -> Path | None:
    installed = _installed_font_files()
    for family in preferred:
        normalized = family.lower()
        for name, path in installed.items():
            if normalized == name or normalized in name or name in normalized:
                return path
    return None

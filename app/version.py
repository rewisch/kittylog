"""Application version management."""
from __future__ import annotations

from pathlib import Path


VERSION_PATH = Path(__file__).resolve().parent.parent / "version.txt"


def get_version() -> str:
    """Return the application version from version.txt."""
    try:
        return VERSION_PATH.read_text(encoding="utf-8").strip()
    except Exception:
        return "0.1"

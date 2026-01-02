from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class AppSettings:
    default_language: str = "en"


_settings: AppSettings | None = None


def load_settings(path: Path | None = None) -> AppSettings:
    """Load app-wide settings from YAML."""
    global _settings
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "settings.yml"
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        data = {}

    _settings = AppSettings(default_language=str(data.get("default_language", "en")))
    return _settings


def get_settings() -> AppSettings:
    """Return cached settings, loading defaults if needed."""
    global _settings
    if _settings is None:
        return load_settings()
    return _settings

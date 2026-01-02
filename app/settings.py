from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "kittylog.db"


@dataclass
class AppSettings:
    default_language: str = "en"
    db_path: Path = DEFAULT_DB_PATH


_settings: AppSettings | None = None


def load_settings(path: Path | None = None) -> AppSettings:
    """Load app-wide settings from YAML."""
    global _settings
    if path is None:
        path = Path(__file__).resolve().parent.parent / "config" / "settings.yml"
    repo_root = path.resolve().parent.parent
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        data = {}

    raw_db_path = data.get("db_path", DEFAULT_DB_PATH)
    db_path = _resolve_db_path(raw_db_path, repo_root)

    _settings = AppSettings(
        default_language=str(data.get("default_language", "en")),
        db_path=db_path,
    )
    return _settings


def get_settings() -> AppSettings:
    """Return cached settings, loading defaults if needed."""
    global _settings
    if _settings is None:
        return load_settings()
    return _settings


def _resolve_db_path(raw_path: Any, repo_root: Path) -> Path:
    """Resolve DB path from config, allowing relative paths from repo root."""
    if isinstance(raw_path, Path):
        candidate = raw_path
    else:
        candidate = Path(str(raw_path))

    if not candidate.is_absolute():
        return repo_root / candidate
    return candidate

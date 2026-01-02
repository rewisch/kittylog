from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "kittylog.db"
DEFAULT_API_KEY_PATH = Path(__file__).resolve().parent.parent / "config" / "api_key.yml"


@dataclass
class AppSettings:
    default_language: str = "en"
    db_path: Path = DEFAULT_DB_PATH
    api_key: str | None = None
    api_user: str = "api"


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

    file_api_key, file_api_user = _load_api_key(repo_root)
    env_api_key = os.getenv("KITTYLOG_API_KEY")
    env_api_user = os.getenv("KITTYLOG_API_USER")

    api_key = (env_api_key or file_api_key or "").strip() or None
    api_user = (env_api_user or file_api_user or "api").strip()

    _settings = AppSettings(
        default_language=str(data.get("default_language", "en")),
        db_path=db_path,
        api_key=api_key,
        api_user=api_user,
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


def _load_api_key(repo_root: Path) -> tuple[str | None, str | None]:
    """Load API key/user from a separate, gitignored file if present."""
    api_path = DEFAULT_API_KEY_PATH if DEFAULT_API_KEY_PATH.is_absolute() else repo_root / DEFAULT_API_KEY_PATH
    if not api_path.exists():
        return None, None
    with api_path.open("r", encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f) or {}
    file_key = str(data.get("api_key") or "").strip() or None
    file_user = str(data.get("api_user") or "").strip() or None
    return file_key, file_user

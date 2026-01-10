from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

import yaml


DEFAULT_PUSH_KEYS_PATH = Path(__file__).resolve().parent.parent / "config" / "push_keys.yml"


@dataclass
class PushSettings:
    vapid_public_key: str | None = None
    vapid_private_key: str | None = None
    vapid_subject: str = "mailto:admin@example.com"


_settings: PushSettings | None = None


def load_push_settings(path: Path | None = None) -> PushSettings:
    """Load VAPID keys + subject from YAML or env."""
    global _settings
    if path is None:
        path = DEFAULT_PUSH_KEYS_PATH
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
    else:
        data = {}

    file_public = str(data.get("vapid_public_key") or "").strip() or None
    file_private = str(data.get("vapid_private_key") or "").strip() or None
    file_subject = str(data.get("vapid_subject") or "").strip()

    env_public = os.getenv("KITTYLOG_VAPID_PUBLIC_KEY")
    env_private = os.getenv("KITTYLOG_VAPID_PRIVATE_KEY")
    env_subject = os.getenv("KITTYLOG_VAPID_SUBJECT")

    _settings = PushSettings(
        vapid_public_key=(env_public or file_public),
        vapid_private_key=(env_private or file_private),
        vapid_subject=(env_subject or file_subject or "mailto:admin@example.com"),
    )
    return _settings


def get_push_settings() -> PushSettings:
    """Return cached push settings, loading defaults if needed."""
    global _settings
    if _settings is None:
        return load_push_settings()
    return _settings

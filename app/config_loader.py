from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import yaml
from sqlmodel import Session, select

from .models import TaskType


@dataclass
class TaskConfig:
    slug: str
    name: str
    icon: str
    color: str = "blue"


def load_task_configs(path: Path) -> list[TaskConfig]:
    """Load tasks from YAML configuration."""
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    tasks: Iterable[dict] = data.get("tasks", [])
    configs: List[TaskConfig] = []
    for item in tasks:
        configs.append(
            TaskConfig(
                slug=str(item["slug"]),
                name=str(item["name"]),
                icon=str(item.get("icon", "🐾")),
                color=str(item.get("color", "blue")),
            )
        )
    return configs


def sync_task_types(session: Session, configs: list[TaskConfig]) -> None:
    """Create or update TaskType rows from config."""
    for config in configs:
        existing = session.exec(select(TaskType).where(TaskType.slug == config.slug)).first()
        if existing is None:
            session.add(
                TaskType(
                    slug=config.slug,
                    name=config.name,
                    icon=config.icon,
                    color=config.color,
                    is_active=True,
                )
            )
        else:
            existing.name = config.name
            existing.icon = config.icon
            existing.color = config.color
    session.commit()

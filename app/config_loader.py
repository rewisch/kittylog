from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

import yaml
from sqlmodel import Session, select

from .models import TaskType


COLOR_PALETTE: tuple[str, ...] = (
    "amber",
    "blue",
    "cyan",
    "green",
    "emerald",
    "fuchsia",
    "indigo",
    "lime",
    "orange",
    "pink",
    "purple",
    "red",
    "rose",
    "sky",
    "teal",
    "violet",
    "yellow",
)


@dataclass
class TaskConfig:
    slug: str
    name: str
    icon: str
    color: str = "blue"
    order: int = 0


def load_task_configs(path: Path) -> list[TaskConfig]:
    """Load tasks from YAML configuration."""
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    tasks: Iterable[dict] = data.get("tasks", [])
    configs: List[TaskConfig] = []
    used_colors: set[str] = set()
    for idx, item in enumerate(tasks):
        raw_order = item.get("order", idx)
        try:
            order_value = int(raw_order)
        except (TypeError, ValueError):
            order_value = idx
        preferred_color = str(item.get("color", "")).strip()
        color = _assign_color(preferred_color, used_colors, idx)
        configs.append(
            TaskConfig(
                slug=str(item["slug"]),
                name=str(item["name"]),
                icon=str(item.get("icon", "🐾")),
                color=color,
                order=order_value,
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
                    sort_order=config.order,
                    is_active=True,
                )
            )
        else:
            existing.name = config.name
            existing.icon = config.icon
            existing.color = config.color
            existing.sort_order = config.order
    session.commit()


def _assign_color(preferred: str, used_colors: set[str], index: int) -> str:
    """Pick a color from the palette, keeping colors unique until exhausted."""
    if preferred in COLOR_PALETTE and preferred not in used_colors:
        used_colors.add(preferred)
        return preferred
    for candidate in COLOR_PALETTE:
        if candidate not in used_colors:
            used_colors.add(candidate)
            return candidate
    # Palette exhausted; fall back to cycling through palette
    fallback = COLOR_PALETTE[index % len(COLOR_PALETTE)]
    used_colors.add(fallback)
    return fallback

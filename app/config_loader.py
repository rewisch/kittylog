from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List

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
    requires_cat: bool = False


def load_task_configs(path: Path) -> list[TaskConfig]:
    """Load tasks from YAML configuration."""
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    tasks: Iterable[dict] = data.get("tasks", [])
    configs: List[TaskConfig] = []
    used_colors: set[str] = set()
    seen_slugs: set[str] = set()
    for idx, item in enumerate(tasks):
        _validate_task_item(item, idx)
        raw_order = item.get("order", idx)
        try:
            order_value = int(raw_order)
        except (TypeError, ValueError):
            order_value = idx
        preferred_color = str(item.get("color", "")).strip()
        color = _assign_color(preferred_color, used_colors, idx)
        slug = str(item["slug"])
        if slug in seen_slugs:
            raise ValueError(f"Duplicate task slug '{slug}' in tasks.yml")
        seen_slugs.add(slug)
        configs.append(
            TaskConfig(
                slug=slug,
                name=str(item["name"]),
                icon=str(item.get("icon", "🐾")),
                color=color,
                order=order_value,
                requires_cat=bool(item.get("requires_cat", False)),
            )
        )
    return configs


def sync_task_types(session: Session, configs: list[TaskConfig]) -> None:
    """Create or update TaskType rows from config."""
    config_slugs = {c.slug for c in configs}
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
                    requires_cat=config.requires_cat,
                )
            )
        else:
            existing.name = config.name
            existing.icon = config.icon
            existing.color = config.color
            existing.sort_order = config.order
            existing.is_active = True
            existing.requires_cat = config.requires_cat

    # Deactivate tasks not present in config
    for task in session.exec(select(TaskType)).all():
        if task.slug not in config_slugs and task.is_active:
            task.is_active = False
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


def _validate_task_item(item: dict[str, Any], index: int) -> None:
    """Validate one task config entry."""
    required_fields = ("slug", "name")
    for field in required_fields:
        if field not in item or item[field] in (None, ""):
            raise ValueError(f"tasks[{index}] missing required field '{field}'")
    if not isinstance(item.get("slug"), (str, int, float)):
        raise ValueError(f"tasks[{index}].slug must be a string")
    if not isinstance(item.get("name"), (str, int, float)):
        raise ValueError(f"tasks[{index}].name must be a string")
    if "order" in item:
        raw_order = item["order"]
        try:
            int(raw_order)
        except (TypeError, ValueError):
            raise ValueError(f"tasks[{index}].order must be an integer")
    if "requires_cat" in item and not isinstance(item.get("requires_cat"), bool):
        raise ValueError(f"tasks[{index}].requires_cat must be a boolean")

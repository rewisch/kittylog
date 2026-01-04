from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Set

import yaml

from .settings import _resolve_db_path


MigrationFn = Callable[[Path, Path], None]
LEGACY_DB_RELATIVE = "kittylog.db"
LEGACY_DB_PATH = Path(__file__).resolve().parent.parent / LEGACY_DB_RELATIVE
NEW_DB_RELATIVE = "data/kittylog.db"


@dataclass(frozen=True)
class Migration:
    id: str
    fn: MigrationFn
    description: str


def _load_completed(path: Path) -> Set[str]:
    if not path.exists():
        return set()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    items = data.get("completed", [])
    if not isinstance(items, list):
        return set()
    return {str(item) for item in items}


def _save_completed(path: Path, completed: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = {"completed": sorted(completed)}
    path.write_text(yaml.safe_dump(content, sort_keys=False), encoding="utf-8")


def _migrate_001_move_db_to_data_dir(repo_root: Path, settings_path: Path) -> None:
    """Move legacy root-level DB to data/ and update settings."""
    if settings_path.exists():
        settings_data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    else:
        settings_data = {}

    raw_db_value = settings_data.get("db_path")
    resolved_db_path = _resolve_db_path(raw_db_value or NEW_DB_RELATIVE, repo_root)
    legacy_path = repo_root / LEGACY_DB_RELATIVE
    new_path = repo_root / NEW_DB_RELATIVE

    new_path.parent.mkdir(parents=True, exist_ok=True)

    # Move legacy DB forward if present, even if settings already point to new path.
    if legacy_path.exists():
        if not new_path.exists():
            legacy_path.replace(new_path)
            print(f"Moved database to {new_path}")
        else:
            print("New database path already exists; leaving legacy file in place.")

    # Update settings if it referenced the legacy path or omitted db_path.
    if raw_db_value is None or resolved_db_path == legacy_path:
        settings_data["db_path"] = NEW_DB_RELATIVE
        settings_path.write_text(yaml.safe_dump(settings_data, sort_keys=False), encoding="utf-8")
        print(f"Updated settings to use {NEW_DB_RELATIVE}")


MIGRATIONS: list[Migration] = [
    Migration(
        id="001_move_db_to_data_dir",
        fn=_migrate_001_move_db_to_data_dir,
        description="Move legacy root-level kittylog.db into data/kittylog.db and update settings.",
    ),
]


def run_startup_migrations(repo_root: Path) -> None:
    """Run any pending migrations and persist completion state."""
    migrations_file = repo_root / "config" / "migrations.yml"
    settings_path = repo_root / "config" / "settings.yml"

    completed = _load_completed(migrations_file)
    seen_ids: set[str] = set()

    for migration in MIGRATIONS:
        if migration.id in seen_ids:
            raise RuntimeError(f"Duplicate migration id found: {migration.id}")
        seen_ids.add(migration.id)

        if migration.id in completed:
            continue
        migration.fn(repo_root, settings_path)
        completed.add(migration.id)

    _save_completed(migrations_file, completed)

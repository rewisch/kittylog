from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Set

import sqlite3
import yaml

from .auth import load_users
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


def _migrate_002_normalize_task_event_users(repo_root: Path, settings_path: Path) -> None:
    """Normalize TaskEvent.who casing to match users file entries."""
    if settings_path.exists():
        settings_data = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    else:
        settings_data = {}

    raw_db_value = settings_data.get("db_path") or NEW_DB_RELATIVE
    db_path = _resolve_db_path(raw_db_value, repo_root)
    if not db_path.exists():
        print(f"Database not found at {db_path}; skipping user normalization.")
        return

    users = load_users()
    canonical_map: dict[str, str | None] = {}
    for username in users.keys():
        key = username.casefold()
        if key in canonical_map and canonical_map[key] != username:
            canonical_map[key] = None
        else:
            canonical_map[key] = username
    canonical_map = {k: v for k, v in canonical_map.items() if v}

    if not canonical_map:
        print("No users available for normalization; skipping.")
        return

    updated = 0
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT who FROM taskevent WHERE who IS NOT NULL AND TRIM(who) != ''"
        )
        rows = cursor.fetchall()
        for (raw_who,) in rows:
            if raw_who is None:
                continue
            who_value = str(raw_who)
            canonical = canonical_map.get(who_value.casefold())
            if canonical and canonical != who_value:
                cursor.execute(
                    "UPDATE taskevent SET who = ? WHERE who = ?",
                    (canonical, who_value),
                )
                updated += cursor.rowcount
        conn.commit()

    print(f"Normalized task event users: {updated} row(s) updated.")


MIGRATIONS: list[Migration] = [
    Migration(
        id="001_move_db_to_data_dir",
        fn=_migrate_001_move_db_to_data_dir,
        description="Move legacy root-level kittylog.db into data/kittylog.db and update settings.",
    ),
    Migration(
        id="002_normalize_task_event_users",
        fn=_migrate_002_normalize_task_event_users,
        description="Normalize task event usernames to match users file casing.",
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

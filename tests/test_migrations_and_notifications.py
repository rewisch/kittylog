from __future__ import annotations

import sqlite3
from pathlib import Path

from app.migrations import _migrate_002_normalize_task_event_users
from app.auth import encode_password, save_users
from scripts.dispatch_notifications import load_notification_config


def _write_users(path: Path, users: dict[str, str]) -> None:
    data = {}
    for username, password in users.items():
        data[username] = {
            "encoded": encode_password(password),
            "active": True,
            "failed_attempts": 0,
        }
    save_users(data, path)


def test_migration_normalizes_task_event_users(tmp_path, monkeypatch) -> None:
    repo_root = tmp_path
    config_dir = repo_root / "config"
    data_dir = repo_root / "data"
    config_dir.mkdir()
    data_dir.mkdir()
    settings_path = config_dir / "settings.yml"
    settings_path.write_text("db_path: data/kittylog.db\n", encoding="utf-8")

    users_file = tmp_path / "users.txt"
    _write_users(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))

    db_path = data_dir / "kittylog.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE taskevent (id INTEGER PRIMARY KEY, who TEXT)")
        conn.execute("INSERT INTO taskevent (who) VALUES (?)", ("livia",))
        conn.execute("INSERT INTO taskevent (who) VALUES (?)", ("Livia",))
        conn.commit()

    _migrate_002_normalize_task_event_users(repo_root, settings_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT who FROM taskevent ORDER BY id").fetchall()
        assert [row[0] for row in rows] == ["Livia", "Livia"]


def test_load_notification_config_parses_events(tmp_path) -> None:
    config_path = tmp_path / "notifications.yml"
    config_path.write_text(
        """
timezone: "UTC"
window_minutes: 5
click_url: "/"
groups: {}
rules:
  - id: "feed-morning"
    time: "09:00"
    task_slug: "feed"
    if_not_logged_today: true
events:
  - id: "cat-birthday"
    type: "cat_birthday"
    title: "KittyLog"
    message: "Birthday today: {cats}."
  - id: "cat-milestone"
    type: "cat_milestone"
    months: [6, 12]
    title: "KittyLog"
    message: "Milestones today: {items}."
""",
        encoding="utf-8",
    )
    config = load_notification_config(config_path)
    assert config.events[0].event_type == "cat_birthday"
    assert config.events[1].months == [6, 12]

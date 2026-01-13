from __future__ import annotations

import sqlite3
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlmodel import Session, select

from app.migrations import _migrate_002_normalize_task_event_users
from app.auth import encode_password, save_users
from app.database import configure_engine, create_db_and_tables, get_engine
from app.models import NotificationLog, PushSubscription, TaskEvent, TaskType
from app.push_config import PushSettings
from app.settings import AppSettings
import scripts.dispatch_notifications as dispatch
from scripts.dispatch_notifications import birthday_matches
from scripts.dispatch_notifications import days_since_last_event
from scripts.dispatch_notifications import is_within_window
from scripts.dispatch_notifications import load_notification_config
from scripts.dispatch_notifications import local_time_window_bounds
from scripts.dispatch_notifications import months_since_birth


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


def _utc_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _event_ids_in_window(
    session: Session,
    task_id: int,
    window_start: datetime,
    window_end: datetime,
) -> list[int]:
    return session.exec(
        select(TaskEvent.id).where(
            TaskEvent.task_type_id == task_id,
            TaskEvent.deleted == False,  # noqa: E712
            TaskEvent.timestamp >= window_start,
            TaskEvent.timestamp < window_end,
        )
    ).all()


def test_feed_notification_windows_split_day(tmp_path) -> None:
    db_path = tmp_path / "notifications.db"
    configure_engine(db_path)
    create_db_and_tables()

    config_path = tmp_path / "notifications.yml"
    config_path.write_text(
        """
timezone: "Europe/Berlin"
window_minutes: 5
click_url: "/"
groups: {}
rules:
  - id: "feed-morning"
    time: "09:00"
    task_slug: "feed"
    if_not_logged_today: true
    check_window_start: "00:00"
    check_window_end: "12:00"
  - id: "feed-evening"
    time: "19:30"
    task_slug: "feed"
    if_not_logged_today: true
    check_window_start: "12:00"
    check_window_end: "00:00"
events: []
""",
        encoding="utf-8",
    )
    config = load_notification_config(config_path)
    morning_rule, evening_rule = config.rules
    tz = ZoneInfo("Europe/Berlin")

    with Session(get_engine()) as session:
        task = TaskType(slug="feed", name="Feed", icon="F", color="blue", sort_order=0)
        session.add(task)
        session.commit()
        session.refresh(task)

        morning_event = TaskEvent(
            task_type_id=task.id,
            timestamp=_utc_naive(datetime(2024, 1, 1, 8, 0, tzinfo=tz)),
        )
        evening_event = TaskEvent(
            task_type_id=task.id,
            timestamp=_utc_naive(datetime(2024, 1, 1, 18, 0, tzinfo=tz)),
        )
        session.add_all([morning_event, evening_event])
        session.commit()
        session.refresh(morning_event)
        session.refresh(evening_event)

        assert morning_rule.check_window_start is not None
        assert morning_rule.check_window_end is not None
        now_morning = datetime(2024, 1, 1, 9, 0, tzinfo=tz)
        window_start, window_end = local_time_window_bounds(
            now_morning,
            morning_rule.check_window_start,
            morning_rule.check_window_end,
        )
        morning_ids = _event_ids_in_window(session, task.id, window_start, window_end)
        assert morning_event.id in morning_ids
        assert evening_event.id not in morning_ids

        assert evening_rule.check_window_start is not None
        assert evening_rule.check_window_end is not None
        now_evening = datetime(2024, 1, 1, 19, 30, tzinfo=tz)
        window_start, window_end = local_time_window_bounds(
            now_evening,
            evening_rule.check_window_start,
            evening_rule.check_window_end,
        )
        evening_ids = _event_ids_in_window(session, task.id, window_start, window_end)
        assert evening_event.id in evening_ids
        assert morning_event.id not in evening_ids


def test_is_within_window_handles_midnight_wrap() -> None:
    tz = ZoneInfo("UTC")
    rule_time = dt_time(23, 58)
    assert is_within_window(datetime(2024, 1, 1, 23, 59, tzinfo=tz), rule_time, 5) is True
    assert is_within_window(datetime(2024, 1, 2, 0, 2, tzinfo=tz), rule_time, 5) is True
    assert is_within_window(datetime(2024, 1, 2, 0, 3, tzinfo=tz), rule_time, 5) is False
    assert is_within_window(datetime(2024, 1, 2, 9, 4, tzinfo=tz), dt_time(9, 0), 5) is True
    assert is_within_window(datetime(2024, 1, 2, 9, 5, tzinfo=tz), dt_time(9, 0), 5) is False


def test_days_since_last_event_uses_local_date() -> None:
    tz = ZoneInfo("America/New_York")
    now_local = datetime(2024, 1, 10, 1, 0, tzinfo=tz)
    last_ts = datetime(2024, 1, 9, 23, 30)
    assert days_since_last_event(last_ts, now_local) == 1
    assert days_since_last_event(None, now_local) is None


def test_event_helpers_cover_leap_day_and_months() -> None:
    leap_birthday = date(2020, 2, 29)
    assert birthday_matches(leap_birthday, date(2021, 2, 28)) is True
    assert birthday_matches(leap_birthday, date(2021, 3, 1)) is False
    assert birthday_matches(leap_birthday, date(2024, 2, 29)) is True

    birthday = date(2024, 1, 15)
    assert months_since_birth(birthday, date(2024, 2, 15)) == 1
    assert months_since_birth(birthday, date(2024, 2, 14)) is None
    assert months_since_birth(birthday, date(2023, 12, 15)) is None


def test_notification_grouping_and_dedup(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "notifications.db"
    configure_engine(db_path)
    create_db_and_tables()

    config_path = tmp_path / "notifications.yml"
    config_path.write_text(
        """
timezone: "UTC"
window_minutes: 5
click_url: "/"
groups:
  daily:
    title: "KittyLog"
    message: "Tasks missing: {tasks}."
rules:
  - id: "feed-morning"
    time: "09:00"
    task_slug: "feed"
    if_not_logged_today: true
    group: "daily"
  - id: "clean-morning"
    time: "09:00"
    task_slug: "clean"
    if_not_logged_today: true
    group: "daily"
  - id: "water-maintenance"
    time: "09:00"
    task_slug: "water"
    if_not_logged_today: false
    min_days_since_last: 2
    repeat_every_days: 2
events: []
""",
        encoding="utf-8",
    )

    now_local = datetime.now(ZoneInfo("UTC"))
    water_event_time = (now_local - timedelta(days=3)).astimezone(timezone.utc).replace(tzinfo=None)

    with Session(get_engine()) as session:
        feed_task = TaskType(slug="feed", name="Feed", icon="F", color="blue", sort_order=0)
        clean_task = TaskType(slug="clean", name="Clean", icon="C", color="blue", sort_order=0)
        water_task = TaskType(slug="water", name="Water", icon="W", color="blue", sort_order=0)
        session.add_all([feed_task, clean_task, water_task])
        session.add(
            PushSubscription(
                user="tester",
                endpoint="https://example.com/endpoint",
                p256dh="p256dh",
                auth="auth",
            )
        )
        session.commit()
        session.refresh(water_task)
        session.add(TaskEvent(task_type_id=water_task.id, timestamp=water_event_time))
        session.commit()

    monkeypatch.setattr(
        dispatch,
        "load_settings",
        lambda path=None: AppSettings(db_path=db_path),
    )
    monkeypatch.setattr(
        dispatch,
        "load_push_settings",
        lambda path=None: PushSettings(
            vapid_private_key="dummy",
            vapid_subject="mailto:test@example.com",
        ),
    )
    send_calls: list[tuple[tuple, dict]] = []

    def _fake_send(*args, **kwargs) -> None:
        send_calls.append((args, kwargs))

    monkeypatch.setattr(dispatch, "send_web_push", _fake_send)

    assert dispatch.main(["--config", str(config_path), "--at", "09:00"]) == 0
    assert len(send_calls) == 1

    with Session(get_engine()) as session:
        logs = session.exec(select(NotificationLog)).all()
        assert len(logs) == 1
        assert logs[0].group_id == "daily"

    assert dispatch.main(["--config", str(config_path), "--at", "09:00"]) == 0
    assert len(send_calls) == 1

    with Session(get_engine()) as session:
        logs = session.exec(select(NotificationLog)).all()
        assert len(logs) == 1

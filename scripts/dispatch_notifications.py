#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
from dataclasses import dataclass
from datetime import date, datetime, time as dt_time, timedelta, timezone
import json
import sys
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from pywebpush import WebPushException, webpush
from sqlmodel import Session, select

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.database import configure_engine, create_db_and_tables, get_engine  # noqa: E402
from app.models import Cat, NotificationLog, PushSubscription, TaskEvent, TaskType  # noqa: E402
from app.push_config import load_push_settings  # noqa: E402
from app.settings import load_settings  # noqa: E402


@dataclass
class GroupConfig:
    title: str
    message: str


@dataclass
class RuleConfig:
    rule_id: str
    time: dt_time
    task_slug: str
    if_not_logged_today: bool
    min_days_since_last: int | None
    repeat_every_days: int | None
    check_window_start: dt_time | None
    check_window_end: dt_time | None
    title: str | None
    message: str | None
    group: str | None


@dataclass
class EventConfig:
    event_id: str
    event_type: str
    months: list[int] | None
    title: str | None
    message: str | None


@dataclass
class NotificationConfig:
    timezone: ZoneInfo
    window_minutes: int
    click_url: str
    groups: dict[str, GroupConfig]
    rules: list[RuleConfig]
    events: list[EventConfig]


def _parse_time(value: str) -> dt_time:
    try:
        parsed = datetime.strptime(value, "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"Invalid time '{value}', expected HH:MM") from exc
    return parsed


def load_notification_config(path: Path) -> NotificationConfig:
    if not path.exists():
        raise FileNotFoundError(f"Notification config not found: {path}")
    data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    tz_name = str(data.get("timezone") or "UTC")
    timezone_obj = ZoneInfo(tz_name)

    raw_window = data.get("window_minutes", 5)
    try:
        window_minutes = int(raw_window)
    except (TypeError, ValueError) as exc:
        raise ValueError("window_minutes must be an integer") from exc
    if window_minutes <= 0:
        raise ValueError("window_minutes must be greater than zero")

    click_url = str(data.get("click_url") or "/")

    groups: dict[str, GroupConfig] = {}
    for key, value in (data.get("groups") or {}).items():
        if not isinstance(value, dict):
            continue
        title = str(value.get("title") or "KittyLog")
        message = str(value.get("message") or "Tasks missing: {tasks}.")
        groups[str(key)] = GroupConfig(title=title, message=message)

    rules: list[RuleConfig] = []
    for item in data.get("rules") or []:
        if not isinstance(item, dict):
            continue
        rule_id = str(item.get("id") or "").strip()
        if not rule_id:
            raise ValueError("Each rule must have a non-empty id")
        task_slug = str(item.get("task_slug") or "").strip()
        if not task_slug:
            raise ValueError(f"Rule '{rule_id}' is missing task_slug")
        time_value = _parse_time(str(item.get("time") or ""))
        if_not_logged_today = bool(item.get("if_not_logged_today", True))
        min_days_since_last = item.get("min_days_since_last")
        if min_days_since_last is not None:
            try:
                min_days_since_last = int(min_days_since_last)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Rule '{rule_id}' min_days_since_last must be an integer") from exc
            if min_days_since_last < 0:
                raise ValueError(f"Rule '{rule_id}' min_days_since_last must be >= 0")
        repeat_every_days = item.get("repeat_every_days")
        if repeat_every_days is not None:
            try:
                repeat_every_days = int(repeat_every_days)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Rule '{rule_id}' repeat_every_days must be an integer") from exc
            if repeat_every_days <= 0:
                raise ValueError(f"Rule '{rule_id}' repeat_every_days must be > 0")
        if min_days_since_last is None and not if_not_logged_today:
            raise ValueError(f"Rule '{rule_id}' must set if_not_logged_today or min_days_since_last")
        check_window_start = item.get("check_window_start")
        check_window_end = item.get("check_window_end")
        if check_window_start is not None or check_window_end is not None:
            if not if_not_logged_today:
                raise ValueError(
                    f"Rule '{rule_id}' check_window_* requires if_not_logged_today to be true"
                )
            if check_window_start is None or check_window_end is None:
                raise ValueError(
                    f"Rule '{rule_id}' must set both check_window_start and check_window_end"
                )
            check_window_start = _parse_time(str(check_window_start))
            check_window_end = _parse_time(str(check_window_end))
        else:
            check_window_start = None
            check_window_end = None
        title = str(item.get("title") or "").strip() or None
        message = str(item.get("message") or "").strip() or None
        group = str(item.get("group") or "").strip() or None
        rules.append(
            RuleConfig(
                rule_id=rule_id,
                time=time_value,
                task_slug=task_slug,
                if_not_logged_today=if_not_logged_today,
                min_days_since_last=min_days_since_last,
                repeat_every_days=repeat_every_days,
                check_window_start=check_window_start,
                check_window_end=check_window_end,
                title=title,
                message=message,
                group=group,
            )
        )

    if not rules:
        raise ValueError("No rules configured in notifications.yml")

    events: list[EventConfig] = []
    for item in data.get("events") or []:
        if not isinstance(item, dict):
            continue
        event_id = str(item.get("id") or "").strip()
        if not event_id:
            raise ValueError("Each event must have a non-empty id")
        event_type = str(item.get("type") or "").strip()
        if not event_type:
            raise ValueError(f"Event '{event_id}' is missing type")
        raw_months = item.get("months")
        months: list[int] | None = None
        if raw_months is not None:
            if not isinstance(raw_months, list):
                raise ValueError(f"Event '{event_id}' months must be a list of integers")
            months = []
            for value in raw_months:
                try:
                    month_value = int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Event '{event_id}' months must be integers") from exc
                if month_value <= 0:
                    raise ValueError(f"Event '{event_id}' months must be > 0")
                months.append(month_value)
        title = str(item.get("title") or "").strip() or None
        message = str(item.get("message") or "").strip() or None
        events.append(
            EventConfig(
                event_id=event_id,
                event_type=event_type,
                months=months,
                title=title,
                message=message,
            )
        )

    return NotificationConfig(
        timezone=timezone_obj,
        window_minutes=window_minutes,
        click_url=click_url,
        groups=groups,
        rules=rules,
        events=events,
    )


def is_within_window(now_local: datetime, rule_time: dt_time, window_minutes: int) -> bool:
    now_minutes = now_local.hour * 60 + now_local.minute
    start_minutes = rule_time.hour * 60 + rule_time.minute
    end_minutes = start_minutes + window_minutes
    if end_minutes >= 24 * 60:
        overflow = end_minutes - 24 * 60
        return now_minutes >= start_minutes or now_minutes < overflow
    return start_minutes <= now_minutes < end_minutes


def local_day_bounds(now_local: datetime) -> tuple[datetime, datetime]:
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    end_local = start_local + timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def local_time_window_bounds(
    now_local: datetime,
    window_start: dt_time,
    window_end: dt_time,
) -> tuple[datetime, datetime]:
    start_local = now_local.replace(
        hour=window_start.hour,
        minute=window_start.minute,
        second=0,
        microsecond=0,
    )
    end_local = now_local.replace(
        hour=window_end.hour,
        minute=window_end.minute,
        second=0,
        microsecond=0,
    )
    if end_local <= start_local:
        end_local += timedelta(days=1)
    start_utc = start_local.astimezone(timezone.utc).replace(tzinfo=None)
    end_utc = end_local.astimezone(timezone.utc).replace(tzinfo=None)
    return start_utc, end_utc


def days_since_last_event(last_ts: datetime | None, now_local: datetime) -> int | None:
    if last_ts is None:
        return None
    last_local = last_ts.replace(tzinfo=timezone.utc).astimezone(now_local.tzinfo)
    return (now_local.date() - last_local.date()).days


def birthday_matches(birthday: date, today: date) -> bool:
    if birthday.month == 2 and birthday.day == 29 and not calendar.isleap(today.year):
        return today.month == 2 and today.day == 28
    return birthday.month == today.month and birthday.day == today.day


def months_since_birth(birthday: date, today: date) -> int | None:
    if today.day != birthday.day:
        return None
    months = (today.year - birthday.year) * 12 + (today.month - birthday.month)
    if months < 0:
        return None
    return months


def _ensure_pywebpush_curve() -> None:
    # Work around cryptography API change in Python 3.13+ where curve must be an instance.
    try:
        import pywebpush  # noqa: WPS433
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: WPS433
    except ImportError:
        return
    if getattr(pywebpush, "_kittylog_ec_patch", False):
        return
    original_generate = ec.generate_private_key

    def generate_private_key(curve, backend=None):  # type: ignore[override]
        if isinstance(curve, type):
            curve = curve()
        return original_generate(curve, backend)

    pywebpush.ec.generate_private_key = generate_private_key  # type: ignore[attr-defined]
    pywebpush._kittylog_ec_patch = True


def send_web_push(
    subscription: PushSubscription,
    title: str,
    message: str,
    click_url: str,
    private_key: str,
    subject: str,
) -> None:
    _ensure_pywebpush_curve()
    payload = json.dumps({"title": title, "message": message, "url": click_url})
    webpush(
        subscription_info={
            "endpoint": subscription.endpoint,
            "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
        },
        data=payload,
        vapid_private_key=private_key,
        vapid_claims={"sub": subject},
        ttl=3600,
    )


def build_default_message(task_name: str) -> str:
    return f"{task_name} not logged yet today."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dispatch KittyLog push notifications")
    parser.add_argument(
        "--config",
        type=Path,
        default=REPO_ROOT / "config" / "notifications.yml",
        help="Path to notifications.yml",
    )
    parser.add_argument(
        "--at",
        default="",
        help="Test run at a specific local time (HH:MM) using configured timezone",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Send an immediate test notification to all active subscriptions",
    )
    parser.add_argument("--dry-run", action="store_true", help="Evaluate rules without sending")
    args = parser.parse_args(argv)

    settings = load_settings()
    configure_engine(settings.db_path)
    create_db_and_tables()

    push_settings = load_push_settings()
    if not push_settings.vapid_private_key:
        print("Push notifications are not configured (missing VAPID private key).", file=sys.stderr)
        return 1

    try:
        config = load_notification_config(args.config)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    now_local = datetime.now(config.timezone)
    if args.at:
        try:
            at_time = datetime.strptime(args.at, "%H:%M").time()
        except ValueError as exc:
            print("Error: --at must be in HH:MM 24h format.", file=sys.stderr)
            return 1
        now_local = now_local.replace(hour=at_time.hour, minute=at_time.minute, second=0, microsecond=0)
    day_key = now_local.date().isoformat()
    start_utc, end_utc = local_day_bounds(now_local)

    with Session(get_engine()) as session:
        if args.test:
            subscriptions = session.exec(
                select(PushSubscription).where(PushSubscription.is_active == True)  # noqa: E712
            ).all()
            if not subscriptions:
                print("No active push subscriptions.")
                return 0
            title = "KittyLog test"
            message = "Test notification from KittyLog."
            for subscription in subscriptions:
                if args.dry_run:
                    print(f"[dry-run] {subscription.user}: {title} - {message}")
                    continue
                try:
                    send_web_push(
                        subscription,
                        title,
                        message,
                        config.click_url,
                        push_settings.vapid_private_key,
                        push_settings.vapid_subject,
                    )
                except WebPushException as exc:
                    status = exc.response and exc.response.status_code
                    print(f"Push failed for {subscription.endpoint}: {exc}", file=sys.stderr)
                    if status in (404, 410):
                        subscription.is_active = False
            if not args.dry_run:
                session.commit()
            print("Test notifications sent.")
            return 0

        tasks = session.exec(
            select(TaskType).where(TaskType.is_active == True)  # noqa: E712
        ).all()
        tasks_by_slug = {task.slug: task for task in tasks}

        triggered: list[tuple[RuleConfig, TaskType]] = []
        for rule in config.rules:
            if not is_within_window(now_local, rule.time, config.window_minutes):
                continue
            task = tasks_by_slug.get(rule.task_slug)
            if not task:
                print(f"Warning: task '{rule.task_slug}' not found for rule '{rule.rule_id}'")
                continue
            if rule.if_not_logged_today:
                if rule.check_window_start and rule.check_window_end:
                    window_start_utc, window_end_utc = local_time_window_bounds(
                        now_local,
                        rule.check_window_start,
                        rule.check_window_end,
                    )
                else:
                    window_start_utc, window_end_utc = start_utc, end_utc
                exists = session.exec(
                    select(TaskEvent.id).where(
                        TaskEvent.task_type_id == task.id,
                        TaskEvent.deleted == False,  # noqa: E712
                        TaskEvent.timestamp >= window_start_utc,
                        TaskEvent.timestamp < window_end_utc,
                    ).limit(1)
                ).first()
                if exists:
                    continue
            if rule.min_days_since_last is not None:
                last_event = session.exec(
                    select(TaskEvent).where(
                        TaskEvent.task_type_id == task.id,
                        TaskEvent.deleted == False,  # noqa: E712
                    ).order_by(TaskEvent.timestamp.desc()).limit(1)
                ).first()
                days_since = days_since_last_event(last_event.timestamp if last_event else None, now_local)
                if days_since is None:
                    days_since = rule.min_days_since_last
                if days_since < rule.min_days_since_last:
                    continue
                if rule.repeat_every_days is not None:
                    if (days_since - rule.min_days_since_last) % rule.repeat_every_days != 0:
                        continue
            triggered.append((rule, task))

        event_payloads: list[tuple[str, str, str]] = []
        if config.events:
            active_cats = session.exec(
                select(Cat).where(Cat.is_active == True)  # noqa: E712
            ).all()
            today = now_local.date()
            event_by_type = {event.event_type: event for event in config.events}

            birthday_event = event_by_type.get("cat_birthday")
            if birthday_event:
                birthday_cats = []
                for cat in active_cats:
                    if cat.birthday and birthday_matches(cat.birthday, today):
                        years = today.year - cat.birthday.year
                        birthday_cats.append({"name": cat.name, "years": years})
                if birthday_cats:
                    cats_list = ", ".join(cat["name"] for cat in birthday_cats)
                    title = birthday_event.title or "KittyLog"
                    message_template = birthday_event.message or "Birthday today: {cats}."
                    message = message_template.format(
                        cat=birthday_cats[0]["name"],
                        cats=cats_list,
                        count=len(birthday_cats),
                        years=birthday_cats[0]["years"],
                    )
                    event_payloads.append((birthday_event.event_id, title, message))

            milestone_event = event_by_type.get("cat_milestone")
            if milestone_event and milestone_event.months:
                milestones = []
                for cat in active_cats:
                    if not cat.birthday:
                        continue
                    months = months_since_birth(cat.birthday, today)
                    if months is not None and months in milestone_event.months:
                        milestones.append({"name": cat.name, "months": months})
                if milestones:
                    items_text = ", ".join(
                        f"{item['name']} ({item['months']}m)" for item in milestones
                    )
                    title = milestone_event.title or "KittyLog"
                    message_template = milestone_event.message or "Milestones today: {items}."
                    message = message_template.format(
                        cat=milestones[0]["name"],
                        cats=", ".join(item["name"] for item in milestones),
                        count=len(milestones),
                        months=milestones[0]["months"],
                        items=items_text,
                    )
                    event_payloads.append((milestone_event.event_id, title, message))

        if not triggered and not event_payloads:
            print("No rules triggered.")
            return 0

        subscriptions = session.exec(
            select(PushSubscription).where(PushSubscription.is_active == True)  # noqa: E712
        ).all()
        if not subscriptions:
            print("No active push subscriptions.")
            return 0

        logs = session.exec(
            select(NotificationLog).where(NotificationLog.day_key == day_key)
        ).all()
        sent_keys = {
            (log.subscription_id, log.group_id or log.rule_id) for log in logs
        }

        grouped: dict[str, list[tuple[RuleConfig, TaskType]]] = {}
        singles: list[tuple[RuleConfig, TaskType]] = []
        for rule, task in triggered:
            if rule.group:
                grouped.setdefault(rule.group, []).append((rule, task))
            else:
                singles.append((rule, task))

        for group_id, rules in list(grouped.items()):
            if len(rules) <= 1:
                singles.extend(rules)
                grouped.pop(group_id, None)

        notifications_sent = 0

        for subscription in subscriptions:
            for group_id, rules in grouped.items():
                key = (subscription.id, group_id)
                if key in sent_keys:
                    continue
                task_names = ", ".join(sorted({task.name for _, task in rules}))
                group_cfg = config.groups.get(group_id)
                title = group_cfg.title if group_cfg else "KittyLog"
                message_template = group_cfg.message if group_cfg else "Tasks missing: {tasks}."
                message = message_template.format(tasks=task_names)
                if args.dry_run:
                    print(f"[dry-run] {subscription.user}: {title} - {message}")
                else:
                    try:
                        send_web_push(
                            subscription,
                            title,
                            message,
                            config.click_url,
                            push_settings.vapid_private_key,
                            push_settings.vapid_subject,
                        )
                        session.add(
                            NotificationLog(
                                subscription_id=subscription.id,
                                rule_id=group_id,
                                group_id=group_id,
                                day_key=day_key,
                            )
                        )
                        sent_keys.add(key)
                        notifications_sent += 1
                    except WebPushException as exc:
                        status = exc.response and exc.response.status_code
                        print(f"Push failed for {subscription.endpoint}: {exc}", file=sys.stderr)
                        if status in (404, 410):
                            subscription.is_active = False
                if not args.dry_run:
                    session.commit()

            for rule, task in singles:
                key = (subscription.id, rule.rule_id)
                if key in sent_keys:
                    continue
                title = rule.title or "KittyLog"
                message = rule.message or build_default_message(task.name)
                if args.dry_run:
                    print(f"[dry-run] {subscription.user}: {title} - {message}")
                    continue
                try:
                    send_web_push(
                        subscription,
                        title,
                        message,
                        config.click_url,
                        push_settings.vapid_private_key,
                        push_settings.vapid_subject,
                    )
                    session.add(
                        NotificationLog(
                            subscription_id=subscription.id,
                            rule_id=rule.rule_id,
                            group_id=None,
                            day_key=day_key,
                        )
                    )
                    sent_keys.add(key)
                    notifications_sent += 1
                except WebPushException as exc:
                    status = exc.response and exc.response.status_code
                    print(f"Push failed for {subscription.endpoint}: {exc}", file=sys.stderr)
                    if status in (404, 410):
                        subscription.is_active = False
                if not args.dry_run:
                    session.commit()

            for event_id, title, message in event_payloads:
                key = (subscription.id, event_id)
                if key in sent_keys:
                    continue
                if args.dry_run:
                    print(f"[dry-run] {subscription.user}: {title} - {message}")
                    continue
                try:
                    send_web_push(
                        subscription,
                        title,
                        message,
                        config.click_url,
                        push_settings.vapid_private_key,
                        push_settings.vapid_subject,
                    )
                    session.add(
                        NotificationLog(
                            subscription_id=subscription.id,
                            rule_id=event_id,
                            group_id=None,
                            day_key=day_key,
                        )
                    )
                    sent_keys.add(key)
                    notifications_sent += 1
                except WebPushException as exc:
                    status = exc.response and exc.response.status_code
                    print(f"Push failed for {subscription.endpoint}: {exc}", file=sys.stderr)
                    if status in (404, 410):
                        subscription.is_active = False
                if not args.dry_run:
                    session.commit()

        if args.dry_run:
            return 0
        print(f"Notifications sent: {notifications_sent}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

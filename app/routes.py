from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import io
import csv
import secrets
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from pywebpush import WebPushException
from sqlalchemy import and_, func
from sqlmodel import Session, select

from .auth import (
    authenticate_user,
    check_rate_limit,
    log_auth_event,
    generate_csrf_token,
    validate_csrf_token,
    resolve_user_name,
)
from .database import get_session
from .settings import get_settings
from .i18n import resolve_language, translate, SUPPORTED_LANGS
from .models import Cat, PushSubscription, TaskEvent, TaskType, UserNotificationPreference
from .push_config import get_push_settings
from .version import get_version
from scripts.dispatch_notifications import load_notification_config, send_web_push


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["t"] = translate
templates.env.globals["supported_langs"] = SUPPORTED_LANGS
templates.env.globals["app_version"] = get_version()
router = APIRouter()
PER_PAGE = 20
CAT_UPLOAD_DIR = Path(__file__).parent / "static" / "uploads" / "cats"


class PushSubscriptionIn(BaseModel):
    endpoint: str
    keys: dict[str, str]


class PushUnsubscribeIn(BaseModel):
    endpoint: str


class LogNotificationPreferenceIn(BaseModel):
    enabled: bool


def require_user(request: Request) -> str:
    """Ensure a session user is present, otherwise redirect to login."""
    user = request.session.get("user")
    if user:
        request.session.setdefault("csrf_token", generate_csrf_token())
        return user
    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    login_url = f"/login?next={quote(next_url, safe='')}"
    raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": login_url})


def safe_redirect_target(target: str | None, default: str = "/") -> str:
    """Return a path-only redirect target, falling back to default."""
    if not target:
        return default
    target = str(target).strip()
    if target.startswith("//"):
        return default
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return default
    if not target.startswith("/"):
        return default
    return target


def parse_cat_id(raw_value: str | int | None) -> int | None:
    """Convert cat id input to an int or None, raising for invalid values."""
    if raw_value is None:
        return None
    value_str = str(raw_value).strip()
    if not value_str:
        return None
    try:
        value = int(value_str)
    except (TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cat selection")
    if value <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cat selection")
    return value


def parse_birthday(raw_value: str | None) -> date | None:
    """Parse optional birthday string into a date."""
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid birthday")


def validate_cat_for_task(session: Session, task: TaskType, cat_id: int | None) -> Cat | None:
    """Ensure cat selection aligns with task requirements."""
    if task.requires_cat and cat_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cat required for this task")
    if cat_id is None:
        return None
    cat = session.exec(select(Cat).where(Cat.id == cat_id)).first()
    if cat is None or not cat.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cat for this task")
    return cat


def _save_cat_photo(photo: UploadFile | None) -> str | None:
    """Persist uploaded cat photo and return its static path."""
    if photo is None or not photo.filename:
        return None
    if photo.content_type and not photo.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cat photo must be an image")
    suffix = Path(photo.filename).suffix or ".jpg"
    filename = f"{secrets.token_hex(8)}{suffix}"
    CAT_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = CAT_UPLOAD_DIR / filename
    photo.file.seek(0)
    with dest_path.open("wb") as buffer:
        shutil.copyfileobj(photo.file, buffer)
    return f"/static/uploads/cats/{filename}"


def current_user(request: Request) -> str | None:
    """Return current session user or None."""
    return request.session.get("user")


def ensure_csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = generate_csrf_token()
        request.session["csrf_token"] = token
    return token


def api_key_user(request: Request) -> str | None:
    """Return an API user if the X-API-Key header matches configured key."""
    api_key = get_settings().api_key
    if not api_key:
        return None
    header_key = request.headers.get("X-API-Key")
    if header_key and secrets.compare_digest(header_key, api_key):
        return get_settings().api_user or "api"
    return None


def require_user_or_api(request: Request) -> str:
    """Allow API key auth as a fallback to session user."""
    api_user = api_key_user(request)
    if api_user:
        request.state.api_user = api_user
        return api_user
    return require_user(request)


def parse_date_param(raw_value: str | None, field_name: str) -> date | None:
    """Parse an ISO date query parameter while allowing empty values."""
    if raw_value is None:
        return None
    value = raw_value.strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {field_name}"
        )


def resolve_date_preset(
    preset: str | None,
    start_date: date | None,
    end_date: date | None,
) -> tuple[date | None, date | None]:
    """Apply preset date range if no explicit dates are provided."""
    if preset and not start_date and not end_date:
        today = date.today()
        if preset == "today":
            return today, today
        if preset == "7d":
            return today - timedelta(days=6), today
        if preset == "30d":
            return today - timedelta(days=29), today
    return start_date, end_date


def parse_timestamp_value(raw_value: str | None) -> datetime:
    """Parse a datetime input (typically datetime-local) into a naive UTC datetime."""
    if raw_value is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Timestamp is required")
    value = raw_value.strip()
    if not value:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Timestamp is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timestamp format")
    if parsed.tzinfo:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def humanize_timestamp(ts: datetime | None, lang: str = "en") -> str:
    """Return a short relative time string."""
    if ts is None:
        return "Never" if lang == "en" else "Noch nie"
    delta = now_utc() - ts
    if delta < timedelta(minutes=1):
        return "just now" if lang == "en" else "gerade eben"
    if delta < timedelta(hours=1):
        minutes = int(delta.total_seconds() // 60)
        return f"{minutes}m ago" if lang == "en" else f"{minutes} Min. her"
    if delta < timedelta(days=1):
        hours = int(delta.total_seconds() // 3600)
        return f"{hours}h ago" if lang == "en" else f"{hours} Std. her"
    days = delta.days
    return f"{days}d ago" if lang == "en" else f"{days} Tg. her"


def recency_state(ts: datetime | None) -> str:
    """Return recency bucket: fresh, warm, stale, never."""
    if ts is None:
        return "never"
    delta = now_utc() - ts
    if delta < timedelta(hours=6):
        return "fresh"
    if delta < timedelta(days=1):
        return "warm"
    return "stale"


def create_event(
    session: Session,
    task: TaskType,
    who: str | None,
    note: str | None,
    source: str,
    cat_id: int | None = None,
) -> TaskEvent:
    event = TaskEvent(
        task_type_id=task.id,
        cat_id=cat_id,
        who=who or None,
        note=note or None,
        source=source,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def _load_log_notification_settings() -> tuple[str, str, str]:
    config_path = Path(__file__).resolve().parent.parent / "config" / "notifications.yml"
    try:
        config = load_notification_config(config_path)
        return config.log_event_title, config.log_event_message, config.click_url
    except Exception:
        return "KittyLog", "{task} logged.", "/"


def _format_log_message(
    message_template: str,
    task_name: str,
    who: str | None,
    cat_name: str | None,
    note: str | None,
) -> str:
    values = {
        "task": task_name,
        "who": who or "Someone",
        "cat": cat_name or "",
        "note": note or "",
    }
    try:
        return message_template.format(**values)
    except KeyError:
        return f"{task_name} logged."


def dispatch_log_notifications(
    session: Session,
    task: TaskType,
    who: str | None,
    cat_name: str | None,
    note: str | None,
) -> None:
    prefs = session.exec(
        select(UserNotificationPreference).where(UserNotificationPreference.notify_on_log == True)  # noqa: E712
    ).all()
    if not prefs:
        return
    allowed_users = {pref.username for pref in prefs}
    subscriptions = session.exec(
        select(PushSubscription).where(PushSubscription.is_active == True)  # noqa: E712
    ).all()
    if not subscriptions:
        return
    push_settings = get_push_settings()
    if not push_settings.vapid_private_key:
        return
    title, message_template, click_url = _load_log_notification_settings()
    message = _format_log_message(message_template, task.name, who, cat_name, note)
    actor_key = who.casefold() if who else None

    for subscription in subscriptions:
        if subscription.user not in allowed_users:
            continue
        if actor_key and subscription.user.casefold() == actor_key:
            continue
        try:
            send_web_push(
                subscription,
                title,
                message,
                click_url,
                push_settings.vapid_private_key,
                push_settings.vapid_subject,
            )
        except WebPushException as exc:
            status = exc.response and exc.response.status_code
            if status in (404, 410):
                subscription.is_active = False
    session.commit()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = Query("/")) -> Any:
    lang = resolve_language(request)
    existing_user = current_user(request)
    if existing_user:
        redirect_target = safe_redirect_target(next)
        return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    request.session["csrf_token"] = generate_csrf_token()
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "lang": lang,
            "next": next,
            "error": None,
            "user": None,
            "csrf_token": request.session["csrf_token"],
        },
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    csrf_token: str = Form(""),
) -> Any:
    lang = resolve_language(request)
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{username}"
    if not check_rate_limit(rate_key):
        log_auth_event(username, client_ip, False, reason="rate_limit")
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "request": request,
                "lang": lang,
                "next": next,
                "error": translate("login_rate_limited", lang),
                "user": None,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
    if authenticate_user(username, password):
        request.session["user"] = username
        log_auth_event(username, client_ip, True)
        redirect_target = safe_redirect_target(next)
        return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    log_auth_event(username, client_ip, False, reason="invalid_credentials")
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "lang": lang,
            "next": next,
            "error": translate("login_error", lang),
            "user": None,
        },
        status_code=status.HTTP_401_UNAUTHORIZED,
    )


@router.post("/logout")
def logout(
    request: Request,
    next: str = Form("/login"),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    redirect_target = safe_redirect_target(next, default="/login")
    request.session.clear()
    response = RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("kittylog_session")
    return response


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    ensure_csrf_token(request)
    push_settings = get_push_settings()
    all_cats = session.exec(
        select(Cat)
        .order_by(Cat.is_active.desc(), Cat.name)
    ).all()
    cats = [c for c in all_cats if c.is_active]
    cat_map = {c.id: c for c in all_cats}
    tasks = session.exec(
        select(TaskType)
        .where(TaskType.is_active == True)
        .order_by(TaskType.sort_order, TaskType.name)  # noqa: E712
    ).all()
    last_events: dict[int, TaskEvent | None] = {}
    for task in tasks:
        last_events[task.id] = session.exec(
            select(TaskEvent)
            .where(TaskEvent.task_type_id == task.id, TaskEvent.deleted == False)  # noqa: E712
            .order_by(TaskEvent.timestamp.desc())
            .limit(1)
        ).first()
    response = templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "request": request,
            "tasks": tasks,
            "last_events": last_events,
            "cats": cats,
            "cat_map": cat_map,
            "humanize": humanize_timestamp,
            "recency_state": recency_state,
            "lang": lang,
            "user": user,
            "vapid_public_key": push_settings.vapid_public_key,
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.get("/insights", response_class=HTMLResponse)
def insights(
    request: Request,
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    preset: str | None = Query(None, pattern="^(today|7d|30d)$"),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    ensure_csrf_token(request)
    now = now_utc()
    since_7 = now - timedelta(days=7)
    since_30 = now - timedelta(days=30)

    start_date_value = parse_date_param(start_date, "start_date")
    end_date_value = parse_date_param(end_date, "end_date")
    start_date_value, end_date_value = resolve_date_preset(preset, start_date_value, end_date_value)

    event_filters = [TaskEvent.deleted == False]  # noqa: E712
    if start_date_value:
        start_dt = datetime.combine(start_date_value, time.min)
        event_filters.append(TaskEvent.timestamp >= start_dt)
    if end_date_value:
        end_dt = datetime.combine(end_date_value, time.max)
        event_filters.append(TaskEvent.timestamp <= end_dt)

    total_all = session.exec(
        select(func.count()).select_from(TaskEvent).where(*event_filters)
    ).one()
    total_7d = session.exec(
        select(func.count())
        .select_from(TaskEvent)
        .where(TaskEvent.deleted == False, TaskEvent.timestamp >= since_7)  # noqa: E712
    ).one()
    total_30d = session.exec(
        select(func.count())
        .select_from(TaskEvent)
        .where(TaskEvent.deleted == False, TaskEvent.timestamp >= since_30)  # noqa: E712
    ).one()

    task_rows = session.exec(
        select(TaskType.id, TaskType.name, TaskType.icon, func.count(TaskEvent.id))
        .join(TaskEvent, TaskEvent.task_type_id == TaskType.id)
        .where(
            TaskType.is_active == True,  # noqa: E712
            *event_filters,
        )
        .group_by(TaskType.id)
        .order_by(func.count(TaskEvent.id).desc())
    ).all()
    top_tasks = [
        {"id": row[0], "name": row[1], "icon": row[2], "count": int(row[3])}
        for row in task_rows
    ]

    user_rows = session.exec(
        select(TaskEvent.who, func.count(TaskEvent.id))
        .where(*event_filters)
        .group_by(TaskEvent.who)
        .order_by(func.count(TaskEvent.id).desc())
    ).all()
    top_users = []
    for who, count in user_rows:
        name = (who or "").strip() if who else ""
        top_users.append({"name": name or None, "count": int(count)})

    cat_rows = session.exec(
        select(Cat.id, Cat.name, func.count(TaskEvent.id))
        .join(TaskEvent, TaskEvent.cat_id == Cat.id)
        .where(*event_filters)
        .group_by(Cat.id)
        .order_by(func.count(TaskEvent.id).desc())
    ).all()
    cat_counts = [
        {"id": row[0], "name": row[1], "count": int(row[2])}
        for row in cat_rows
    ]
    cat_logged_total = sum(item["count"] for item in cat_counts)
    no_cat_count = max(int(total_30d) - cat_logged_total, 0)

    hour_rows = session.exec(
        select(func.strftime("%H", TaskEvent.timestamp), func.count(TaskEvent.id))
        .where(*event_filters)
        .group_by(func.strftime("%H", TaskEvent.timestamp))
    ).all()
    hour_counts = {int(row[0]): int(row[1]) for row in hour_rows if row[0] is not None}
    hourly = [{"hour": hour, "count": hour_counts.get(hour, 0)} for hour in range(24)]

    recency_rows = session.exec(
        select(TaskType.id, TaskType.name, TaskType.icon, func.max(TaskEvent.timestamp))
        .join(
            TaskEvent,
            (TaskEvent.task_type_id == TaskType.id) & and_(*event_filters),
            isouter=True,
        )
        .where(TaskType.is_active == True)  # noqa: E712
        .group_by(TaskType.id)
        .order_by(TaskType.sort_order, TaskType.name)
    ).all()
    task_recency = []
    for task_id, name, icon, last_ts in recency_rows:
        days_since = (now - last_ts).days if last_ts else None
        task_recency.append(
            {
                "id": task_id,
                "name": name,
                "icon": icon,
                "last_ts": last_ts,
                "days_since": days_since,
            }
        )

    def _with_percent(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        max_count = max((item["count"] for item in items), default=0)
        for item in items:
            item["pct"] = int((item["count"] / max_count) * 100) if max_count else 0
        return items

    top_tasks = _with_percent(top_tasks)
    top_users = _with_percent(top_users)
    cat_counts = _with_percent(cat_counts)
    hourly = _with_percent(hourly)

    task_totals_rows = session.exec(
        select(
            TaskType.id,
            TaskType.name,
            TaskType.icon,
            func.count(TaskEvent.id),
            func.count(func.distinct(func.date(TaskEvent.timestamp))),
        )
        .join(TaskEvent, TaskEvent.task_type_id == TaskType.id)
        .where(
            TaskType.is_active == True,  # noqa: E712
            *event_filters,
        )
        .group_by(TaskType.id)
        .order_by(TaskType.sort_order, TaskType.name)
    ).all()

    task_time_map: dict[int, dict[str, Any]] = {}
    for task_id, name, icon, total_count, distinct_days in task_totals_rows:
        task_time_map[task_id] = {
            "id": task_id,
            "name": name,
            "icon": icon,
            "hours": {hour: 0 for hour in range(24)},
            "distinct_days": int(distinct_days or 0),
            "total": int(total_count or 0),
        }

    task_hour_rows = session.exec(
        select(
            TaskType.id,
            func.strftime("%H", TaskEvent.timestamp),
            func.count(TaskEvent.id),
        )
        .join(TaskEvent, TaskEvent.task_type_id == TaskType.id)
        .where(
            TaskType.is_active == True,  # noqa: E712
            *event_filters,
        )
        .group_by(TaskType.id, func.strftime("%H", TaskEvent.timestamp))
    ).all()

    for task_id, hour_str, hour_count in task_hour_rows:
        entry = task_time_map.get(task_id)
        if not entry or hour_str is None:
            continue
        entry["hours"][int(hour_str)] += int(hour_count)

    task_time = []
    for entry in task_time_map.values():
        if entry["distinct_days"] < 7 and entry["total"] < 7:
            continue
        max_count = max(entry["hours"].values()) if entry["hours"] else 0
        entry["hourly"] = [
            {
                "hour": hour,
                "count": entry["hours"][hour],
                "pct": int((entry["hours"][hour] / max_count) * 100) if max_count else 0,
            }
            for hour in range(24)
        ]
        task_time.append(entry)

    response = templates.TemplateResponse(
        request,
        "insights.html",
        {
            "request": request,
            "lang": lang,
            "user": user,
            "total_all": int(total_all),
            "total_7d": int(total_7d),
            "total_30d": int(total_30d),
            "top_tasks": top_tasks,
            "top_users": top_users,
            "cat_counts": cat_counts,
            "no_cat_count": no_cat_count,
            "hourly": hourly,
            "task_time": task_time,
            "task_recency": task_recency,
            "humanize": humanize_timestamp,
            "start_date": start_date_value,
            "end_date": end_date_value,
            "preset": preset,
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.get("/api/push/public-key")
def push_public_key() -> dict[str, str | None]:
    settings = get_push_settings()
    return {"public_key": settings.vapid_public_key}


@router.post("/api/push/subscribe")
def push_subscribe(
    payload: PushSubscriptionIn,
    request: Request,
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    csrf_token = request.headers.get("X-CSRF-Token", "")
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    endpoint = payload.endpoint.strip()
    keys = payload.keys or {}
    p256dh = (keys.get("p256dh") or "").strip()
    auth = (keys.get("auth") or "").strip()
    if not endpoint or not p256dh or not auth:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subscription payload")

    existing = session.exec(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    ).first()
    now = now_utc()
    if existing:
        existing.user = user
        existing.p256dh = p256dh
        existing.auth = auth
        existing.last_seen_at = now
        existing.is_active = True
    else:
        session.add(
            PushSubscription(
                user=user,
                endpoint=endpoint,
                p256dh=p256dh,
                auth=auth,
                user_agent=request.headers.get("user-agent"),
                created_at=now,
                last_seen_at=now,
                is_active=True,
            )
        )
    session.commit()
    return {"status": "ok"}


@router.post("/api/push/unsubscribe")
def push_unsubscribe(
    payload: PushUnsubscribeIn,
    request: Request,
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, str]:
    csrf_token = request.headers.get("X-CSRF-Token", "")
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    endpoint = payload.endpoint.strip()
    if not endpoint:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid subscription payload")
    existing = session.exec(
        select(PushSubscription).where(PushSubscription.endpoint == endpoint)
    ).first()
    if existing:
        existing.is_active = False
        existing.last_seen_at = now_utc()
        session.commit()
    return {"status": "ok"}


@router.post("/api/push/log-preference")
def update_log_preference(
    payload: LogNotificationPreferenceIn,
    request: Request,
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> dict[str, str | bool]:
    csrf_token = request.headers.get("X-CSRF-Token", "")
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    existing = session.exec(
        select(UserNotificationPreference).where(UserNotificationPreference.username == user)
    ).first()
    now = now_utc()
    if existing:
        existing.notify_on_log = payload.enabled
        existing.updated_at = now
    else:
        session.add(
            UserNotificationPreference(
                username=user,
                notify_on_log=payload.enabled,
                updated_at=now,
            )
        )
    session.commit()
    return {"status": "ok", "enabled": payload.enabled}


@router.get("/cats", response_class=HTMLResponse)
def cats_page(
    request: Request,
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    ensure_csrf_token(request)
    cats = session.exec(
        select(Cat).order_by(Cat.is_active.desc(), Cat.name)
    ).all()
    response = templates.TemplateResponse(
        request,
        "cats.html",
        {
            "request": request,
            "cats": cats,
            "lang": lang,
            "user": user,
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.get("/settings", response_class=HTMLResponse)
def settings_page(
    request: Request,
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    ensure_csrf_token(request)
    push_settings = get_push_settings()
    preference = session.exec(
        select(UserNotificationPreference).where(UserNotificationPreference.username == user)
    ).first()
    response = templates.TemplateResponse(
        request,
        "settings.html",
        {
            "request": request,
            "lang": lang,
            "user": user,
            "vapid_public_key": push_settings.vapid_public_key,
            "notify_on_log": preference.notify_on_log if preference else False,
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.post("/cats", response_class=HTMLResponse)
def create_cat(
    request: Request,
    name: str = Form(...),
    color: str = Form(""),
    birthday: str = Form(""),
    chip_id: str = Form(""),
    photo: UploadFile | None = File(None),
    csrf_token: str = Form(""),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    lang = resolve_language(request)
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required")
    birthday_value = parse_birthday(birthday)
    photo_path = _save_cat_photo(photo)
    cat = Cat(
        name=clean_name,
        color=color.strip() or None,
        birthday=birthday_value,
        chip_id=chip_id.strip() or None,
        photo_path=photo_path,
        is_active=True,
    )
    session.add(cat)
    session.commit()
    redirect_url = f"/cats?lang={lang}"
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.post("/cats/{cat_id}/update", response_class=HTMLResponse)
def update_cat(
    request: Request,
    cat_id: int,
    name: str = Form(...),
    color: str = Form(""),
    birthday: str = Form(""),
    chip_id: str = Form(""),
    is_active: bool = Form(False),
    photo: UploadFile | None = File(None),
    csrf_token: str = Form(""),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    lang = resolve_language(request)
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    cat = session.exec(select(Cat).where(Cat.id == cat_id)).first()
    if cat is None:
        raise HTTPException(status_code=404, detail="Cat not found")
    clean_name = name.strip()
    if not clean_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name is required")
    cat.name = clean_name
    cat.color = color.strip() or None
    cat.birthday = parse_birthday(birthday)
    cat.chip_id = chip_id.strip() or None
    cat.is_active = bool(is_active)
    new_photo = _save_cat_photo(photo)
    if new_photo:
        cat.photo_path = new_photo
    session.add(cat)
    session.commit()
    redirect_url = f"/cats?lang={lang}"
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.post("/cats/{cat_id}/delete")
def delete_cat(
    request: Request,
    cat_id: int,
    csrf_token: str = Form(""),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    lang = resolve_language(request)
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    cat = session.exec(select(Cat).where(Cat.id == cat_id)).first()
    if cat is None:
        raise HTTPException(status_code=404, detail="Cat not found")
    cat.is_active = False
    session.add(cat)
    session.commit()
    redirect_url = f"/cats?lang={lang}"
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    task: str | None = Query(None),
    cat: str | int | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    preset: str | None = Query(None, pattern="^(today|7d|30d)$"),
    page: int = Query(1, ge=1),
    format: str | None = Query(None),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    ensure_csrf_token(request)
    base_query = select(TaskEvent).where(TaskEvent.deleted == False)  # noqa: E712
    if task:
        base_query = base_query.join(TaskType).where(TaskType.slug == task)
    selected_cat_id = parse_cat_id(cat)
    if selected_cat_id:
        base_query = base_query.where(TaskEvent.cat_id == selected_cat_id)
    start_date_value = parse_date_param(start_date, "start_date")
    end_date_value = parse_date_param(end_date, "end_date")
    start_date_value, end_date_value = resolve_date_preset(preset, start_date_value, end_date_value)
    if start_date_value:
        start_dt = datetime.combine(start_date_value, time.min)
        base_query = base_query.where(TaskEvent.timestamp >= start_dt)
    if end_date_value:
        end_dt = datetime.combine(end_date_value, time.max)
        base_query = base_query.where(TaskEvent.timestamp <= end_dt)

    query = base_query.order_by(TaskEvent.timestamp.desc())

    if format == "csv":
        all_events = session.exec(query).all()
        task_types = session.exec(
            select(TaskType).order_by(TaskType.sort_order, TaskType.name)
        ).all()
        task_map = {t.id: t for t in task_types}
        cats = session.exec(select(Cat)).all()
        cat_map = {c.id: c for c in cats}

        def _iter_rows() -> Any:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["timestamp", "task_slug", "task_name", "cat_name", "who", "note", "source"])
            for ev in all_events:
                task = task_map.get(ev.task_type_id)
                cat = cat_map.get(ev.cat_id) if ev.cat_id else None
                writer.writerow(
                    [
                        ev.timestamp.isoformat(),
                        task.slug if task else "",
                        task.name if task else "",
                        cat.name if cat else "",
                        ev.who or "",
                        ev.note or "",
                        ev.source or "",
                    ]
                )
            buffer.seek(0)
            yield buffer.read()

        filename = f"kittylog-history-page{page}.csv"
        return StreamingResponse(
            _iter_rows(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    total_count = session.exec(select(func.count()).select_from(base_query.subquery())).one()
    if isinstance(total_count, tuple):
        total_count = total_count[0]
    offset = (page - 1) * PER_PAGE
    events = session.exec(query.offset(offset).limit(PER_PAGE)).all()
    task_types = session.exec(select(TaskType).order_by(TaskType.sort_order, TaskType.name)).all()
    cats = session.exec(select(Cat).order_by(Cat.is_active.desc(), Cat.name)).all()
    task_map = {t.id: t for t in task_types}
    cat_map = {c.id: c for c in cats}
    filter_values = {
        "task": task,
        "cat": selected_cat_id or "",
        "start_date": start_date_value.isoformat() if start_date_value else "",
        "end_date": end_date_value.isoformat() if end_date_value else "",
        "preset": preset,
    }

    response = templates.TemplateResponse(
        request,
        "history.html",
        {
            "request": request,
            "events": events,
            "tasks": task_types,
            "task_map": task_map,
            "cats": cats,
            "cat_map": cat_map,
            "selected_task": task,
            "selected_cat": selected_cat_id,
            "start_date": start_date_value,
            "end_date": end_date_value,
            "preset": preset,
            "page": page,
            "per_page": PER_PAGE,
            "total_count": total_count,
            "filter_values": filter_values,
            "humanize": humanize_timestamp,
            "recency_state": recency_state,
            "lang": lang,
            "user": user,
        },
    )
    request.session.setdefault("csrf_token", generate_csrf_token())
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.post("/history/{event_id}/update-time")
def update_event_time(
    request: Request,
    event_id: int,
    timestamp: str = Form(...),
    csrf_token: str = Form(""),
    _user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    lang = resolve_language(request)
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    event = session.exec(
        select(TaskEvent).where(TaskEvent.id == event_id, TaskEvent.deleted == False)  # noqa: E712
    ).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")

    event.timestamp = parse_timestamp_value(timestamp)
    session.add(event)
    session.commit()

    params = dict(request.query_params)
    params["lang"] = lang
    redirect_url = "/history"
    if params:
        redirect_url = f"/history?{urlencode(params, doseq=True)}"

    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.post("/history/{event_id}/delete")
def delete_event(
    request: Request,
    event_id: int,
    csrf_token: str = Form(""),
    _user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    lang = resolve_language(request)
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    event = session.exec(
        select(TaskEvent).where(TaskEvent.id == event_id, TaskEvent.deleted == False)  # noqa: E712
    ).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event.deleted = True
    session.add(event)
    session.commit()

    params = dict(request.query_params)
    params["lang"] = lang
    redirect_url = "/history"
    if params:
        redirect_url = f"/history?{urlencode(params, doseq=True)}"

    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.post("/log", response_class=HTMLResponse)
def log_task(
    request: Request,
    slug: str = Form(...),
    who: str | None = Form(None),
    note: str | None = Form(None),
    cat_id: str | None = Form(None),
    csrf_token: str = Form(""),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    task = session.exec(select(TaskType).where(TaskType.slug == slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    actor = user
    if who and who.strip():
        resolved = resolve_user_name(who)
        if not resolved:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown user")
        actor = resolved
    cat_id_value = parse_cat_id(cat_id)
    cat = validate_cat_for_task(session, task, cat_id_value)
    event = create_event(session, task, actor, note, source="web", cat_id=cat.id if cat else None)
    try:
        dispatch_log_notifications(session, task, actor, cat.name if cat else None, note)
    except Exception:
        pass
    response = templates.TemplateResponse(
        request,
        "qr_confirm.html",
        {
            "request": request,
            "task": task,
            "event": event,
            "auto": True,
            "message": translate("confirm_message_logged", lang),
            "lang": lang,
            "user": user,
            "cat": cat,
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.get("/q/{task_slug}", response_class=HTMLResponse)
def qr_landing(
    request: Request,
    task_slug: str,
    auto: int = 0,
    note: str | None = None,
    cat_id: int | None = Query(None),
    user: str = Depends(require_user_or_api),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    ensure_csrf_token(request)
    task = session.exec(select(TaskType).where(TaskType.slug == task_slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    active_cats = session.exec(
        select(Cat)
        .where(Cat.is_active == True)  # noqa: E712
        .order_by(Cat.name)
    ).all()
    selected_cat = None
    parsed_cat_id = parse_cat_id(cat_id)
    if parsed_cat_id:
        selected_cat = session.exec(select(Cat).where(Cat.id == parsed_cat_id)).first()
        if selected_cat is None or not selected_cat.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid cat selection")

    if auto == 1:
        cat = validate_cat_for_task(session, task, parsed_cat_id)
        event = create_event(session, task, user, note, source="qr", cat_id=cat.id if cat else None)
        try:
            dispatch_log_notifications(session, task, user, cat.name if cat else None, note)
        except Exception:
            pass
        response = templates.TemplateResponse(
            request,
            "qr_confirm.html",
            {
                "request": request,
                "task": task,
                "event": event,
                "auto": True,
                "message": translate("confirm_message_logged", lang),
                "lang": lang,
                "user": user,
                "cat": cat,
            },
        )
    else:
        response = templates.TemplateResponse(
            request,
            "qr_confirm.html",
            {
                "request": request,
                "task": task,
                "event": None,
                "auto": False,
                "note": note,
                "lang": lang,
                "user": user,
                "cats": active_cats,
                "selected_cat": selected_cat,
            },
        )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.post("/q/{task_slug}/confirm", response_class=HTMLResponse)
def qr_confirm(
    request: Request,
    task_slug: str,
    note: str | None = Form(None),
    cat_id: str | None = Form(None),
    csrf_token: str = Form(""),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    if not validate_csrf_token(request.session.get("csrf_token"), csrf_token):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid CSRF token")
    task = session.exec(select(TaskType).where(TaskType.slug == task_slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    cat_id_value = parse_cat_id(cat_id)
    cat = validate_cat_for_task(session, task, cat_id_value)
    event = create_event(session, task, user, note, source="qr", cat_id=cat.id if cat else None)
    try:
        dispatch_log_notifications(session, task, user, cat.name if cat else None, note)
    except Exception:
        pass
    response = templates.TemplateResponse(
        request,
        "qr_confirm.html",
        {
            "request": request,
            "task": task,
            "event": event,
            "auto": True,
            "message": translate("confirm_message_logged", lang),
            "lang": lang,
            "user": user,
            "cat": cat,
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response

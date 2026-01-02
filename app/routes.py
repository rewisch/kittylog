from __future__ import annotations

from datetime import date, datetime, time, timedelta
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
from sqlalchemy import func
from sqlmodel import Session, select

from .auth import (
    authenticate_user,
    check_rate_limit,
    log_auth_event,
    generate_csrf_token,
    validate_csrf_token,
)
from .database import get_session
from .settings import get_settings
from .i18n import resolve_language, translate, SUPPORTED_LANGS
from .models import Cat, TaskEvent, TaskType


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["t"] = translate
templates.env.globals["supported_langs"] = SUPPORTED_LANGS
router = APIRouter()
PER_PAGE = 20
CAT_UPLOAD_DIR = Path(__file__).parent / "static" / "uploads" / "cats"


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


def humanize_timestamp(ts: datetime | None, lang: str = "en") -> str:
    """Return a short relative time string."""
    if ts is None:
        return "Never" if lang == "en" else "Noch nie"
    delta = datetime.utcnow() - ts
    if delta < timedelta(minutes=1):
        return "just now" if lang == "en" else "gerade eben"
    if delta < timedelta(hours=1):
        minutes = int(delta.total_seconds() // 60)
        suffix = "m ago" if lang == "en" else "Min. her"
        return f"{minutes}{suffix if lang == 'en' else f' {suffix}'}"
    if delta < timedelta(days=1):
        hours = int(delta.total_seconds() // 3600)
        suffix = "h ago" if lang == "en" else "Std. her"
        return f"{hours}{suffix if lang == 'en' else f' {suffix}'}"
    days = delta.days
    suffix = "d ago" if lang == "en" else "Tg. her"
    return f"{days}{suffix if lang == 'en' else f' {suffix}'}"


def recency_state(ts: datetime | None) -> str:
    """Return recency bucket: fresh, warm, stale, never."""
    if ts is None:
        return "never"
    delta = datetime.utcnow() - ts
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


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, next: str = Query("/")) -> Any:
    lang = resolve_language(request)
    existing_user = current_user(request)
    if existing_user:
        redirect_target = safe_redirect_target(next)
        return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    request.session["csrf_token"] = generate_csrf_token()
    return templates.TemplateResponse(
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
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


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
    cat: int | None = Query(None),
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
    if preset and not start_date_value and not end_date_value:
        today = date.today()
        if preset == "today":
            start_date_value = today
            end_date_value = today
        elif preset == "7d":
            start_date_value = today - timedelta(days=6)
            end_date_value = today
        elif preset == "30d":
            start_date_value = today - timedelta(days=29)
            end_date_value = today
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


@router.post("/history/{event_id}/delete")
def delete_event(
    request: Request,
    event_id: int,
    csrf_token: str = Form(""),
    user: str = Depends(require_user),
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

    actor = who or user
    cat_id_value = parse_cat_id(cat_id)
    cat = validate_cat_for_task(session, task, cat_id_value)
    event = create_event(session, task, actor, note, source="web", cat_id=cat.id if cat else None)
    response = templates.TemplateResponse(
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
        response = templates.TemplateResponse(
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
    response = templates.TemplateResponse(
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

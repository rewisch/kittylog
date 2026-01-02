from __future__ import annotations

from datetime import date, datetime, time, timedelta
import io
import csv
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlmodel import Session, select

from .auth import authenticate_user
from .database import get_session
from .i18n import resolve_language, translate, SUPPORTED_LANGS
from .models import TaskEvent, TaskType


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["t"] = translate
templates.env.globals["supported_langs"] = SUPPORTED_LANGS
router = APIRouter()
PER_PAGE = 20


def require_user(request: Request) -> str:
    """Ensure a session user is present, otherwise redirect to login."""
    user = request.session.get("user")
    if user:
        return user
    next_url = request.url.path
    if request.url.query:
        next_url = f"{next_url}?{request.url.query}"
    login_url = f"/login?next={quote(next_url, safe='')}"
    raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": login_url})


def current_user(request: Request) -> str | None:
    """Return current session user or None."""
    return request.session.get("user")


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
) -> TaskEvent:
    event = TaskEvent(
        task_type_id=task.id,
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
        redirect_target = next if str(next).startswith("/") else "/"
        return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
    return templates.TemplateResponse(
        "login.html",
        {
            "request": request,
            "lang": lang,
            "next": next,
            "error": None,
            "user": None,
        },
    )


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
) -> Any:
    lang = resolve_language(request)
    if authenticate_user(username, password):
        request.session["user"] = username
        redirect_target = next if str(next).startswith("/") else "/"
        return RedirectResponse(url=redirect_target, status_code=status.HTTP_303_SEE_OTHER)
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
def logout(request: Request, next: str = Form("/login")) -> RedirectResponse:
    redirect_target = next if str(next).startswith("/") else "/login"
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
            "humanize": humanize_timestamp,
            "recency_state": recency_state,
            "lang": lang,
            "user": user,
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    task: str | None = Query(None),
    start_date: str | None = Query(None),
    end_date: str | None = Query(None),
    preset: str | None = Query(None, pattern="^(today|7d|30d)$"),
    page: int = Query(1, ge=1),
    format: str | None = Query(None),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    query = select(TaskEvent).where(TaskEvent.deleted == False).order_by(  # noqa: E712
        TaskEvent.timestamp.desc()
    )
    if task:
        query = query.join(TaskType).where(TaskType.slug == task)
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
        query = query.where(TaskEvent.timestamp >= start_dt)
    if end_date_value:
        end_dt = datetime.combine(end_date_value, time.max)
        query = query.where(TaskEvent.timestamp <= end_dt)

    if format == "csv":
        all_events = session.exec(query).all()
        task_types = session.exec(
            select(TaskType).order_by(TaskType.sort_order, TaskType.name)
        ).all()
        task_map = {t.id: t for t in task_types}

        def _iter_rows() -> Any:
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow(["timestamp", "task_slug", "task_name", "who", "note", "source"])
            for ev in all_events:
                task = task_map.get(ev.task_type_id)
                writer.writerow(
                    [
                        ev.timestamp.isoformat(),
                        task.slug if task else "",
                        task.name if task else "",
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

    total_count = session.exec(
        select(func.count()).select_from(query.subquery())
    ).one()
    if isinstance(total_count, tuple):
        total_count = total_count[0]
    offset = (page - 1) * PER_PAGE
    events = session.exec(query.offset(offset).limit(PER_PAGE)).all()
    task_types = session.exec(select(TaskType).order_by(TaskType.sort_order, TaskType.name)).all()
    task_map = {t.id: t for t in task_types}
    filter_values = {
        "task": task,
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
        "selected_task": task,
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


@router.post("/history/{event_id}/delete")
def delete_event(
    request: Request,
    event_id: int,
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    lang = resolve_language(request)
    event = session.exec(
        select(TaskEvent).where(TaskEvent.id == event_id, TaskEvent.deleted == False)  # noqa: E712
    ).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    event.deleted = True
    session.add(event)
    session.commit()

    params = request.query_params.mutablecopy()
    params["lang"] = lang
    redirect_url = "/history"
    if params:
        redirect_url = f"/history?{urlencode(params, doseq=True)}"

    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response


@router.post("/log", response_class=HTMLResponse)
def log_task(
    request: Request,
    slug: str = Form(...),
    who: str | None = Form(None),
    note: str | None = Form(None),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    task = session.exec(select(TaskType).where(TaskType.slug == slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    actor = who or user
    event = create_event(session, task, actor, note, source="web")
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
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    task = session.exec(select(TaskType).where(TaskType.slug == task_slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if auto == 1:
        event = create_event(session, task, user, note, source="qr")
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
            },
        )
        if request.query_params.get("lang"):
            response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
        return response

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
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    task = session.exec(select(TaskType).where(TaskType.slug == task_slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    event = create_event(session, task, user, note, source="qr")
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
        },
    )
    if request.query_params.get("lang"):
        response.set_cookie("lang", lang, max_age=30 * 24 * 3600)
    return response

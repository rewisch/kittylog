from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .auth import authenticate_user
from .database import get_session
from .i18n import resolve_language, translate, SUPPORTED_LANGS
from .models import TaskEvent, TaskType


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
templates.env.globals["t"] = translate
templates.env.globals["supported_langs"] = SUPPORTED_LANGS
router = APIRouter()


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
        select(TaskType).where(TaskType.is_active == True).order_by(TaskType.name)  # noqa: E712
    ).all()
    last_events: dict[int, TaskEvent | None] = {}
    for task in tasks:
        last_events[task.id] = session.exec(
            select(TaskEvent)
            .where(TaskEvent.task_type_id == task.id)
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
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    user: str = Depends(require_user),
    session: Session = Depends(get_session),
) -> Any:
    lang = resolve_language(request)
    query = select(TaskEvent).order_by(TaskEvent.timestamp.desc())
    if task:
        query = query.join(TaskType).where(TaskType.slug == task)
    if start_date:
        start_dt = datetime.combine(start_date, time.min)
        query = query.where(TaskEvent.timestamp >= start_dt)
    if end_date:
        end_dt = datetime.combine(end_date, time.max)
        query = query.where(TaskEvent.timestamp <= end_dt)

    events = session.exec(query).all()
    task_types = session.exec(select(TaskType).order_by(TaskType.name)).all()
    task_map = {t.id: t for t in task_types}

    response = templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "events": events,
            "tasks": task_types,
            "task_map": task_map,
            "selected_task": task,
            "start_date": start_date,
            "end_date": end_date,
            "humanize": humanize_timestamp,
            "lang": lang,
            "user": user,
        },
    )
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

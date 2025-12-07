from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .database import get_session
from .models import TaskEvent, TaskType


templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
router = APIRouter()


def humanize_timestamp(ts: datetime | None) -> str:
    """Return a short relative time string."""
    if ts is None:
        return "Never"
    delta = datetime.utcnow() - ts
    if delta < timedelta(minutes=1):
        return "just now"
    if delta < timedelta(hours=1):
        minutes = int(delta.total_seconds() // 60)
        return f"{minutes}m ago"
    if delta < timedelta(days=1):
        hours = int(delta.total_seconds() // 3600)
        return f"{hours}h ago"
    days = delta.days
    return f"{days}d ago"


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


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)) -> Any:
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
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "tasks": tasks,
            "last_events": last_events,
            "humanize": humanize_timestamp,
        },
    )


@router.get("/history", response_class=HTMLResponse)
def history(
    request: Request,
    task: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    session: Session = Depends(get_session),
) -> Any:
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

    return templates.TemplateResponse(
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
        },
    )


@router.post("/log", response_class=HTMLResponse)
def log_task(
    request: Request,
    slug: str = Form(...),
    who: str | None = Form(None),
    note: str | None = Form(None),
    session: Session = Depends(get_session),
) -> Any:
    task = session.exec(select(TaskType).where(TaskType.slug == slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    event = create_event(session, task, who, note, source="web")
    return templates.TemplateResponse(
        "qr_confirm.html",
        {
            "request": request,
            "task": task,
            "event": event,
            "auto": True,
            "message": "Logged!",
        },
    )


@router.get("/q/{task_slug}", response_class=HTMLResponse)
def qr_landing(
    request: Request,
    task_slug: str,
    auto: int = 0,
    who: str | None = None,
    note: str | None = None,
    session: Session = Depends(get_session),
) -> Any:
    task = session.exec(select(TaskType).where(TaskType.slug == task_slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if auto == 1:
        event = create_event(session, task, who, note, source="qr")
        return templates.TemplateResponse(
            "qr_confirm.html",
            {
                "request": request,
                "task": task,
                "event": event,
                "auto": True,
                "message": "Logged!",
            },
        )

    return templates.TemplateResponse(
        "qr_confirm.html",
        {
            "request": request,
            "task": task,
            "event": None,
            "auto": False,
            "who": who,
            "note": note,
        },
    )


@router.post("/q/{task_slug}/confirm", response_class=HTMLResponse)
def qr_confirm(
    request: Request,
    task_slug: str,
    who: str | None = Form(None),
    note: str | None = Form(None),
    session: Session = Depends(get_session),
) -> Any:
    task = session.exec(select(TaskType).where(TaskType.slug == task_slug)).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    event = create_event(session, task, who, note, source="qr")
    return templates.TemplateResponse(
        "qr_confirm.html",
        {
            "request": request,
            "task": task,
            "event": event,
            "auto": True,
            "message": "Logged!",
        },
    )

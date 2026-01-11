from __future__ import annotations

from sqlmodel import Session, select

from app.database import get_engine
from app.models import Cat, TaskEvent, TaskType

from .conftest import extract_csrf_token, login_user, write_users_file


def test_qr_confirm_requires_csrf(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    response = client.post("/q/feed/confirm", data={"note": "hi", "csrf_token": "bad"})
    assert response.status_code == 400


def test_qr_confirm_logs_event(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    response = client.get("/q/feed")
    csrf = extract_csrf_token(response.text)
    response = client.post(
        "/q/feed/confirm",
        data={"note": "test", "csrf_token": csrf},
    )
    assert response.status_code == 200

    with Session(get_engine()) as session:
        event = session.exec(select(TaskEvent)).first()
        assert event is not None
        assert event.note == "test"


def test_requires_cat_task_rejects_missing_cat(client_requires_cat, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client_requires_cat, "Livia", "secret")

    response = client_requires_cat.get("/")
    csrf = extract_csrf_token(response.text)
    response = client_requires_cat.post(
        "/log",
        data={"slug": "medicine", "who": "Livia", "note": "", "csrf_token": csrf},
    )
    assert response.status_code == 400


def test_requires_cat_task_accepts_active_cat(client_requires_cat, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client_requires_cat, "Livia", "secret")

    with Session(get_engine()) as session:
        cat = Cat(name="Nori", is_active=True)
        session.add(cat)
        session.commit()
        session.refresh(cat)
        cat_id = cat.id

    response = client_requires_cat.get("/")
    csrf = extract_csrf_token(response.text)
    response = client_requires_cat.post(
        "/log",
        data={"slug": "medicine", "who": "Livia", "note": "", "cat_id": str(cat_id), "csrf_token": csrf},
    )
    assert response.status_code == 200

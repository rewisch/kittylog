from __future__ import annotations

from sqlmodel import Session, select

from app.auth import resolve_user_name
from app.database import get_engine
from app.models import TaskEvent

from .conftest import extract_csrf_token, login_user, write_users_file


def test_resolve_user_name_casefold(users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    assert resolve_user_name("livia") == "Livia"
    assert resolve_user_name("LIVIA") == "Livia"
    assert resolve_user_name("Unknown") is None


def test_log_task_rejects_unknown_who(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    response = client.get("/")
    csrf = extract_csrf_token(response.text)
    response = client.post(
        "/log",
        data={"slug": "feed", "who": "Unknown", "note": "", "csrf_token": csrf},
    )
    assert response.status_code == 400


def test_log_task_accepts_casefold_who(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    response = client.get("/")
    csrf = extract_csrf_token(response.text)
    response = client.post(
        "/log",
        data={"slug": "feed", "who": "livia", "note": "", "csrf_token": csrf},
    )
    assert response.status_code == 200

    with Session(get_engine()) as session:
        event = session.exec(select(TaskEvent)).first()
        assert event is not None
        assert event.who == "Livia"

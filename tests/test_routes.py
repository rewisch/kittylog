from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.database import get_engine
from app.models import Cat, TaskEvent, TaskType

from .conftest import extract_csrf_token, login_user, write_users_file


def test_insights_date_filtering(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    with Session(get_engine()) as session:
        task = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()
        assert task is not None
        session.add(
            TaskEvent(
                task_type_id=task.id,
                who="Livia",
                source="web",
                timestamp=datetime.utcnow() - timedelta(days=10),
            )
        )
        session.add(
            TaskEvent(
                task_type_id=task.id,
                who="Livia",
                source="web",
                timestamp=datetime.utcnow(),
            )
        )
        session.commit()

    response = client.get("/insights")
    assert response.status_code == 200
    assert ">2<" in response.text

    future = (datetime.utcnow().date() + timedelta(days=1)).isoformat()
    response = client.get(f"/insights?start_date={future}&end_date={future}")
    assert response.status_code == 200
    assert ">0<" in response.text


def test_push_subscribe_and_unsubscribe(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    response = client.get("/settings")
    csrf = extract_csrf_token(response.text)

    payload = {
        "endpoint": "https://example.com/push/abc",
        "keys": {"p256dh": "key", "auth": "auth"},
    }
    response = client.post("/api/push/subscribe", json=payload, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

    response = client.post("/api/push/unsubscribe", json={"endpoint": payload["endpoint"]}, headers={"X-CSRF-Token": csrf})
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_qr_auto_logging(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    response = client.get("/q/feed?auto=1")
    assert response.status_code == 200

    with Session(get_engine()) as session:
        events = session.exec(select(TaskEvent)).all()
        assert len(events) == 1


def test_create_cat(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    response = client.get("/cats")
    csrf = extract_csrf_token(response.text)
    response = client.post(
        "/cats",
        data={
            "name": "Milo",
            "color": "gray",
            "birthday": "",
            "chip_id": "",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(get_engine()) as session:
        cat = session.exec(select(Cat).where(Cat.name == "Milo")).first()
        assert cat is not None

from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import Session, select

from app.database import get_engine
from app.models import Cat, TaskEvent, TaskType

from .conftest import extract_csrf_token, login_user, write_users_file


def _seed_events() -> tuple[int, int]:
    now = datetime.utcnow()
    with Session(get_engine()) as session:
        task = session.exec(select(TaskType).where(TaskType.slug == "feed")).first()
        assert task is not None
        cat = Cat(name="Milo", is_active=True)
        session.add(cat)
        session.commit()
        session.refresh(cat)

        session.add(
            TaskEvent(
                task_type_id=task.id,
                cat_id=cat.id,
                who="Livia",
                source="web",
                timestamp=now - timedelta(days=1),
                note="yesterday",
            )
        )
        session.add(
            TaskEvent(
                task_type_id=task.id,
                who="Livia",
                source="web",
                timestamp=now,
                note="today",
            )
        )
        session.commit()
        return task.id, cat.id


def test_history_filters_by_cat_and_date(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")
    _, cat_id = _seed_events()

    today = datetime.utcnow().date().isoformat()
    response = client.get(f"/history?cat={cat_id}&start_date={today}&end_date={today}")
    assert response.status_code == 200
    assert "today" in response.text
    assert "yesterday" not in response.text


def test_history_preset_today(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")
    _seed_events()

    response = client.get("/history?preset=today")
    assert response.status_code == 200
    assert "today" in response.text
    assert "yesterday" not in response.text

from __future__ import annotations

from sqlmodel import Session, select

from app.database import get_engine
from app.models import Cat

from .conftest import extract_csrf_token, login_user, write_users_file


def test_update_and_deactivate_cat(client, users_file, monkeypatch) -> None:
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
        cat_id = cat.id

    response = client.get("/cats")
    csrf = extract_csrf_token(response.text)
    response = client.post(
        f"/cats/{cat_id}/update",
        data={
            "name": "Milo",
            "color": "white",
            "birthday": "",
            "chip_id": "",
            "is_active": "true",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    response = client.get("/cats")
    csrf = extract_csrf_token(response.text)
    response = client.post(
        f"/cats/{cat_id}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with Session(get_engine()) as session:
        cat = session.exec(select(Cat).where(Cat.id == cat_id)).first()
        assert cat is not None
        assert cat.is_active is False

from __future__ import annotations

from .conftest import extract_csrf_token, login_user, write_users_file


def test_history_csv_export(client, users_file, monkeypatch) -> None:
    write_users_file(users_file, {"Livia": "secret"})
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(users_file))
    login_user(client, "Livia", "secret")

    response = client.get("/")
    csrf = extract_csrf_token(response.text)
    response = client.post(
        "/log",
        data={"slug": "feed", "who": "Livia", "note": "morning", "csrf_token": csrf},
    )
    assert response.status_code == 200

    response = client.get("/history?format=csv")
    assert response.status_code == 200
    assert response.text.splitlines()[0] == "timestamp,task_slug,task_name,cat_name,who,note,source"

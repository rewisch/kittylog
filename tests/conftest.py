from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("KITTYLOG_SESSION_SECURE", "false")
os.environ.setdefault("KITTYLOG_SECRET_KEY", "test-secret-key")

import app.main as main
from app import auth
from app.auth import encode_password, save_users
from app.config_loader import TaskConfig
from app.settings import AppSettings


def extract_csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match, "CSRF token not found in HTML"
    return match.group(1)


def write_users_file(path: Path, users: dict[str, str]) -> None:
    data = {}
    for username, password in users.items():
        data[username] = {
            "encoded": encode_password(password),
            "active": True,
            "failed_attempts": 0,
        }
    save_users(data, path)


def login_user(client: TestClient, username: str, password: str) -> None:
    response = client.get("/login")
    csrf = extract_csrf_token(response.text)
    response = client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf, "next": "/"},
        follow_redirects=False,
    )
    assert response.status_code == 303


@pytest.fixture()
def users_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "users.txt"
    monkeypatch.setenv("KITTYLOG_USERS_FILE", str(path))
    return path


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, users_file: Path) -> TestClient:
    def fake_load_settings(path: Path | None = None) -> AppSettings:
        return AppSettings(default_language="en", db_path=tmp_path / "test.db", api_key=None, api_user="api")

    monkeypatch.setattr(main, "load_settings", fake_load_settings)
    monkeypatch.setattr(main, "run_startup_migrations", lambda repo_root: None)
    monkeypatch.setattr(
        main,
        "load_task_configs",
        lambda path: [
            TaskConfig(slug="feed", name="Feed", icon="F", color="blue", order=1, requires_cat=False)
        ],
    )

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture()
def client_requires_cat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, users_file: Path) -> TestClient:
    def fake_load_settings(path: Path | None = None) -> AppSettings:
        return AppSettings(default_language="en", db_path=tmp_path / "test_requires_cat.db", api_key=None, api_user="api")

    monkeypatch.setattr(main, "load_settings", fake_load_settings)
    monkeypatch.setattr(main, "run_startup_migrations", lambda repo_root: None)
    monkeypatch.setattr(
        main,
        "load_task_configs",
        lambda path: [
            TaskConfig(slug="feed", name="Feed", icon="F", color="blue", order=1, requires_cat=False),
            TaskConfig(slug="medicine", name="Medicine", icon="M", color="rose", order=2, requires_cat=True),
        ],
    )

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def reset_rate_limit_cache() -> None:
    auth._rate_limit_cache.clear()

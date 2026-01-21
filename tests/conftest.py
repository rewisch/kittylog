from __future__ import annotations

import os
import re
import socket
import sys
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
import uvicorn
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


class UvicornTestServer:
    """Manages uvicorn server lifecycle for E2E testing."""

    def __init__(self, app, host="127.0.0.1", port=None):
        self.app = app
        self.host = host
        self.port = port or self._find_free_port()
        self.server = None
        self.thread = None

    def _find_free_port(self):
        with socket.socket() as s:
            s.bind(("", 0))
            return s.getsockname()[1]

    def start(self):
        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="error",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        self._wait_for_ready()

    def _wait_for_ready(self, timeout=5.0):
        url = f"http://{self.host}:{self.port}/health"
        start = time.time()
        while time.time() - start < timeout:
            try:
                response = httpx.get(url, timeout=1.0)
                if response.status_code == 200:
                    return
            except:
                pass
            time.sleep(0.1)
        raise RuntimeError("Server failed to start")

    def stop(self):
        if self.server:
            self.server.should_exit = True
            if self.thread:
                self.thread.join(timeout=5.0)

    @property
    def url(self):
        return f"http://{self.host}:{self.port}"


@pytest.fixture()
def uvicorn_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, users_file: Path) -> str:
    """Start a real uvicorn server for E2E tests."""
    # Create isolated database
    db_path = tmp_path / f"test_{uuid.uuid4().hex[:8]}.db"

    # Monkeypatch settings BEFORE importing app
    def fake_load_settings(path=None):
        return AppSettings(
            default_language="en",
            db_path=db_path,
        )

    monkeypatch.setattr("app.main.load_settings", fake_load_settings)
    monkeypatch.setattr("app.main.run_startup_migrations", lambda repo_root: None)
    monkeypatch.setattr(
        "app.main.load_task_configs",
        lambda path: [
            TaskConfig(slug="feed", name="Feed the cat", icon="🍽️", color="blue", order=1, requires_cat=False),
            TaskConfig(slug="water", name="Fresh water", icon="💧", color="cyan", order=2, requires_cat=False),
        ],
    )

    # Import app AFTER monkeypatching
    from app.main import app

    # Start server
    server = UvicornTestServer(app)
    server.start()

    yield server.url

    server.stop()


def extract_csrf_token_from_page(page) -> str:
    """Extract CSRF token from Playwright page."""
    token = page.locator('input[name="csrf_token"]').get_attribute("value")
    assert token, "CSRF token not found on page"
    return token


def playwright_login(page, username: str, password: str, server_url: str):
    """Login helper for Playwright tests."""
    page.goto(f"{server_url}/login")
    page.fill('input[name="username"]', username)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_url(f"{server_url}/")


@pytest.fixture()
def authenticated_page(page, uvicorn_server: str, users_file: Path):
    """Provide a Playwright page with authenticated session."""
    # Create test user
    write_users_file(users_file, {"Livia": "secret"})

    # Login
    playwright_login(page, "Livia", "secret", uvicorn_server)

    yield page

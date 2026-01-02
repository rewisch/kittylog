from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import Response
from sqlmodel import Session

from .config_loader import load_task_configs, sync_task_types
from .database import configure_engine, create_db_and_tables, get_engine
from .routes import router
from .settings import load_settings


app = FastAPI(title="KittyLog")
ENV_PATH = Path(__file__).resolve().parent.parent / "config" / "kittylog.env"


def _load_env_file(path: Path) -> dict[str, str]:
    """Parse a simple KEY=VALUE env file."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, _, value = stripped.partition("=")
            values[key.strip()] = value.strip()
    return values


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    """Persist env values to disk with restrictive permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in sorted(values.items())]
    content = "\n".join(lines) + "\n"
    path.write_text(content, encoding="utf-8")
    try:
        path.chmod(0o600)
    except PermissionError:
        # Best-effort; continue if unable to change permissions.
        pass


def _ensure_secret_key() -> str:
    """Return a stable secret key, generating and persisting if missing."""
    env_values: dict[str, str] = {}
    secret = os.getenv("KITTYLOG_SECRET_KEY")
    if not secret:
        env_values = _load_env_file(ENV_PATH)
        secret = env_values.get("KITTYLOG_SECRET_KEY")
    if not secret:
        secret = secrets.token_hex(32)
        env_values["KITTYLOG_SECRET_KEY"] = secret
        env_values.setdefault("KITTYLOG_SESSION_SECURE", "true")
        _write_env_file(ENV_PATH, env_values)
        print(f"Generated KITTYLOG_SECRET_KEY and wrote {ENV_PATH}")
    for key, value in env_values.items():
        os.environ.setdefault(key, value)
    return secret


secret_key = _ensure_secret_key()
cookie_secure = os.getenv("KITTYLOG_SESSION_SECURE", "false").lower() == "true"
app.add_middleware(
    SessionMiddleware,
    secret_key=secret_key,
    session_cookie="kittylog_session",
    max_age=7 * 24 * 3600,
    same_site="lax",
    https_only=cookie_secure,
)
app.include_router(router)

app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    csp = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "script-src 'self' https://cdn.tailwindcss.com; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'none'"
    )
    response.headers.setdefault("Content-Security-Policy", csp)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
    return response


@app.on_event("startup")
def on_startup() -> None:
    settings_path = Path(__file__).resolve().parent.parent / "config" / "settings.yml"
    settings = load_settings(settings_path)
    configure_engine(settings.db_path)
    create_db_and_tables()
    config_path = Path(__file__).resolve().parent.parent / "config" / "tasks.yml"
    configs = load_task_configs(config_path)
    with Session(get_engine()) as session:
        sync_task_types(session, configs)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", reload=True)

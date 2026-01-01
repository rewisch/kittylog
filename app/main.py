from __future__ import annotations

import os
import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from sqlmodel import Session

from .config_loader import load_task_configs, sync_task_types
from .database import create_db_and_tables, engine
from .routes import router


app = FastAPI(title="KittyLog")
secret_key = os.getenv("KITTYLOG_SECRET_KEY") or secrets.token_hex(32)
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


@app.on_event("startup")
def on_startup() -> None:
    create_db_and_tables()
    config_path = Path(__file__).resolve().parent.parent / "config" / "tasks.yml"
    configs = load_task_configs(config_path)
    with Session(engine) as session:
        sync_task_types(session, configs)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", reload=True)

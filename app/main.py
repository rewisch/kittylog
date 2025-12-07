from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .config_loader import load_task_configs, sync_task_types
from .database import create_db_and_tables, engine
from .routes import router


app = FastAPI(title="KittyLog")
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

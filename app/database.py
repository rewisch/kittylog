from collections.abc import Generator
from pathlib import Path
from typing import Optional

from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from .settings import DEFAULT_DB_PATH


engine: Optional[Engine] = None


def configure_engine(db_path: Path | str | None = None) -> Engine:
    """Configure the global engine, defaulting to the configured DB path."""
    global engine
    target_path = Path(db_path) if db_path is not None else DEFAULT_DB_PATH
    engine = create_engine(
        f"sqlite:///{target_path}",
        connect_args={"check_same_thread": False},
    )
    return engine


def get_engine() -> Engine:
    """Return an initialized engine, configuring defaults if needed."""
    global engine
    if engine is None:
        configure_engine()
    assert engine is not None
    return engine


def create_db_and_tables() -> None:
    """Ensure database tables exist."""
    target_engine = get_engine()
    SQLModel.metadata.create_all(target_engine)
    _ensure_sort_order_column(target_engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency providing a SQLModel session."""
    target_engine = get_engine()
    with Session(target_engine) as session:
        yield session


def _ensure_sort_order_column(target_engine: Engine) -> None:
    """Add missing sort_order column for TaskType when upgrading existing DBs."""
    inspector = inspect(target_engine)
    existing_columns = [col["name"] for col in inspector.get_columns("tasktype")]
    if "sort_order" in existing_columns:
        return
    with target_engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE tasktype ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
        )

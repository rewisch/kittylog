from collections.abc import Generator
from pathlib import Path

from sqlalchemy import inspect
from sqlmodel import Session, SQLModel, create_engine


DB_PATH = Path(__file__).resolve().parent.parent / "kittylog.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    """Ensure database tables exist."""
    SQLModel.metadata.create_all(engine)
    _ensure_sort_order_column()


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency providing a SQLModel session."""
    with Session(engine) as session:
        yield session


def _ensure_sort_order_column() -> None:
    """Add missing sort_order column for TaskType when upgrading existing DBs."""
    inspector = inspect(engine)
    existing_columns = [col["name"] for col in inspector.get_columns("tasktype")]
    if "sort_order" in existing_columns:
        return
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "ALTER TABLE tasktype ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
        )

from collections.abc import Generator
from pathlib import Path

from sqlmodel import Session, SQLModel, create_engine


DB_PATH = Path(__file__).resolve().parent.parent / "kittylog.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    """Ensure database tables exist."""
    SQLModel.metadata.create_all(engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency providing a SQLModel session."""
    with Session(engine) as session:
        yield session

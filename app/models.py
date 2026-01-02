from datetime import datetime

from sqlmodel import Field, Relationship, SQLModel


class TaskEvent(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    task_type_id: int = Field(foreign_key="tasktype.id", index=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    who: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=50)
    note: str | None = Field(default=None, max_length=500)

    task_type: "TaskType" = Relationship(back_populates="events")


class TaskType(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=100)
    name: str
    icon: str
    color: str = Field(default="blue")
    sort_order: int = Field(default=0, index=True)
    is_active: bool = Field(default=True, index=True)

    events: list[TaskEvent] = Relationship(back_populates="task_type")

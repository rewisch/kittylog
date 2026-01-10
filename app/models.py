from datetime import date, datetime
from typing import List, Optional

from sqlmodel import Field, Relationship, SQLModel


class TaskType(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True, unique=True, max_length=100)
    name: str
    icon: str
    color: str = Field(default="blue")
    sort_order: int = Field(default=0, index=True)
    is_active: bool = Field(default=True, index=True)
    requires_cat: bool = Field(default=False, index=True)

    events: List["TaskEvent"] = Relationship(back_populates="task_type")


class Cat(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, max_length=100)
    color: Optional[str] = Field(default=None, max_length=50)
    birthday: Optional[date] = Field(default=None)
    chip_id: Optional[str] = Field(default=None, max_length=100)
    photo_path: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = Field(default=True, index=True)

    events: List["TaskEvent"] = Relationship(back_populates="cat")


class TaskEvent(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_type_id: int = Field(foreign_key="tasktype.id", index=True)
    cat_id: Optional[int] = Field(default=None, foreign_key="cat.id", index=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    who: Optional[str] = Field(default=None, max_length=100)
    source: Optional[str] = Field(default=None, max_length=50)
    note: Optional[str] = Field(default=None, max_length=500)
    deleted: bool = Field(default=False, index=True)

    task_type: "TaskType" = Relationship(back_populates="events")
    cat: Optional["Cat"] = Relationship(back_populates="events")


class PushSubscription(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user: str = Field(index=True, max_length=100)
    endpoint: str = Field(unique=True, max_length=500)
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=200)
    user_agent: Optional[str] = Field(default=None, max_length=300)
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    last_seen_at: datetime = Field(default_factory=datetime.utcnow, index=True)
    is_active: bool = Field(default=True, index=True)


class NotificationLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    subscription_id: int = Field(foreign_key="pushsubscription.id", index=True)
    rule_id: str = Field(index=True, max_length=100)
    group_id: Optional[str] = Field(default=None, index=True, max_length=100)
    day_key: str = Field(index=True, max_length=10)
    sent_at: datetime = Field(default_factory=datetime.utcnow, index=True)

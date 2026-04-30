from datetime import datetime
from enum import Enum
from sqlmodel import SQLModel, Field


class ReservationStatus(str, Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Resource(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    capacity: int = 1
    is_active: bool = True


class Reservation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    resource_id: int = Field(foreign_key="resource.id")
    user_email: str
    starts_at: datetime
    ends_at: datetime
    status: ReservationStatus = ReservationStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    cancelled_reason: str | None = None

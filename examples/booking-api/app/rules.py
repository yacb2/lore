from datetime import datetime, timedelta

from .models import Reservation, ReservationStatus

CANCELLATION_WINDOW = timedelta(hours=2)
PENDING_TTL = timedelta(minutes=15)


def can_user_cancel(reservation: Reservation, now: datetime) -> bool:
    if reservation.status != ReservationStatus.CONFIRMED:
        return False
    return reservation.starts_at - now >= CANCELLATION_WINDOW


def is_pending_expired(reservation: Reservation, now: datetime) -> bool:
    if reservation.status != ReservationStatus.PENDING:
        return False
    return now - reservation.created_at >= PENDING_TTL


def overlaps(a: Reservation, b: Reservation) -> bool:
    return a.starts_at < b.ends_at and b.starts_at < a.ends_at

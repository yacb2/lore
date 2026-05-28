from datetime import datetime

from sqlmodel import Session

from .models import Reservation, ReservationStatus
from .rules import can_user_cancel


class CancellationNotAllowed(Exception):
    pass


def confirm_reservation(session: Session, reservation_id: int) -> Reservation:
    r = session.get(Reservation, reservation_id)
    if r and r.status == ReservationStatus.PENDING:
        r.status = ReservationStatus.CONFIRMED
        session.add(r)
        session.commit()
        session.refresh(r)
    return r


def cancel_by_user(session: Session, reservation_id: int, now: datetime) -> Reservation:
    r = session.get(Reservation, reservation_id)
    if not can_user_cancel(r, now):
        raise CancellationNotAllowed(
            "Cancellation window closed or reservation not confirmed."
        )
    r.status = ReservationStatus.CANCELLED
    r.cancelled_reason = "user_request"
    session.add(r)
    session.commit()
    session.refresh(r)
    return r


def force_cancel_by_admin(
    session: Session, reservation_id: int, reason: str
) -> Reservation:
    r = session.get(Reservation, reservation_id)
    r.status = ReservationStatus.CANCELLED
    r.cancelled_reason = "admin:" + reason
    session.add(r)
    session.commit()
    session.refresh(r)
    return r

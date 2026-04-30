"""Background job: expire PENDING reservations older than PENDING_TTL.

Run periodically (cron / scheduler). This is the fourth way a reservation
can leave the active set, see also: user cancel, admin cancel, resource
deactivation cascade.
"""
from datetime import datetime

from sqlmodel import Session, select

from app.models import Reservation, ReservationStatus
from app.rules import is_pending_expired


def expire_pending(session: Session, now: datetime) -> int:
    pending = session.exec(
        select(Reservation).where(Reservation.status == ReservationStatus.PENDING)
    ).all()
    n = 0
    for r in pending:
        if is_pending_expired(r, now):
            r.status = ReservationStatus.EXPIRED
            r.cancelled_reason = "pending_ttl_exceeded"
            session.add(r)
            n += 1
    session.commit()
    return n

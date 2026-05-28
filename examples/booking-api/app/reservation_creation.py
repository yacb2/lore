from sqlmodel import Session, select

from .models import Reservation, ReservationStatus
from .rules import overlaps


class ReservationConflict(Exception):
    pass


def create_reservation(session: Session, payload: Reservation) -> Reservation:
    existing = session.exec(
        select(Reservation).where(
            Reservation.resource_id == payload.resource_id,
            Reservation.status.in_(
                [ReservationStatus.PENDING, ReservationStatus.CONFIRMED]
            ),
        )
    ).all()
    if any(overlaps(payload, r) for r in existing):
        raise ReservationConflict("Resource already booked for that window.")
    session.add(payload)
    session.commit()
    session.refresh(payload)
    return payload

from datetime import datetime

from sqlmodel import Session, select

from .models import Reservation, ReservationStatus, Resource
from .rules import can_user_cancel, overlaps


class ReservationConflict(Exception):
    pass


class CancellationNotAllowed(Exception):
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


def deactivate_resource(session: Session, resource_id: int) -> None:
    resource = session.get(Resource, resource_id)
    resource.is_active = False
    affected = session.exec(
        select(Reservation).where(
            Reservation.resource_id == resource_id,
            Reservation.status.in_(
                [ReservationStatus.PENDING, ReservationStatus.CONFIRMED]
            ),
        )
    ).all()
    for r in affected:
        r.status = ReservationStatus.CANCELLED
        r.cancelled_reason = "resource_deactivated"
        session.add(r)
    session.add(resource)
    session.commit()

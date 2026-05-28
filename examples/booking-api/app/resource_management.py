from sqlmodel import Session, select

from .models import Reservation, ReservationStatus, Resource


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

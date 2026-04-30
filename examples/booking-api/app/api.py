from datetime import datetime

from fastapi import FastAPI, HTTPException
from sqlmodel import Session

from .models import Reservation
from .services import (
    CancellationNotAllowed,
    ReservationConflict,
    cancel_by_user,
    confirm_reservation,
    create_reservation,
    deactivate_resource,
    force_cancel_by_admin,
)

app = FastAPI(title="booking-api")


def get_session() -> Session: ...  # wired in main.py


@app.post("/reservations")
def post_reservation(payload: Reservation):
    try:
        return create_reservation(get_session(), payload)
    except ReservationConflict as e:
        raise HTTPException(409, str(e))


@app.post("/reservations/{rid}/confirm")
def post_confirm(rid: int):
    return confirm_reservation(get_session(), rid)


@app.post("/reservations/{rid}/cancel")
def post_cancel(rid: int):
    try:
        return cancel_by_user(get_session(), rid, datetime.utcnow())
    except CancellationNotAllowed as e:
        raise HTTPException(403, str(e))


@app.post("/admin/reservations/{rid}/cancel")
def post_admin_cancel(rid: int, reason: str):
    return force_cancel_by_admin(get_session(), rid, reason)


@app.post("/admin/resources/{resource_id}/deactivate")
def post_deactivate_resource(resource_id: int):
    deactivate_resource(get_session(), resource_id)
    return {"ok": True}

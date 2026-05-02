# booking-api — DomainTome demo project

A tiny FastAPI booking system used to demo DomainTome in ~60 seconds.

It is intentionally small but spreads its business logic across endpoints,
services, rules, and a background job — so the question *"how many ways can
a reservation be cancelled?"* requires real exploration without DomainTome.

## The four cancellation paths (the punchline)

1. `POST /reservations/{id}/cancel` — user-initiated, gated by `can_user_cancel`
2. `POST /admin/reservations/{id}/cancel` — admin force-cancel with reason
3. `POST /admin/resources/{id}/deactivate` — cascades to active reservations
4. `scripts/expire_pending.py` — background job, expires stale PENDING

Without DomainTome, an assistant has to grep, read 4+ files, and reconstruct
this list. With DomainTome, it is a single `dt_query` returning typed nodes
with `source_ref` provenance.

## Layout

```
app/
  models.py      Reservation, Resource, ReservationStatus
  rules.py       can_user_cancel, is_pending_expired, overlaps
  services.py    create / confirm / cancel_by_user / force_cancel_by_admin / deactivate_resource
  api.py         FastAPI endpoints
scripts/
  expire_pending.py  background expiration job
```

## Reproduce the A/B yourself

Measured input-payload size for the question *"how many ways can a Reservation be cancelled?"*:

```bash
# Without DomainTome: bytes the assistant must read
wc -c app/api.py app/services.py app/rules.py app/models.py scripts/expire_pending.py
# => 6,213 bytes

# With DomainTome: bytes returned by a single query
dt init                                  # creates .dt/graph.db
sqlite3 .dt/graph.db < scripts/seed_graph.sql
dt query cancel | wc -c
# => 1,485 bytes
```

`scripts/seed_graph.sql` is the source of truth for the demo graph (12 nodes, 15 edges covering 4 cancellation paths, 3 rules, 2 entities). `.dt/` is gitignored so the DB is rebuilt locally.

## Generate the demo GIF

```bash
brew install vhs
vhs demo.tape   # writes demo.gif (~750 KB)
```


-- Seed DomainTome graph for booking-api demo.
-- Captures the four cancellation paths plus the entities and rules they touch.

BEGIN;

-- Entities
INSERT INTO nodes (id, type, title, body, status, metadata_json, created_at, updated_at) VALUES
('entity-reservation', 'entity', 'Reservation',
 'Booking made by a user against a Resource. Status lifecycle: PENDING -> CONFIRMED -> CANCELLED|EXPIRED.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/models.py:18'),
 datetime('now'), datetime('now')),
('entity-resource', 'entity', 'Resource',
 'Bookable resource (room, equipment). is_active flag gates new bookings.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/models.py:11'),
 datetime('now'), datetime('now'));

-- Capability + flow variants
INSERT INTO nodes (id, type, title, body, status, metadata_json, created_at, updated_at) VALUES
('cap-cancel-reservation', 'capability', 'Cancel a Reservation',
 'Move a Reservation out of the active set (CONFIRMED or PENDING) into CANCELLED or EXPIRED. Four implementations exist.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/services.py'),
 datetime('now'), datetime('now')),

('flow-user-cancel', 'flow', 'User cancels own reservation',
 'POST /reservations/{id}/cancel. Gated by can_user_cancel: must be CONFIRMED and at least 2h before starts_at. Sets cancelled_reason=user_request.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/services.py:42'),
 datetime('now'), datetime('now')),

('flow-admin-force-cancel', 'flow', 'Admin force-cancels a reservation',
 'POST /admin/reservations/{id}/cancel?reason=... Bypasses the cancellation window. Sets cancelled_reason=admin:<reason>.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/services.py:55'),
 datetime('now'), datetime('now')),

('flow-resource-deactivation-cascade', 'flow', 'Resource deactivation cascades to active reservations',
 'POST /admin/resources/{id}/deactivate sets is_active=false and cancels every PENDING/CONFIRMED reservation for that resource. Sets cancelled_reason=resource_deactivated.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/services.py:64'),
 datetime('now'), datetime('now')),

('flow-pending-ttl-expire', 'flow', 'Background job expires stale PENDING reservations',
 'scripts/expire_pending.py. Runs periodically (cron). Any PENDING reservation older than PENDING_TTL (15 min) is moved to EXPIRED with cancelled_reason=pending_ttl_exceeded.',
 'active',
 json_object('source','manual','confidence','high','source_ref','scripts/expire_pending.py:13'),
 datetime('now'), datetime('now'));

-- Rules
INSERT INTO nodes (id, type, title, body, status, metadata_json, created_at, updated_at) VALUES
('rule-cancellation-window', 'rule', 'User cancellation requires >=2h before start',
 'can_user_cancel returns False if (starts_at - now) < CANCELLATION_WINDOW (2 hours) or status != CONFIRMED.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/rules.py:10'),
 datetime('now'), datetime('now')),

('rule-pending-ttl', 'rule', 'PENDING reservations expire after 15 minutes',
 'is_pending_expired returns True if (now - created_at) >= PENDING_TTL.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/rules.py:17'),
 datetime('now'), datetime('now')),

('rule-no-overlap', 'rule', 'Resource cannot be double-booked',
 'create_reservation rejects (409) if any existing PENDING/CONFIRMED reservation for the same resource overlaps with the requested window.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/services.py:18'),
 datetime('now'), datetime('now'));

-- Modules
INSERT INTO nodes (id, type, title, body, status, metadata_json, created_at, updated_at) VALUES
('module-services', 'module', 'app/services.py',
 'Business-logic layer. All state transitions for Reservation and Resource go through here.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/services.py'),
 datetime('now'), datetime('now')),
('module-api', 'module', 'app/api.py',
 'FastAPI endpoints. Thin layer over services.',
 'active',
 json_object('source','manual','confidence','high','source_ref','app/api.py'),
 datetime('now'), datetime('now'));

-- Edges
INSERT INTO edges (from_id, to_id, relation, metadata_json, created_at) VALUES
('flow-user-cancel',                   'cap-cancel-reservation', 'implements', NULL, datetime('now')),
('flow-admin-force-cancel',            'cap-cancel-reservation', 'implements', NULL, datetime('now')),
('flow-resource-deactivation-cascade', 'cap-cancel-reservation', 'implements', NULL, datetime('now')),
('flow-pending-ttl-expire',            'cap-cancel-reservation', 'implements', NULL, datetime('now')),

('flow-user-cancel',                   'rule-cancellation-window',  'enforces',  NULL, datetime('now')),
('flow-pending-ttl-expire',            'rule-pending-ttl',          'enforces',  NULL, datetime('now')),

('flow-user-cancel',                   'entity-reservation', 'mutates', NULL, datetime('now')),
('flow-admin-force-cancel',            'entity-reservation', 'mutates', NULL, datetime('now')),
('flow-resource-deactivation-cascade', 'entity-reservation', 'mutates', NULL, datetime('now')),
('flow-resource-deactivation-cascade', 'entity-resource',    'mutates', NULL, datetime('now')),
('flow-pending-ttl-expire',            'entity-reservation', 'mutates', NULL, datetime('now')),

('module-services', 'flow-user-cancel',                   'contains', NULL, datetime('now')),
('module-services', 'flow-admin-force-cancel',            'contains', NULL, datetime('now')),
('module-services', 'flow-resource-deactivation-cascade', 'contains', NULL, datetime('now')),
('module-services', 'rule-no-overlap',                    'contains', NULL, datetime('now'));

COMMIT;

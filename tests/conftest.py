"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from domaintome.graph import add_edge, add_node, open_db


@pytest.fixture()
def conn():
    """In-memory SQLite database with DomainTome schema applied."""
    c = open_db(":memory:")
    yield c
    c.close()


@pytest.fixture()
def seeded_conn(conn):
    """A small seeded graph covering the PRD payments example."""
    add_node(conn, node_id="payments", type="module", title="Payments")
    add_node(
        conn,
        node_id="payment-registration",
        type="capability",
        title="Register a payment",
    )
    add_node(
        conn,
        node_id="payment-by-transfer",
        type="flow",
        title="Register payment by transfer",
    )
    add_node(
        conn,
        node_id="payment-by-tpv",
        type="flow",
        title="Register payment by TPV",
    )
    add_node(conn, node_id="payment-recorded", type="event", title="payment.recorded")
    add_node(
        conn,
        node_id="payment-must-match-open-invoice",
        type="rule",
        title="Payment must match an open invoice",
    )
    add_node(conn, node_id="invoice", type="entity", title="Invoice")
    add_node(
        conn,
        node_id="payment-create-form",
        type="form",
        title="PaymentCreateForm",
    )

    add_edge(conn, from_id="payment-registration", to_id="payments", relation="part_of")
    add_edge(conn, from_id="payment-by-transfer", to_id="payments", relation="part_of")
    add_edge(conn, from_id="payment-by-tpv", to_id="payments", relation="part_of")
    add_edge(
        conn,
        from_id="payment-by-transfer",
        to_id="payment-registration",
        relation="implements",
    )
    add_edge(
        conn,
        from_id="payment-by-tpv",
        to_id="payment-registration",
        relation="implements",
    )
    add_edge(
        conn,
        from_id="payment-by-transfer",
        to_id="payment-recorded",
        relation="triggers",
    )
    add_edge(
        conn,
        from_id="payment-create-form",
        to_id="payment-must-match-open-invoice",
        relation="validates",
    )
    add_edge(
        conn,
        from_id="payment-must-match-open-invoice",
        to_id="invoice",
        relation="enforces",
    )
    return conn

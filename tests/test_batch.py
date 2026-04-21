"""Tests for batch node/edge creation."""

from __future__ import annotations

import pytest

from lore.graph import add_edges_batch, add_nodes_batch
from lore.graph.schema import SchemaError


def test_add_nodes_batch_inserts_all(conn):
    nodes = add_nodes_batch(
        conn,
        [
            {"id": "module-a", "type": "module", "title": "A"},
            {"id": "module-b", "type": "module", "title": "B",
             "metadata": {"source": "inferred_from_code"}},
        ],
    )
    assert [n["id"] for n in nodes] == ["module-a", "module-b"]
    assert nodes[1]["metadata"] == {"source": "inferred_from_code"}


def test_add_nodes_batch_fails_atomically(conn):
    with pytest.raises(SchemaError):
        add_nodes_batch(
            conn,
            [
                {"id": "module-ok", "type": "module", "title": "OK"},
                {"id": "BAD--ID", "type": "module", "title": "nope"},
            ],
        )
    # First node must NOT have been inserted
    rows = conn.execute("SELECT COUNT(*) AS n FROM nodes").fetchone()
    assert rows["n"] == 0


def test_add_edges_batch(conn):
    add_nodes_batch(
        conn,
        [
            {"id": "module-a", "type": "module", "title": "A"},
            {"id": "module-b", "type": "module", "title": "B"},
            {"id": "module-c", "type": "module", "title": "C"},
        ],
    )
    edges = add_edges_batch(
        conn,
        [
            {"from_id": "module-a", "to_id": "module-b", "relation": "depends_on"},
            {"from_id": "module-b", "to_id": "module-c", "relation": "depends_on"},
        ],
    )
    assert len(edges) == 2
    rows = conn.execute("SELECT COUNT(*) AS n FROM edges").fetchone()
    assert rows["n"] == 2


def test_add_edges_batch_rejects_invalid_relation(conn):
    add_nodes_batch(
        conn,
        [
            {"id": "cap-a", "type": "capability", "title": "A"},
            {"id": "cap-b", "type": "capability", "title": "B"},
        ],
    )
    with pytest.raises(SchemaError):
        add_edges_batch(
            conn,
            [{"from_id": "cap-a", "to_id": "cap-b", "relation": "depends_on"}],
        )

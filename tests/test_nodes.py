"""Node CRUD tests."""

from __future__ import annotations

import sqlite3

import pytest

from domaintome.graph import add_node, delete_node, get_node, update_node
from domaintome.graph.schema import SchemaError


def test_add_and_get_node(conn):
    node = add_node(
        conn,
        node_id="payments",
        type="module",
        title="Payments",
        body="The payments module.",
        metadata={"tags": ["billing"]},
    )
    assert node["id"] == "payments"
    assert node["type"] == "module"
    assert node["status"] == "active"
    assert node["metadata"] == {"tags": ["billing"]}

    fetched = get_node(conn, "payments")
    # add_node() augments the persisted node with a soft-validation
    # `warnings` list; get_node() returns the raw row.
    assert fetched is not None
    assert {k: v for k, v in node.items() if k != "warnings"} == fetched


def test_add_duplicate_raises(conn):
    add_node(conn, node_id="payments", type="module", title="Payments")
    with pytest.raises(sqlite3.IntegrityError):
        add_node(conn, node_id="payments", type="module", title="Dup")


def test_add_rejects_invalid_id(conn):
    with pytest.raises(SchemaError):
        add_node(conn, node_id="Payments", type="module", title="Bad")


def test_add_rejects_invalid_type(conn):
    with pytest.raises(SchemaError):
        add_node(conn, node_id="x", type="service", title="x")


def test_add_rejects_empty_title(conn):
    with pytest.raises(SchemaError):
        add_node(conn, node_id="x", type="module", title="  ")


def test_update_node_fields(conn):
    add_node(conn, node_id="x", type="flow", title="Old")
    before = get_node(conn, "x")
    updated = update_node(conn, "x", title="New", status="deprecated")
    assert updated["title"] == "New"
    assert updated["status"] == "deprecated"
    assert updated["updated_at"] >= before["updated_at"]


def test_update_node_missing(conn):
    with pytest.raises(SchemaError):
        update_node(conn, "ghost", title="x")


def test_update_metadata_replaces(conn):
    add_node(conn, node_id="x", type="flow", title="X", metadata={"tags": ["a"]})
    updated = update_node(conn, "x", metadata={"tags": ["b"], "owner": "ayoel"})
    assert updated["metadata"] == {"tags": ["b"], "owner": "ayoel"}


def test_metadata_patch_merges_and_preserves(conn):
    add_node(
        conn,
        node_id="x",
        type="flow",
        title="X",
        metadata={"source": "user_stated", "confidence": "high", "tags": ["a"]},
    )
    updated = update_node(
        conn, "x", metadata_patch={"confidence": "medium", "owner": "ayoel"}
    )
    assert updated["metadata"] == {
        "source": "user_stated",
        "confidence": "medium",
        "tags": ["a"],
        "owner": "ayoel",
    }


def test_metadata_patch_removes_key_when_value_is_none(conn):
    add_node(conn, node_id="x", type="flow", title="X",
             metadata={"source": "user_stated", "note": "drop me"})
    updated = update_node(conn, "x", metadata_patch={"note": None})
    assert updated["metadata"] == {"source": "user_stated"}


def test_metadata_and_patch_are_mutually_exclusive(conn):
    add_node(conn, node_id="x", type="flow", title="X")
    with pytest.raises(SchemaError):
        update_node(conn, "x", metadata={"a": 1}, metadata_patch={"b": 2})


def test_new_statuses_accepted(conn):
    add_node(conn, node_id="x", type="flow", title="X")
    for s in ("draft", "archived", "deprecated", "superseded", "active"):
        update_node(conn, "x", status=s)


def test_delete_node(conn):
    add_node(conn, node_id="x", type="flow", title="X")
    result = delete_node(conn, "x")
    assert result == {"deleted": True, "edges_lost": 0}
    assert get_node(conn, "x") is None
    assert delete_node(conn, "x") == {"deleted": False, "edges_lost": 0}


def test_delete_node_reports_lost_edges(conn):
    add_node(conn, node_id="a", type="module", title="A")
    add_node(conn, node_id="b", type="module", title="B")
    from domaintome.graph import add_edge
    add_edge(conn, from_id="a", to_id="b", relation="depends_on")
    assert delete_node(conn, "a") == {"deleted": True, "edges_lost": 1}


def test_get_missing_returns_none(conn):
    assert get_node(conn, "ghost") is None

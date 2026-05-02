"""Edge CRUD tests."""

from __future__ import annotations

import sqlite3

import pytest

from domaintome.graph import add_edge, add_node, delete_node, list_edges, remove_edge
from domaintome.graph.schema import SchemaError


def test_add_edge_valid(conn):
    add_node(conn, node_id="f", type="flow", title="F")
    add_node(conn, node_id="c", type="capability", title="C")
    edge = add_edge(conn, from_id="f", to_id="c", relation="implements")
    assert edge["from_id"] == "f"
    assert edge["to_id"] == "c"
    assert edge["relation"] == "implements"


def test_add_edge_invalid_types(conn):
    add_node(conn, node_id="f", type="flow", title="F")
    add_node(conn, node_id="r", type="rule", title="R")
    with pytest.raises(SchemaError):
        add_edge(conn, from_id="f", to_id="r", relation="implements")


def test_add_edge_missing_node(conn):
    add_node(conn, node_id="f", type="flow", title="F")
    with pytest.raises(SchemaError):
        add_edge(conn, from_id="f", to_id="ghost", relation="implements")


def test_duplicate_edge_raises(conn):
    add_node(conn, node_id="f", type="flow", title="F")
    add_node(conn, node_id="c", type="capability", title="C")
    add_edge(conn, from_id="f", to_id="c", relation="implements")
    with pytest.raises(sqlite3.IntegrityError):
        add_edge(conn, from_id="f", to_id="c", relation="implements")


def test_remove_edge(conn):
    add_node(conn, node_id="f", type="flow", title="F")
    add_node(conn, node_id="c", type="capability", title="C")
    add_edge(conn, from_id="f", to_id="c", relation="implements")
    assert remove_edge(conn, from_id="f", to_id="c", relation="implements") is True
    assert remove_edge(conn, from_id="f", to_id="c", relation="implements") is False


def test_delete_node_cascades_edges(conn):
    add_node(conn, node_id="f", type="flow", title="F")
    add_node(conn, node_id="c", type="capability", title="C")
    add_edge(conn, from_id="f", to_id="c", relation="implements")
    delete_node(conn, "f")
    assert list_edges(conn) == []


def test_list_edges_filter(conn):
    add_node(conn, node_id="f1", type="flow", title="F1")
    add_node(conn, node_id="f2", type="flow", title="F2")
    add_node(conn, node_id="c", type="capability", title="C")
    add_edge(conn, from_id="f1", to_id="c", relation="implements")
    add_edge(conn, from_id="f2", to_id="c", relation="implements")

    all_edges = list_edges(conn)
    assert len(all_edges) == 2

    one = list_edges(conn, from_id="f1")
    assert len(one) == 1
    assert one[0]["from_id"] == "f1"

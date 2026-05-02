"""Tests for the audit_log table and stats()."""

from __future__ import annotations

from domaintome.graph import history, log_call, stats


def test_log_call_appends_row(conn):
    log_call(conn, tool="dt_add_node", op="create", node_id="foo",
             input_bytes=120, output_bytes=340)
    log_call(conn, tool="dt_list", op="read", input_bytes=10, output_bytes=500)

    rows = conn.execute("SELECT tool, op, node_id, input_bytes, output_bytes "
                        "FROM audit_log ORDER BY id").fetchall()
    assert [dict(r) for r in rows] == [
        {"tool": "dt_add_node", "op": "create", "node_id": "foo",
         "input_bytes": 120, "output_bytes": 340},
        {"tool": "dt_list", "op": "read", "node_id": None,
         "input_bytes": 10, "output_bytes": 500},
    ]


def test_stats_empty(conn):
    data = stats(conn)
    assert data["calls"] == 0
    assert data["total_bytes"] == 0
    assert data["by_tool"] == []
    assert data["first_call_at"] is None


def test_stats_aggregates(conn):
    log_call(conn, tool="dt_add_node", op="create", input_bytes=100, output_bytes=200)
    log_call(conn, tool="dt_add_node", op="create", input_bytes=100, output_bytes=200)
    log_call(conn, tool="dt_list", op="read", input_bytes=10, output_bytes=1000)
    log_call(conn, tool="dt_list", op="read", input_bytes=10, output_bytes=1000,
             error="RuntimeError: boom")

    data = stats(conn)
    assert data["calls"] == 4
    assert data["errors"] == 1
    assert data["input_bytes"] == 220
    assert data["output_bytes"] == 2400

    tools = {r["tool"]: r for r in data["by_tool"]}
    assert tools["dt_add_node"]["calls"] == 2
    assert tools["dt_list"]["calls"] == 2

    ops = {r["op"]: r["calls"] for r in data["by_op"]}
    assert ops == {"create": 2, "read": 2}


def test_history_filters_by_node(conn):
    log_call(conn, tool="dt_add_node", op="create", node_id="foo",
             input_bytes=10, output_bytes=20)
    log_call(conn, tool="dt_update_node", op="update", node_id="foo",
             input_bytes=10, output_bytes=20)
    log_call(conn, tool="dt_add_node", op="create", node_id="bar",
             input_bytes=10, output_bytes=20)

    events = history(conn, "foo")
    assert len(events) == 2
    assert {e["tool"] for e in events} == {"dt_add_node", "dt_update_node"}
    assert history(conn, "missing") == []

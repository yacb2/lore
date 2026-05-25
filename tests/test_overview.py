"""Tests for `dt_overview` — the bootstrap context tool for LLM agents.

`dt_overview` must return a compact map of the graph so an agent landing
on a new project can orient itself in a single call instead of several
exploratory `dt_list`/`dt_traverse` round-trips.
"""

from __future__ import annotations

import json

import pytest

from domaintome.graph import add_edge, add_node, open_db, overview
from domaintome.mcp import build_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_overview_empty_graph_has_well_formed_shape():
    conn = open_db(":memory:")
    out = overview(conn)
    assert set(out) >= {
        "node_counts",
        "total_nodes",
        "top_capabilities",
        "recent_decisions",
        "recent_changes",
        "health_summary",
    }
    assert out["node_counts"] == {}
    assert out["total_nodes"] == 0
    assert out["top_capabilities"] == []
    assert out["recent_decisions"] == []
    assert out["recent_changes"] == []
    assert isinstance(out["health_summary"], str)


def test_overview_counts_and_top_capabilities(seeded_conn):
    out = overview(seeded_conn)
    counts = out["node_counts"]
    assert counts["module"] == 1
    assert counts["capability"] == 1
    assert counts["flow"] == 2
    assert out["total_nodes"] == sum(counts.values())

    # `payment-registration` is implemented by two flows in the fixture.
    titles = {c["id"]: c["variant_count"] for c in out["top_capabilities"]}
    assert titles.get("payment-registration") == 2


def test_overview_recent_decisions_newest_first():
    conn = open_db(":memory:")
    add_node(conn, node_id="d-old", type="decision", title="Old decision")
    add_node(conn, node_id="d-new", type="decision", title="New decision")
    # Force ordering: bump d-new updated_at by touching it.
    conn.execute(
        "UPDATE nodes SET updated_at = '2099-01-01T00:00:00+00:00' WHERE id = 'd-new'"
    )
    conn.commit()

    out = overview(conn)
    ids = [d["id"] for d in out["recent_decisions"]]
    assert ids[0] == "d-new"
    assert "d-old" in ids


def test_overview_payload_under_2kb_on_realistic_graph():
    """Even with ~50 nodes the overview must stay under ~2KB."""
    conn = open_db(":memory:")
    add_node(conn, node_id="mod-a", type="module", title="Module A")
    for i in range(40):
        add_node(
            conn,
            node_id=f"cap-{i:03d}",
            type="capability",
            title=f"Capability {i}",
        )
    for i in range(20):
        add_node(
            conn, node_id=f"flow-{i:03d}", type="flow", title=f"Flow {i}"
        )
        add_edge(
            conn,
            from_id=f"flow-{i:03d}",
            to_id="cap-000",
            relation="implements",
        )

    out = overview(conn)
    size = len(json.dumps(out, default=str).encode("utf-8"))
    assert size < 2048, f"overview payload too large: {size} bytes"
    # Top capability cap-000 has 20 variants.
    assert out["top_capabilities"][0]["id"] == "cap-000"
    assert out["top_capabilities"][0]["variant_count"] == 20


def test_overview_health_summary_flags_orphans():
    conn = open_db(":memory:")
    add_node(conn, node_id="lonely", type="module", title="Lonely")
    out = overview(conn)
    assert "orphan" in out["health_summary"].lower()


def test_overview_health_summary_ok_on_clean_graph(seeded_conn):
    out = overview(seeded_conn)
    # seeded_conn has all edges wired — no orphans expected.
    assert "orphan" not in out["health_summary"].lower()


@pytest.mark.anyio
async def test_dt_overview_mcp_tool_registered(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)
    tools = await server.list_tools()
    names = {t.name for t in tools}
    assert "dt_overview" in names


@pytest.mark.anyio
async def test_dt_overview_mcp_tool_end_to_end(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)

    async def call(name: str, args: dict):
        result = await server.call_tool(name, args)
        if isinstance(result, tuple):
            _, structured = result
        else:
            structured = None
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured

    await call(
        "dt_add_node",
        {"id": "m", "type": "module", "title": "M"},
    )
    out = await call("dt_overview", {})
    assert isinstance(out, dict)
    assert out["node_counts"] == {"module": 1}
    assert out["total_nodes"] == 1

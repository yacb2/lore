"""MCP server smoke tests.

We don't drive the stdio loop here — we just verify the server builds with the
expected tools registered.
"""

from __future__ import annotations

import pytest

from domaintome.mcp import build_server
from domaintome.mcp.server import run as mcp_run


def _patch_fastmcp_run(monkeypatch):
    """Stub FastMCP.run so we don't start the stdio loop in tests."""
    from mcp.server.fastmcp import FastMCP

    called = {}

    def fake(self):
        called["ran"] = True

    monkeypatch.setattr(FastMCP, "run", fake)
    return called


def test_mcp_run_auto_creates_missing_db(tmp_path, capsys, monkeypatch):
    """Missing DB + missing parent dir → create both and proceed.
    Zero-friction first-run for brand-new projects."""
    db = tmp_path / "nope" / ".dt" / "graph.db"
    assert not db.exists()
    called = _patch_fastmcp_run(monkeypatch)

    mcp_run(db)
    assert db.exists(), "DB must be auto-created regardless of parent dir state"
    assert called.get("ran") is True
    err = capsys.readouterr().err
    assert "creating new graph" in err
    assert "using database at" in err


def test_mcp_run_silent_banner_when_db_already_exists(
    tmp_path, capsys, monkeypatch
):
    """Existing DB → no 'creating new graph' banner, only the path log.
    The banner is reserved for first-time materialization so it remains
    a real signal."""
    db_dir = tmp_path / ".dt"
    db_dir.mkdir()
    db = db_dir / "graph.db"
    # Materialize the DB once.
    from domaintome.graph import open_db as _open
    _open(db).close()
    assert db.exists()

    _patch_fastmcp_run(monkeypatch)
    mcp_run(db)
    err = capsys.readouterr().err
    assert "creating new graph" not in err
    assert "using database at" in err


@pytest.mark.anyio
async def test_build_server_registers_tools(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)
    tools = await server.list_tools()
    names = {t.name for t in tools}
    expected = {
        "dt_add_node",
        "dt_update_node",
        "dt_delete_node",
        "dt_get_node",
        "dt_add_edge",
        "dt_remove_edge",
        "dt_query",
        "dt_traverse",
        "dt_find_variants",
        "dt_list",
        "dt_audit",
        "dt_export_markdown",
    }
    assert expected <= names


@pytest.mark.anyio
async def test_call_tools_end_to_end(tmp_path):
    """Drive a realistic sequence: add two nodes, add edge, query, find_variants."""
    import json

    db = tmp_path / "graph.db"
    server = build_server(db)

    async def call(name: str, args: dict) -> dict | list:
        result = await server.call_tool(name, args)
        # FastMCP returns (content_list, structured) — structured is the dict/list
        if isinstance(result, tuple):
            content, structured = result
        else:
            content, structured = result, None
        if structured is not None:
            # FastMCP wraps list/scalar returns as {"result": ...}
            if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
                return structured["result"]
            return structured
        # Fall back to parsing the first text block
        for block in content:
            text = getattr(block, "text", None)
            if text:
                return json.loads(text)
        raise AssertionError(f"No content from tool {name}")

    cap = await call(
        "dt_add_node",
        {"id": "pay-cap", "type": "capability", "title": "Pay capability"},
    )
    assert cap["id"] == "pay-cap"

    await call(
        "dt_add_node",
        {"id": "pay-flow", "type": "flow", "title": "Pay flow"},
    )
    await call(
        "dt_add_edge",
        {"from_id": "pay-flow", "to_id": "pay-cap", "relation": "implements"},
    )

    got = await call("dt_get_node", {"id": "pay-flow", "include_edges": True})
    assert got["node"]["id"] == "pay-flow"
    assert any(e["to_id"] == "pay-cap" for e in got["outgoing"])

    variants = await call("dt_find_variants", {"capability_id": "pay-cap"})
    assert any(v["id"] == "pay-flow" for v in variants)


@pytest.mark.anyio
async def test_schema_violation_surfaces_as_error(tmp_path):
    """Calling dt_add_edge with incompatible types should error, not silently
    succeed."""
    db = tmp_path / "graph.db"
    server = build_server(db)

    # Add two nodes whose types can't connect via `implements`
    await server.call_tool(
        "dt_add_node",
        {"id": "m", "type": "module", "title": "M"},
    )
    await server.call_tool(
        "dt_add_node",
        {"id": "r", "type": "rule", "title": "R"},
    )
    with pytest.raises(Exception) as exc_info:
        await server.call_tool(
            "dt_add_edge",
            {"from_id": "m", "to_id": "r", "relation": "implements"},
        )
    assert "not allowed" in str(exc_info.value).lower() or "schema" in str(
        exc_info.value
    ).lower()


@pytest.fixture
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------------------
# Truncation contract — dt_traverse, dt_list and dt_query must mark partial
# results with `_truncated: true` so the LLM consumer never reasons over
# silently-cropped data. See `.context/backlog/2026-05-14-dt-truncation-metadata.md`.
# ---------------------------------------------------------------------------


async def _call(server, name: str, args: dict):
    import json as _json

    result = await server.call_tool(name, args)
    if isinstance(result, tuple):
        content, structured = result
    else:
        content, structured = result, None
    if structured is not None:
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured
    for block in content:
        text = getattr(block, "text", None)
        if text:
            return _json.loads(text)
    raise AssertionError(f"No content from tool {name}")


@pytest.mark.anyio
async def test_dt_list_wraps_in_dict_and_marks_truncation(tmp_path, monkeypatch):
    """dt_list always returns a dict with `items`; when serialized output
    exceeds DT_MAX_RESPONSE_BYTES, it carries truncation metadata."""
    monkeypatch.setenv("DT_MAX_RESPONSE_BYTES", "1500")
    db = tmp_path / "graph.db"
    server = build_server(db)

    # Seed ~80 modules so the full list comfortably overshoots 1.5KB.
    for i in range(80):
        await _call(
            server,
            "dt_add_node",
            {"id": f"m-{i:03d}", "type": "module", "title": f"Module {i}"},
        )

    out = await _call(server, "dt_list", {"type": "module"})
    assert isinstance(out, dict), "dt_list must return a dict (wrapped)"
    assert "items" in out
    assert out.get("_truncated") is True
    assert out.get("_truncated_reason") == "max_bytes"
    assert out.get("_total_estimated") == 80
    assert "hint" in (out.get("_hint") or "").lower() or out.get("_hint")
    assert len(out["items"]) < 80


@pytest.mark.anyio
async def test_dt_list_no_truncation_when_small(tmp_path, monkeypatch):
    """When the response fits under the limit, dt_list returns
    {"items": [...]} with no `_truncated` field."""
    monkeypatch.setenv("DT_MAX_RESPONSE_BYTES", "30000")
    db = tmp_path / "graph.db"
    server = build_server(db)

    await _call(
        server,
        "dt_add_node",
        {"id": "only", "type": "module", "title": "Only"},
    )
    out = await _call(server, "dt_list", {})
    assert isinstance(out, dict)
    assert "items" in out
    assert out.get("_truncated") is None or out.get("_truncated") is False
    assert len(out["items"]) == 1


@pytest.mark.anyio
async def test_dt_traverse_marks_truncation(tmp_path, monkeypatch):
    """dt_traverse adds `_truncated` metadata when nodes+edges exceed the
    byte budget; otherwise behaves as before."""
    monkeypatch.setenv("DT_MAX_RESPONSE_BYTES", "1500")
    db = tmp_path / "graph.db"
    server = build_server(db)

    # Hub-and-spoke: one module with many flows linked via part_of.
    await _call(
        server,
        "dt_add_node",
        {"id": "hub", "type": "module", "title": "Hub"},
    )
    for i in range(60):
        await _call(
            server,
            "dt_add_node",
            {"id": f"f-{i:03d}", "type": "flow", "title": f"Flow {i}"},
        )
        await _call(
            server,
            "dt_add_edge",
            {"from_id": f"f-{i:03d}", "to_id": "hub", "relation": "part_of"},
        )

    out = await _call(
        server, "dt_traverse", {"from_id": "hub", "max_depth": 0}
    )
    # depth=0 → only the hub, no truncation expected.
    assert "_truncated" not in out or out.get("_truncated") is not True
    assert out["nodes"][0]["id"] == "hub"

    # Now reverse traversal via a deep walk: seed reverse edges so the
    # traversal actually fans out.
    for i in range(60):
        await _call(
            server,
            "dt_add_edge",
            {"from_id": "hub", "to_id": f"f-{i:03d}", "relation": "depends_on"},
        )

    out2 = await _call(
        server,
        "dt_traverse",
        {"from_id": "hub", "relations": ["depends_on"], "max_depth": 1},
    )
    assert out2.get("_truncated") is True
    assert out2.get("_truncated_reason") == "max_bytes"
    assert "hint" in (out2.get("_hint") or "").lower() or out2.get("_hint")
    # Truncated set must be self-consistent: every edge points to a kept node.
    kept = {n["id"] for n in out2["nodes"]}
    for e in out2["edges"]:
        assert e["from_id"] in kept and e["to_id"] in kept


@pytest.mark.anyio
async def test_dt_query_marks_truncation(tmp_path, monkeypatch):
    """dt_query carries `_truncated` metadata when its neighborhood
    exceeds DT_MAX_RESPONSE_BYTES."""
    monkeypatch.setenv("DT_MAX_RESPONSE_BYTES", "1500")
    db = tmp_path / "graph.db"
    server = build_server(db)

    await _call(
        server,
        "dt_add_node",
        {"id": "center", "type": "module", "title": "Center"},
    )
    for i in range(60):
        await _call(
            server,
            "dt_add_node",
            {"id": f"n-{i:03d}", "type": "flow", "title": f"Node {i}"},
        )
        await _call(
            server,
            "dt_add_edge",
            {"from_id": f"n-{i:03d}", "to_id": "center", "relation": "part_of"},
        )

    out = await _call(server, "dt_query", {"text_or_id": "center", "depth": 1})
    assert out.get("_truncated") is True
    assert out.get("_truncated_reason") == "max_bytes"
    kept = {n["id"] for n in out["nodes"]}
    for e in out["edges"]:
        assert e["from_id"] in kept and e["to_id"] in kept


# ---------------------------------------------------------------------------
# Unified batch mode on dt_add_node / dt_add_edge — step 2 of the
# surface-area consolidation. The plurals (dt_add_nodes, dt_add_edges) are
# kept as deprecated aliases for one release; the new shape lives on the
# singulars via optional `nodes` / `edges` params.
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_dt_add_node_batch_mode_via_nodes_arg(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)

    out = await _call(
        server,
        "dt_add_node",
        {
            "nodes": [
                {"id": "m-a", "type": "module", "title": "A"},
                {"id": "m-b", "type": "module", "title": "B"},
            ]
        },
    )
    assert isinstance(out, dict)
    assert "results" in out
    assert {r["id"] for r in out["results"]} == {"m-a", "m-b"}


@pytest.mark.anyio
async def test_dt_add_node_single_mode_unchanged(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)

    out = await _call(
        server,
        "dt_add_node",
        {"id": "m-solo", "type": "module", "title": "Solo"},
    )
    assert out["id"] == "m-solo"
    assert "results" not in out


@pytest.mark.anyio
async def test_dt_add_node_missing_args_returns_error(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)

    out = await _call(server, "dt_add_node", {})
    assert "error" in out


@pytest.mark.anyio
async def test_dt_add_edge_batch_mode_via_edges_arg(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)

    await _call(
        server,
        "dt_add_node",
        {
            "nodes": [
                {"id": "cap-x", "type": "capability", "title": "X"},
                {"id": "flow-1", "type": "flow", "title": "F1"},
                {"id": "flow-2", "type": "flow", "title": "F2"},
            ]
        },
    )
    out = await _call(
        server,
        "dt_add_edge",
        {
            "edges": [
                {"from_id": "flow-1", "to_id": "cap-x", "relation": "implements"},
                {"from_id": "flow-2", "to_id": "cap-x", "relation": "implements"},
            ]
        },
    )
    assert "results" in out
    assert len(out["results"]) == 2


@pytest.mark.anyio
async def test_dt_add_edges_alias_still_works_and_warns(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)

    await _call(
        server,
        "dt_add_node",
        {
            "nodes": [
                {"id": "cap-y", "type": "capability", "title": "Y"},
                {"id": "flow-y", "type": "flow", "title": "FY"},
            ]
        },
    )
    import warnings as _warnings

    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        out = await _call(
            server,
            "dt_add_edges",
            {
                "edges": [
                    {
                        "from_id": "flow-y",
                        "to_id": "cap-y",
                        "relation": "implements",
                    }
                ]
            },
        )
    assert isinstance(out, list)
    assert len(out) == 1
    assert any(
        issubclass(w.category, DeprecationWarning) and "dt_add_edges" in str(w.message)
        for w in caught
    )


@pytest.mark.anyio
async def test_dt_add_nodes_alias_still_works_and_warns(tmp_path):
    db = tmp_path / "graph.db"
    server = build_server(db)

    import warnings as _warnings

    with _warnings.catch_warnings(record=True) as caught:
        _warnings.simplefilter("always")
        out = await _call(
            server,
            "dt_add_nodes",
            {
                "nodes": [
                    {"id": "n-1", "type": "module", "title": "N1"},
                    {"id": "n-2", "type": "module", "title": "N2"},
                ]
            },
        )
    assert isinstance(out, list)
    assert {n["id"] for n in out} == {"n-1", "n-2"}
    assert any(
        issubclass(w.category, DeprecationWarning) and "dt_add_nodes" in str(w.message)
        for w in caught
    )

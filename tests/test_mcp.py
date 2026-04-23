"""MCP server smoke tests.

We don't drive the stdio loop here — we just verify the server builds with the
expected tools registered.
"""

from __future__ import annotations

import pytest

from lore.mcp import build_server
from lore.mcp.server import run as mcp_run


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
    db = tmp_path / "nope" / ".lore" / "lore.db"
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
    db_dir = tmp_path / ".lore"
    db_dir.mkdir()
    db = db_dir / "lore.db"
    # Materialize the DB once.
    from lore.graph import open_db as _open
    _open(db).close()
    assert db.exists()

    _patch_fastmcp_run(monkeypatch)
    mcp_run(db)
    err = capsys.readouterr().err
    assert "creating new graph" not in err
    assert "using database at" in err


@pytest.mark.anyio
async def test_build_server_registers_tools(tmp_path):
    db = tmp_path / "lore.db"
    server = build_server(db)
    tools = await server.list_tools()
    names = {t.name for t in tools}
    expected = {
        "lore_add_node",
        "lore_update_node",
        "lore_delete_node",
        "lore_get_node",
        "lore_add_edge",
        "lore_remove_edge",
        "lore_query",
        "lore_traverse",
        "lore_find_variants",
        "lore_list",
        "lore_audit",
        "lore_export_markdown",
    }
    assert expected <= names


@pytest.mark.anyio
async def test_call_tools_end_to_end(tmp_path):
    """Drive a realistic sequence: add two nodes, add edge, query, find_variants."""
    import json

    db = tmp_path / "lore.db"
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
        "lore_add_node",
        {"id": "pay-cap", "type": "capability", "title": "Pay capability"},
    )
    assert cap["id"] == "pay-cap"

    await call(
        "lore_add_node",
        {"id": "pay-flow", "type": "flow", "title": "Pay flow"},
    )
    await call(
        "lore_add_edge",
        {"from_id": "pay-flow", "to_id": "pay-cap", "relation": "implements"},
    )

    got = await call("lore_get_node", {"id": "pay-flow", "include_edges": True})
    assert got["node"]["id"] == "pay-flow"
    assert any(e["to_id"] == "pay-cap" for e in got["outgoing"])

    variants = await call("lore_find_variants", {"capability_id": "pay-cap"})
    assert any(v["id"] == "pay-flow" for v in variants)


@pytest.mark.anyio
async def test_schema_violation_surfaces_as_error(tmp_path):
    """Calling lore_add_edge with incompatible types should error, not silently
    succeed."""
    db = tmp_path / "lore.db"
    server = build_server(db)

    # Add two nodes whose types can't connect via `implements`
    await server.call_tool(
        "lore_add_node",
        {"id": "m", "type": "module", "title": "M"},
    )
    await server.call_tool(
        "lore_add_node",
        {"id": "r", "type": "rule", "title": "R"},
    )
    with pytest.raises(Exception) as exc_info:
        await server.call_tool(
            "lore_add_edge",
            {"from_id": "m", "to_id": "r", "relation": "implements"},
        )
    assert "not allowed" in str(exc_info.value).lower() or "schema" in str(
        exc_info.value
    ).lower()


@pytest.fixture
def anyio_backend():
    return "asyncio"

"""MCP server smoke tests.

We don't drive the stdio loop here — we just verify the server builds with the
expected tools registered.
"""

from __future__ import annotations

import pytest

from lore.mcp import build_server
from lore.mcp.server import run as mcp_run


def test_mcp_run_refuses_when_lore_dir_also_missing(tmp_path, capsys):
    """No DB and no `.lore/` parent → refuse. Guards the footgun of
    launching from a directory that was never meant to host Lore."""
    missing = tmp_path / "nope" / "lore.db"
    assert not missing.parent.exists()
    with pytest.raises(SystemExit) as exc:
        mcp_run(missing)
    assert exc.value.code == 1
    assert not missing.exists(), "run() must not create the DB"
    err = capsys.readouterr().err
    assert "no `.lore/` directory" in err


def test_mcp_run_auto_creates_when_lore_dir_exists(tmp_path, capsys, monkeypatch):
    """Parent `.lore/` exists but DB doesn't → auto-create and open.
    The user opted into Lore by creating the folder."""
    lore_dir = tmp_path / ".lore"
    lore_dir.mkdir()
    db = lore_dir / "lore.db"
    assert not db.exists()

    called = {}

    def fake_mcp_run_method(self):
        called["ran"] = True

    # We don't want to actually start the stdio loop in a test; patch
    # FastMCP.run so run() returns after building the server.
    from mcp.server.fastmcp import FastMCP
    monkeypatch.setattr(FastMCP, "run", fake_mcp_run_method)

    mcp_run(db)
    assert db.exists(), "DB must be auto-created when .lore/ parent exists"
    assert called.get("ran") is True
    err = capsys.readouterr().err
    assert "auto-creating" in err


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

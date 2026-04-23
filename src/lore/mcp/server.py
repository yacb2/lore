"""Lore MCP server — exposes the graph tools to LLM clients over stdio.

Every tool call is recorded in the `audit_log` table with byte counts so the
user can later answer "how much did Lore cost me on this project?" via
`lore stats` (see CLI).
"""

from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from lore.export import export_markdown as _export_markdown
from lore.graph import (
    add_edge as _add_edge,
)
from lore.graph import (
    add_edges_batch as _add_edges_batch,
)
from lore.graph import (
    add_node as _add_node,
)
from lore.graph import (
    add_nodes_batch as _add_nodes_batch,
)
from lore.graph import (
    audit as _audit,
)
from lore.graph import (
    delete_node as _delete_node,
)
from lore.graph import (
    find_variants as _find_variants,
)
from lore.graph import (
    get_node as _get_node,
)
from lore.graph import (
    history as _history,
)
from lore.graph import (
    list_edges as _list_edges,
)
from lore.graph import (
    list_nodes as _list_nodes,
)
from lore.graph import (
    log_call as _log_call,
)
from lore.graph import (
    open_db,
)
from lore.graph import (
    query as _query,
)
from lore.graph import (
    remove_edge as _remove_edge,
)
from lore.graph import (
    stats as _stats,
)
from lore.graph import (
    traverse as _traverse,
)
from lore.graph import (
    update_node as _update_node,
)


def _bytes(value: Any) -> int:
    """Approximate serialized size of a value in bytes (UTF-8 JSON)."""
    if value is None:
        return 0
    try:
        return len(json.dumps(value, default=str).encode("utf-8"))
    except (TypeError, ValueError):
        return len(str(value).encode("utf-8"))


def _instrumented(
    conn: sqlite3.Connection, tool_name: str, op: str
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that wraps a tool handler to log input/output sizes."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            in_bytes = _bytes(kwargs) + _bytes(list(args))
            node_id = kwargs.get("id") or kwargs.get("from_id")
            error: str | None = None
            result: Any = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                _log_call(
                    conn,
                    tool=tool_name,
                    op=op,
                    node_id=node_id if isinstance(node_id, str) else None,
                    input_bytes=in_bytes,
                    output_bytes=_bytes(result),
                    error=error,
                )

        return wrapper

    return decorator


def build_server(db_path: str | Path) -> FastMCP:
    """Create a FastMCP server bound to the given database."""
    conn: sqlite3.Connection = open_db(db_path)
    mcp = FastMCP("lore")

    @mcp.tool()
    @_instrumented(conn, "lore_add_node", "create")
    def lore_add_node(
        id: str,
        type: str,
        title: str,
        body: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a new node. Type must be one of: module, capability, flow,
        event, rule, form, entity, decision.

        Write content (title, body) in the same natural language the user uses
        in conversation. Populate `metadata.source` with one of
        `user_stated | user_confirmed | inferred_from_code |
        inferred_from_conversation` and `metadata.confidence`
        (`high | medium | low`) so the graph stays auditable."""
        return _add_node(
            conn,
            node_id=id,
            type=type,
            title=title,
            body=body,
            status=status,
            metadata=metadata,
        )

    @mcp.tool()
    @_instrumented(conn, "lore_add_nodes", "batch_create")
    def lore_add_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch-create nodes in a single transaction. Each item needs
        `id`, `type`, `title`; optional `body`, `status`, `metadata`.
        Fails atomically if any entry is invalid."""
        return _add_nodes_batch(conn, nodes)

    @mcp.tool()
    @_instrumented(conn, "lore_update_node", "update")
    def lore_update_node(
        id: str,
        title: str | None = None,
        body: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Update fields on an existing node. Pass only fields that changed.

        Use `metadata_patch` to merge keys into existing metadata (preferred —
        preserves provenance). Pass `null` as a value to remove a key. Use
        `metadata` only for full replacement (rare). Cannot combine both.
        Status values: active, draft, deprecated, superseded, archived."""
        return _update_node(
            conn,
            id,
            title=title,
            body=body,
            status=status,
            metadata=metadata,
            metadata_patch=metadata_patch,
        )

    @mcp.tool()
    @_instrumented(conn, "lore_delete_node", "delete")
    def lore_delete_node(id: str) -> dict[str, Any]:
        """Hard-delete a node and all its edges. **Destroys history** —
        prefer `lore_update_node(status="deprecated" | "archived")` for
        concepts that still matter. Returns `{deleted, edges_lost,
        warning}`; a non-empty `warning` appears when edges were dropped."""
        result = _delete_node(conn, id)
        if result["deleted"] and result["edges_lost"] > 0:
            result["warning"] = (
                f"{result['edges_lost']} edges destroyed. History of this "
                f"node is gone. Consider soft-delete next time."
            )
        return result

    @mcp.tool()
    @_instrumented(conn, "lore_get_node", "read")
    def lore_get_node(id: str, include_edges: bool = True) -> dict[str, Any]:
        """Fetch a node by id, optionally with its direct edges."""
        node = _get_node(conn, id)
        if node is None:
            return {"error": f"Node {id!r} not found"}
        result: dict[str, Any] = {"node": node}
        if include_edges:
            result["outgoing"] = _list_edges(conn, from_id=id)
            result["incoming"] = _list_edges(conn, to_id=id)
        return result

    @mcp.tool()
    @_instrumented(conn, "lore_add_edge", "create")
    def lore_add_edge(
        from_id: str,
        to_id: str,
        relation: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an edge between two existing nodes. The relation must be
        valid for the node types. Common pairs: `part_of` (flow/capability/
        form/event → module), `implements` (flow → capability), `depends_on`
        (module/flow → module/flow), `triggers` (flow/event → event/flow),
        `validates` (form → rule), `enforces` (rule → entity)."""
        return _add_edge(
            conn,
            from_id=from_id,
            to_id=to_id,
            relation=relation,
            metadata=metadata,
        )

    @mcp.tool()
    @_instrumented(conn, "lore_add_edges", "batch_create")
    def lore_add_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Batch-create edges in a single transaction. Each item needs
        `from_id`, `to_id`, `relation`; optional `metadata`."""
        return _add_edges_batch(conn, edges)

    @mcp.tool()
    @_instrumented(conn, "lore_remove_edge", "delete")
    def lore_remove_edge(
        from_id: str, to_id: str, relation: str
    ) -> dict[str, bool]:
        """Remove a specific edge."""
        return {
            "removed": _remove_edge(
                conn, from_id=from_id, to_id=to_id, relation=relation
            )
        }

    @mcp.tool()
    @_instrumented(conn, "lore_query", "read")
    def lore_query(text_or_id: str, depth: int = 1) -> dict[str, Any]:
        """Flexible search. Tries exact id, then title substring, then tag.
        `text_or_id` is required. Returns matched nodes plus neighborhood up
        to `depth`."""
        return _query(conn, text_or_id, depth=depth)

    @mcp.tool()
    @_instrumented(conn, "lore_traverse", "read")
    def lore_traverse(
        from_id: str,
        relations: list[str] | None = None,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """Walk the graph from a node, following only the listed relations
        (or all of them if None)."""
        return _traverse(
            conn, from_id, relations=relations, max_depth=max_depth
        )

    @mcp.tool()
    @_instrumented(conn, "lore_find_variants", "read")
    def lore_find_variants(capability_id: str) -> list[dict[str, Any]]:
        """List all flows that implement the given capability — answers
        'how many ways of doing X?'."""
        return _find_variants(conn, capability_id)

    @mcp.tool()
    @_instrumented(conn, "lore_list", "read")
    def lore_list(
        type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        include_body: bool = False,
    ) -> list[dict[str, Any]]:
        """List nodes, optionally filtered by type, status or tag. Returns
        id/type/title/status only by default (cheap for large graphs). Pass
        `include_body=True` for full nodes when you actually need them."""
        return _list_nodes(
            conn,
            type=type,
            status=status,
            tag=tag,
            summary_only=not include_body,
        )

    @mcp.tool()
    @_instrumented(conn, "lore_audit", "audit")
    def lore_audit() -> dict[str, Any]:
        """Run structural checks: orphans, dangling edges, id hygiene, cycles."""
        return _audit(conn)

    @mcp.tool()
    @_instrumented(conn, "lore_history", "read")
    def lore_history(id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return the change history for a node from the append-only audit
        log: every MCP call touching this id, newest first. Use to answer
        'what happened to this node?' or 'when was it deprecated?'."""
        return _history(conn, id, limit=limit)

    @mcp.tool()
    @_instrumented(conn, "lore_stats", "read")
    def lore_stats(since: str | None = None) -> dict[str, Any]:
        """Analytics from the append-only audit log. `since` is an optional
        ISO timestamp to scope the report. Returns total calls, bytes
        exchanged, per-tool and per-op breakdowns, and the first/last call
        timestamps."""
        return _stats(conn, since=since)

    @mcp.tool()
    @_instrumented(conn, "lore_export_markdown", "export")
    def lore_export_markdown(out_dir: str) -> dict[str, Any]:
        """Export the graph as one markdown file per node."""
        written = _export_markdown(conn, out_dir)
        return {"count": len(written), "out_dir": str(out_dir)}

    return mcp


def run(db_path: str | Path) -> None:
    """Run the MCP server over stdio.

    Always opens (and creates, if missing) the database at the given
    path. The server prints the resolved path to stderr on every start
    so the user can verify where writes are going; it also prints a
    loud "created new Lore graph" banner the first time a new path is
    materialized. Those two signals are sufficient to catch the "Claude
    Code launched from the wrong directory" footgun without forcing
    users to precreate `.lore/` by hand.
    """
    resolved = Path(db_path).resolve()
    was_new = not resolved.exists()
    if was_new:
        sys.stderr.write(
            "\n"
            "┌──────────────────────────────────────────────────────────────\n"
            "│ Lore MCP: creating new graph\n"
            f"│ path: {resolved}\n"
            "│ If this is not the project you intended, close Claude Code\n"
            "│ and re-open it from the correct directory. You can delete\n"
            f"│ {resolved.parent} to remove this empty graph.\n"
            "└──────────────────────────────────────────────────────────────\n"
        )
    sys.stderr.write(f"Lore MCP: using database at {resolved}\n")
    mcp = build_server(resolved)
    mcp.run()

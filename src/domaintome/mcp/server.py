"""DomainTome MCP server — exposes the graph tools to LLM clients over stdio.

Every tool call is recorded in the `audit_log` table with byte counts so the
user can later answer "how much did DomainTome cost me on this project?" via
`dt stats` (see CLI).
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import warnings
from collections.abc import Callable
from functools import wraps
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from domaintome.export import export_markdown as _export_markdown
from domaintome.graph import (
    add_edge as _add_edge,
)
from domaintome.graph import (
    add_edges_batch as _add_edges_batch,
)
from domaintome.graph import (
    add_node as _add_node,
)
from domaintome.graph import (
    add_nodes_batch as _add_nodes_batch,
)
from domaintome.graph import (
    audit as _audit,
)
from domaintome.graph import (
    delete_node as _delete_node,
)
from domaintome.graph import (
    find_variants as _find_variants,
)
from domaintome.graph import (
    get_node as _get_node,
)
from domaintome.graph import (
    history as _history,
)
from domaintome.graph import (
    list_edges as _list_edges,
)
from domaintome.graph import (
    list_nodes as _list_nodes,
)
from domaintome.graph import (
    log_call as _log_call,
)
from domaintome.graph import (
    open_db,
)
from domaintome.graph import (
    overview as _overview,
)
from domaintome.graph import (
    query as _query,
)
from domaintome.graph import (
    remove_edge as _remove_edge,
)
from domaintome.graph import (
    stats as _stats,
)
from domaintome.graph import (
    traverse as _traverse,
)
from domaintome.graph import (
    update_node as _update_node,
)
from domaintome.graph.schema import schema_descriptor as _schema_descriptor

# Default byte budget for tool responses that can grow unboundedly
# (`dt_traverse`, `dt_list`, `dt_query`). Overridable via the
# `DT_MAX_RESPONSE_BYTES` environment variable.
_DEFAULT_MAX_RESPONSE_BYTES = 30_000
_TRUNCATION_HINT = (
    "use filters (type/status/tag), narrower text_or_id, or lower max_depth"
)


def _max_response_bytes() -> int:
    raw = os.environ.get("DT_MAX_RESPONSE_BYTES")
    if raw is None:
        return _DEFAULT_MAX_RESPONSE_BYTES
    try:
        value = int(raw)
    except ValueError:
        return _DEFAULT_MAX_RESPONSE_BYTES
    return value if value > 0 else _DEFAULT_MAX_RESPONSE_BYTES


def _serialized_bytes(value: Any) -> int:
    return len(json.dumps(value, default=str).encode("utf-8"))


def _truncate_node_set(
    payload: dict[str, Any], max_bytes: int
) -> dict[str, Any]:
    """For `dt_traverse` / `dt_query` shape `{nodes, edges, ...}`. If the
    serialized payload exceeds `max_bytes`, drop nodes from the end and
    keep only edges contained in the remaining node set. Adds truncation
    metadata. Otherwise returns the payload unchanged."""
    nodes: list[dict[str, Any]] = list(payload.get("nodes") or [])
    edges: list[dict[str, Any]] = list(payload.get("edges") or [])
    if _serialized_bytes(payload) <= max_bytes:
        return payload

    total_nodes = len(nodes)

    def _fits(k: int) -> bool:
        kept_ids = {n["id"] for n in nodes[:k]}
        kept_edges = [
            e
            for e in edges
            if e["from_id"] in kept_ids and e["to_id"] in kept_ids
        ]
        candidate = {
            **payload,
            "nodes": nodes[:k],
            "edges": kept_edges,
            "_truncated": True,
            "_truncated_reason": "max_bytes",
            "_total_estimated": total_nodes,
            "_hint": _TRUNCATION_HINT,
        }
        return _serialized_bytes(candidate) <= max_bytes

    lo, hi = 0, total_nodes
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _fits(mid):
            lo = mid
        else:
            hi = mid - 1

    kept_ids = {n["id"] for n in nodes[:lo]}
    kept_edges = [
        e
        for e in edges
        if e["from_id"] in kept_ids and e["to_id"] in kept_ids
    ]
    return {
        **payload,
        "nodes": nodes[:lo],
        "edges": kept_edges,
        "_truncated": True,
        "_truncated_reason": "max_bytes",
        "_total_estimated": total_nodes,
        "_hint": _TRUNCATION_HINT,
    }


def _wrap_list_with_truncation(
    items: list[Any], max_bytes: int
) -> dict[str, Any]:
    """For `dt_list`: always wrap the items in a dict. If the serialized
    wrapper exceeds `max_bytes`, drop items from the end and add
    truncation metadata."""
    total = len(items)
    base: dict[str, Any] = {"items": items}
    if _serialized_bytes(base) <= max_bytes:
        return base

    def _fits(k: int) -> bool:
        candidate = {
            "items": items[:k],
            "_truncated": True,
            "_truncated_reason": "max_bytes",
            "_total_estimated": total,
            "_hint": _TRUNCATION_HINT,
        }
        return _serialized_bytes(candidate) <= max_bytes

    lo, hi = 0, total
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if _fits(mid):
            lo = mid
        else:
            hi = mid - 1
    return {
        "items": items[:lo],
        "_truncated": True,
        "_truncated_reason": "max_bytes",
        "_total_estimated": total,
        "_hint": _TRUNCATION_HINT,
    }


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
            node_type = kwargs.get("type")
            error: str | None = None
            result: Any = None
            t0 = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                raise
            finally:
                latency_ms = int((time.perf_counter() - t0) * 1000)
                warnings_count = 0
                if isinstance(result, dict):
                    w = result.get("warnings")
                    if isinstance(w, list):
                        warnings_count = len(w)
                elif isinstance(result, list):
                    for item in result:
                        if isinstance(item, dict):
                            w = item.get("warnings")
                            if isinstance(w, list):
                                warnings_count += len(w)
                _log_call(
                    conn,
                    tool=tool_name,
                    op=op,
                    node_id=node_id if isinstance(node_id, str) else None,
                    node_type=node_type if isinstance(node_type, str) else None,
                    input_bytes=in_bytes,
                    output_bytes=_bytes(result),
                    latency_ms=latency_ms,
                    warnings_count=warnings_count,
                    error=error,
                )

        return wrapper

    return decorator


def build_server(db_path: str | Path) -> FastMCP:
    """Create a FastMCP server bound to the given database."""
    conn: sqlite3.Connection = open_db(db_path)
    mcp = FastMCP("domaintome")

    def _shrink(node: dict[str, Any], return_mode: str) -> dict[str, Any]:
        """Default response shape is minimal: id + status + warnings.
        Pass return_mode='full' to get the entire persisted node."""
        if return_mode == "full":
            return node
        return {
            "id": node["id"],
            "type": node["type"],
            "status": node.get("status"),
            "warnings": node.get("warnings", []),
        }

    @mcp.tool()
    @_instrumented(conn, "dt_add_node", "create")
    def dt_add_node(
        id: str | None = None,
        type: str | None = None,
        title: str | None = None,
        body: str | None = None,
        status: str = "active",
        metadata: dict[str, Any] | None = None,
        return_mode: str = "summary",
        nodes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """USE ME after introducing new business behavior in code: a new
        endpoint/view, model, signal, management command, event, validation
        rule, form, module, or architectural decision. Also when the user
        confirms a flow that supersedes another, or when a new entity enters
        the domain.

        Two modes:

        - **Single node** (default): pass `id`, `type`, `title` (+ optional
          `body`, `status`, `metadata`). Returns `{id, type, status,
          warnings}` by default; pass `return_mode='full'` for the entire
          persisted node.
        - **Batch** (preferred for bootstrap / discovery): pass `nodes` as a
          list of dicts (each with `id`/`type`/`title` and the same optional
          fields). The other top-level args are ignored. Returns
          `{"results": [<shrunken-or-full>...]}`. Atomic — fails as a unit if
          any entry is invalid. Replaces the deprecated `dt_add_nodes` tool.

        Type must be one of: module, capability, flow, event, rule, form,
        entity, decision. Write `title`/`body` in the same natural language
        the user uses. `metadata.source` and `metadata.confidence` are
        canonical-only and rejected if invalid: pick `source` from
        `user_stated | user_confirmed | inferred_from_code |
        inferred_from_conversation | code_change | scan | incident | manual`,
        `confidence` from `high | medium | low`. Always set
        `metadata.source_ref` (path or path:line) so the node can be
        reconciled with code later. Read `warnings` on each result to fix
        soft issues (thin body, missing source, orphan rule/decision) on the
        next call."""
        if nodes is not None:
            results = _add_nodes_batch(conn, nodes)
            return {"results": [_shrink(n, return_mode) for n in results]}
        if not id or not type or not title:
            return {
                "error": (
                    "Provide either single-node args (id+type+title) or "
                    "the batch arg (nodes=[...])."
                )
            }
        node = _add_node(
            conn,
            node_id=id,
            type=type,
            title=title,
            body=body,
            status=status,
            metadata=metadata,
        )
        return _shrink(node, return_mode)

    @mcp.tool()
    @_instrumented(conn, "dt_add_nodes", "batch_create")
    def dt_add_nodes(
        nodes: list[dict[str, Any]],
        return_mode: str = "summary",
    ) -> list[dict[str, Any]]:
        """DEPRECATED — use `dt_add_node(nodes=[...])` instead. Will be
        removed in the next minor bump. This alias is kept for one release
        so existing prompts/skills keep working; it still persists every
        node atomically and returns the same shape it used to."""
        warnings.warn(
            "dt_add_nodes is deprecated; use dt_add_node(nodes=[...]).",
            DeprecationWarning,
            stacklevel=2,
        )
        results = _add_nodes_batch(conn, nodes)
        return [_shrink(n, return_mode) for n in results]

    @mcp.tool()
    @_instrumented(conn, "dt_schema", "read")
    def dt_schema() -> dict[str, Any]:
        """Return the schema descriptor: node types, statuses, allowed
        relations per `(from_type, to_type)` pair, recommended metadata
        vocabulary, id format, and body minimums.

        Call this **before** doing a batch write if you are unsure which
        relations are valid for a given pair — it is much cheaper than
        recovering from `SchemaError` rollbacks. The response is constant
        for a given DomainTome version."""
        return _schema_descriptor()

    @mcp.tool()
    @_instrumented(conn, "dt_update_node", "update")
    def dt_update_node(
        id: str,
        title: str | None = None,
        body: str | None = None,
        status: str | None = None,
        metadata: dict[str, Any] | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """USE ME after editing code that changes the behavior of an
        existing node — refactored flow, model field added, rule tightened,
        module reshaped. Also to soft-deprecate (`status="deprecated"`),
        archive, or refresh `metadata.last_verified_at`. Pass only the
        fields that changed.

        Prefer `metadata_patch` over `metadata`: it merges into existing
        metadata and preserves provenance (`source`, `confidence`,
        `source_ref`, history). Pass `null` as a value to remove a key.
        Use `metadata` only for full replacement (rare). Cannot combine
        both. Status values: active, draft, deprecated, superseded,
        archived."""
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
    @_instrumented(conn, "dt_delete_node", "delete")
    def dt_delete_node(id: str) -> dict[str, Any]:
        """Hard-delete a node and all its edges. **Destroys history** —
        prefer `dt_update_node(status="deprecated" | "archived")` for
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
    @_instrumented(conn, "dt_get_node", "read")
    def dt_get_node(id: str, include_edges: bool = True) -> dict[str, Any]:
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
    @_instrumented(conn, "dt_add_edge", "create")
    def dt_add_edge(
        from_id: str | None = None,
        to_id: str | None = None,
        relation: str | None = None,
        metadata: dict[str, Any] | None = None,
        edges: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """USE ME after creating or updating nodes to wire them into the
        rest of the graph: a new flow needs `implements` to its capability
        and `part_of` to its module; a new rule needs `enforces` to the
        entity it protects; a superseding decision needs `supersedes`. An
        unconnected node is invisible in traversals.

        Two modes:

        - **Single edge** (default): pass `from_id`, `to_id`, `relation`
          (+ optional `metadata`). Returns the persisted edge dict.
        - **Batch**: pass `edges` as a list of dicts (each with `from_id`,
          `to_id`, `relation` + optional `metadata`). Other top-level args
          are ignored. Returns `{"results": [...]}`. Atomic — fails as a
          unit if any edge is invalid for its node-type pair. Replaces the
          deprecated `dt_add_edges` tool.

        Common relation pairs: `part_of` (flow/capability/form/event →
        module), `implements` (flow → capability), `depends_on`
        (module/flow → module/flow), `triggers` (flow/event → event/flow),
        `validates` (form → rule), `enforces` (rule → entity). Call
        `dt_schema` first if unsure — cheaper than recovering from a
        `SchemaError`."""
        if edges is not None:
            return {"results": _add_edges_batch(conn, edges)}
        if not from_id or not to_id or not relation:
            return {
                "error": (
                    "Provide either single-edge args (from_id+to_id+relation) "
                    "or the batch arg (edges=[...])."
                )
            }
        return _add_edge(
            conn,
            from_id=from_id,
            to_id=to_id,
            relation=relation,
            metadata=metadata,
        )

    @mcp.tool()
    @_instrumented(conn, "dt_add_edges", "batch_create")
    def dt_add_edges(edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """DEPRECATED — use `dt_add_edge(edges=[...])` instead. Will be
        removed in the next minor bump. This alias is kept for one release
        so existing prompts/skills keep working; it still persists every
        edge atomically and returns the same shape it used to."""
        warnings.warn(
            "dt_add_edges is deprecated; use dt_add_edge(edges=[...]).",
            DeprecationWarning,
            stacklevel=2,
        )
        return _add_edges_batch(conn, edges)

    @mcp.tool()
    @_instrumented(conn, "dt_remove_edge", "delete")
    def dt_remove_edge(
        from_id: str, to_id: str, relation: str
    ) -> dict[str, bool]:
        """Remove a specific edge."""
        return {
            "removed": _remove_edge(
                conn, from_id=from_id, to_id=to_id, relation=relation
            )
        }

    @mcp.tool()
    @_instrumented(conn, "dt_query", "read")
    def dt_query(text_or_id: str, depth: int = 1) -> dict[str, Any]:
        """Flexible search. Tries exact id, then title substring, then tag.
        `text_or_id` is required. Returns matched nodes plus neighborhood up
        to `depth`.

        Large neighborhoods are truncated by serialized size
        (`DT_MAX_RESPONSE_BYTES`, default 30KB). Truncated responses carry
        `_truncated: true`, `_truncated_reason`, `_total_estimated` and
        `_hint`. Absence of `_truncated` means the result is complete."""
        return _truncate_node_set(
            _query(conn, text_or_id, depth=depth), _max_response_bytes()
        )

    @mcp.tool()
    @_instrumented(conn, "dt_traverse", "read")
    def dt_traverse(
        from_id: str,
        relations: list[str] | None = None,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """Walk the graph from a node, following only the listed relations
        (or all of them if None).

        Large traversals are truncated by serialized size
        (`DT_MAX_RESPONSE_BYTES`, default 30KB). Truncated responses carry
        `_truncated: true`, `_truncated_reason`, `_total_estimated` and
        `_hint`. Absence of `_truncated` means the result is complete."""
        return _truncate_node_set(
            _traverse(conn, from_id, relations=relations, max_depth=max_depth),
            _max_response_bytes(),
        )

    @mcp.tool()
    @_instrumented(conn, "dt_find_variants", "read")
    def dt_find_variants(capability_id: str) -> list[dict[str, Any]]:
        """List all flows that implement the given capability — answers
        'how many ways of doing X?'."""
        return _find_variants(conn, capability_id)

    @mcp.tool()
    @_instrumented(conn, "dt_list", "read")
    def dt_list(
        type: str | None = None,
        status: str | None = None,
        tag: str | None = None,
        include_body: bool = False,
    ) -> dict[str, Any]:
        """List nodes, optionally filtered by type, status or tag. Returns
        id/type/title/status only by default (cheap for large graphs). Pass
        `include_body=True` for full nodes when you actually need them.

        Always returns `{"items": [...]}` (wrapped). Large responses are
        truncated by serialized size (`DT_MAX_RESPONSE_BYTES`, default
        30KB); truncated responses carry `_truncated: true`,
        `_truncated_reason`, `_total_estimated` and `_hint`. Absence of
        `_truncated` means the list is complete."""
        items = _list_nodes(
            conn,
            type=type,
            status=status,
            tag=tag,
            summary_only=not include_body,
        )
        return _wrap_list_with_truncation(items, _max_response_bytes())

    @mcp.tool()
    @_instrumented(conn, "dt_overview", "read")
    def dt_overview() -> dict[str, Any]:
        """USE ME FIRST when landing on a project for the first time, or
        whenever you need a one-shot map of the graph before deciding
        where to drill. Returns a compact bootstrap payload:
        `node_counts` (by type), `total_nodes`, `top_capabilities`
        (capabilities ranked by `implements` variant count, max 10),
        `recent_decisions` (last 5 decision nodes by `updated_at`),
        `recent_changes` (nodes modified in the last 7 days, max 10),
        and a one-line `health_summary` flagging orphans.

        Stays under ~2KB on realistic graphs — cheap to call before any
        `dt_list`/`dt_traverse`. Does not replace `dt_schema` (which
        describes valid types/relations, not content)."""
        return _overview(conn)

    @mcp.tool()
    @_instrumented(conn, "dt_audit", "audit")
    def dt_audit() -> dict[str, Any]:
        """Run structural checks: orphans, dangling edges, id hygiene, cycles."""
        return _audit(conn)

    @mcp.tool()
    @_instrumented(conn, "dt_history", "read")
    def dt_history(id: str, limit: int = 100) -> list[dict[str, Any]]:
        """Return the change history for a node from the append-only audit
        log: every MCP call touching this id, newest first. Use to answer
        'what happened to this node?' or 'when was it deprecated?'."""
        return _history(conn, id, limit=limit)

    @mcp.tool()
    @_instrumented(conn, "dt_stats", "read")
    def dt_stats(since: str | None = None) -> dict[str, Any]:
        """Analytics from the append-only audit log. `since` is an optional
        ISO timestamp to scope the report. Returns total calls, bytes
        exchanged, per-tool and per-op breakdowns, and the first/last call
        timestamps."""
        return _stats(conn, since=since)

    @mcp.tool()
    @_instrumented(conn, "dt_export_markdown", "export")
    def dt_export_markdown(out_dir: str) -> dict[str, Any]:
        """Export the graph as one markdown file per node."""
        written = _export_markdown(conn, out_dir)
        return {"count": len(written), "out_dir": str(out_dir)}

    return mcp


def run(db_path: str | Path) -> None:
    """Run the MCP server over stdio.

    Always opens (and creates, if missing) the database at the given
    path. The server prints the resolved path to stderr on every start
    so the user can verify where writes are going; it also prints a
    loud "created new DomainTome graph" banner the first time a new path is
    materialized. Those two signals are sufficient to catch the "Claude
    Code launched from the wrong directory" footgun without forcing
    users to precreate `.dt/` by hand.
    """
    resolved = Path(db_path).resolve()
    was_new = not resolved.exists()
    if was_new:
        sys.stderr.write(
            "\n"
            "┌──────────────────────────────────────────────────────────────\n"
            "│ DomainTome MCP: creating new graph\n"
            f"│ path: {resolved}\n"
            "│ If this is not the project you intended, close Claude Code\n"
            "│ and re-open it from the correct directory. You can delete\n"
            f"│ {resolved.parent} to remove this empty graph.\n"
            "└──────────────────────────────────────────────────────────────\n"
        )
    sys.stderr.write(f"DomainTome MCP: using database at {resolved}\n")
    mcp = build_server(resolved)
    mcp.run()

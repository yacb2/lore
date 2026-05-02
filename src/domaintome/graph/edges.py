"""CRUD operations for graph edges."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from domaintome.graph._common import now_iso, placeholders, row_to_dict
from domaintome.graph.nodes import get_node
from domaintome.graph.schema import SchemaError, validate_edge_types


def add_edge(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    to_id: str,
    relation: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an edge. Both nodes must exist and the relation must be allowed
    between their types."""
    from_node = get_node(conn, from_id)
    if from_node is None:
        raise SchemaError(f"Source node {from_id!r} not found")
    to_node = get_node(conn, to_id)
    if to_node is None:
        raise SchemaError(f"Target node {to_id!r} not found")

    validate_edge_types(relation, from_node["type"], to_node["type"])

    now = now_iso()
    meta_json = json.dumps(metadata) if metadata else None
    conn.execute(
        """
        INSERT INTO edges (from_id, to_id, relation, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (from_id, to_id, relation, meta_json, now),
    )
    conn.commit()
    return {
        "from_id": from_id,
        "to_id": to_id,
        "relation": relation,
        "metadata": metadata or {},
        "created_at": now,
    }


def remove_edge(
    conn: sqlite3.Connection,
    *,
    from_id: str,
    to_id: str,
    relation: str,
) -> bool:
    """Delete a specific edge. Returns True if a row was removed."""
    cur = conn.execute(
        "DELETE FROM edges WHERE from_id = ? AND to_id = ? AND relation = ?",
        (from_id, to_id, relation),
    )
    conn.commit()
    return cur.rowcount > 0


def add_edges_batch(
    conn: sqlite3.Connection, specs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Insert many edges in one transaction. Each spec needs `from_id`,
    `to_id`, `relation`; optional `metadata`. Validates types per-spec and
    fails atomically."""
    prepared: list[tuple[Any, ...]] = []
    now = now_iso()
    results: list[dict[str, Any]] = []

    referenced = {s["from_id"] for s in specs} | {s["to_id"] for s in specs}
    if referenced:
        ids = list(referenced)
        rows = conn.execute(
            f"SELECT id, type FROM nodes WHERE id IN ({placeholders(len(ids))})",
            ids,
        ).fetchall()
        types_by_id = {r["id"]: r["type"] for r in rows}
    else:
        types_by_id = {}

    for s in specs:
        from_id = s["from_id"]
        to_id = s["to_id"]
        relation = s["relation"]
        if from_id not in types_by_id:
            raise SchemaError(f"Source node {from_id!r} not found")
        if to_id not in types_by_id:
            raise SchemaError(f"Target node {to_id!r} not found")
        validate_edge_types(relation, types_by_id[from_id], types_by_id[to_id])
        meta = s.get("metadata")
        prepared.append(
            (from_id, to_id, relation, json.dumps(meta) if meta else None, now)
        )
        results.append(
            {
                "from_id": from_id,
                "to_id": to_id,
                "relation": relation,
                "metadata": meta or {},
                "created_at": now,
            }
        )
    conn.executemany(
        """
        INSERT INTO edges (from_id, to_id, relation, metadata_json, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        prepared,
    )
    conn.commit()
    return results


def list_edges(
    conn: sqlite3.Connection,
    *,
    from_id: str | None = None,
    to_id: str | None = None,
    relation: str | None = None,
) -> list[dict[str, Any]]:
    """List edges with optional filters."""
    clauses: list[str] = []
    values: list[Any] = []
    if from_id is not None:
        clauses.append("from_id = ?")
        values.append(from_id)
    if to_id is not None:
        clauses.append("to_id = ?")
        values.append(to_id)
    if relation is not None:
        clauses.append("relation = ?")
        values.append(relation)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(f"SELECT * FROM edges {where} ORDER BY created_at", values).fetchall()
    return [row_to_dict(r) for r in rows]

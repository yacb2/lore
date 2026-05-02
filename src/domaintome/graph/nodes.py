"""CRUD operations for graph nodes."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from domaintome.graph._common import now_iso, row_to_dict
from domaintome.graph.schema import (
    SchemaError,
    validate_id,
    validate_metadata_vocabulary,
    validate_node_type,
    validate_status,
)
from domaintome.graph.warnings import orphan_warning, warnings_for_node_spec


def _build_warnings(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    node_type: str,
    body: str | None,
    metadata: dict[str, Any] | None,
) -> list[str]:
    out = warnings_for_node_spec(node_type=node_type, body=body, metadata=metadata)
    orphan = orphan_warning(conn, node_id=node_id, node_type=node_type)
    if orphan:
        out.append(orphan)
    return out


def add_node(
    conn: sqlite3.Connection,
    *,
    node_id: str,
    type: str,
    title: str,
    body: str | None = None,
    status: str = "active",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Insert a new node. Raises SchemaError on validation failure or
    sqlite3.IntegrityError if the id already exists.

    Returns the persisted node (including its `warnings` list — empty when
    the spec is fully canonical)."""
    validate_id(node_id)
    validate_node_type(type)
    validate_status(status)
    validate_metadata_vocabulary(metadata)
    if not title or not title.strip():
        raise SchemaError("title is required and cannot be empty")

    now = now_iso()
    meta_json = json.dumps(metadata) if metadata else None
    conn.execute(
        """
        INSERT INTO nodes (id, type, title, body, status, metadata_json,
                           created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (node_id, type, title, body, status, meta_json, now, now),
    )
    conn.commit()
    node = get_node(conn, node_id)
    assert node is not None
    node["warnings"] = _build_warnings(
        conn, node_id=node_id, node_type=type, body=body, metadata=metadata
    )
    return node


def update_node(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
    metadata_patch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update mutable fields on an existing node. Pass only the fields to change.

    `metadata` replaces the entire metadata dict (use sparingly — loses
    provenance). `metadata_patch` merges into the existing dict at the top
    level; pass `None` as a value to remove a key. Cannot combine both."""
    if metadata is not None and metadata_patch is not None:
        raise SchemaError("pass either metadata or metadata_patch, not both")

    existing = get_node(conn, node_id)
    if existing is None:
        raise SchemaError(f"Node {node_id!r} not found")

    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        if not title.strip():
            raise SchemaError("title cannot be empty")
        fields.append("title = ?")
        values.append(title)
    if body is not None:
        fields.append("body = ?")
        values.append(body)
    if status is not None:
        validate_status(status)
        fields.append("status = ?")
        values.append(status)
    if metadata is not None:
        validate_metadata_vocabulary(metadata)
        fields.append("metadata_json = ?")
        values.append(json.dumps(metadata) if metadata else None)
    elif metadata_patch is not None:
        validate_metadata_vocabulary(metadata_patch)
        merged = dict(existing.get("metadata") or {})
        for k, v in metadata_patch.items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        fields.append("metadata_json = ?")
        values.append(json.dumps(merged) if merged else None)

    if not fields:
        return existing

    fields.append("updated_at = ?")
    values.append(now_iso())
    values.append(node_id)
    conn.execute(
        f"UPDATE nodes SET {', '.join(fields)} WHERE id = ?",
        values,
    )
    conn.commit()
    return get_node(conn, node_id)  # type: ignore[return-value]


def delete_node(conn: sqlite3.Connection, node_id: str) -> dict[str, Any]:
    """Hard-delete a node and all its edges (via FK cascade).

    Returns `{"deleted": bool, "edges_lost": int}`. Prefer soft-delete
    (`update_node(status="deprecated" | "archived")`) to preserve history —
    this operation is irreversible."""
    edges_lost = conn.execute(
        "SELECT COUNT(*) FROM edges WHERE from_id = ? OR to_id = ?",
        (node_id, node_id),
    ).fetchone()[0]
    cur = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    conn.commit()
    return {"deleted": cur.rowcount > 0, "edges_lost": edges_lost}


def get_node(conn: sqlite3.Connection, node_id: str) -> dict[str, Any] | None:
    """Fetch a node by id. Returns None if not found."""
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row_to_dict(row) if row else None


def add_nodes_batch(
    conn: sqlite3.Connection, specs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Insert many nodes in one transaction. Each spec must have keys
    `id`, `type`, `title`; optional: `body`, `status`, `metadata`.

    Fails atomically: if any spec is invalid, none are inserted. Each
    returned dict carries a `warnings` list."""
    prepared: list[tuple[Any, ...]] = []
    now = now_iso()
    for s in specs:
        node_id = s["id"]
        node_type = s["type"]
        title = s["title"]
        validate_id(node_id)
        validate_node_type(node_type)
        status = s.get("status", "active")
        validate_status(status)
        if not title or not title.strip():
            raise SchemaError(f"title is required for node {node_id!r}")
        meta = s.get("metadata")
        validate_metadata_vocabulary(meta)
        prepared.append(
            (
                node_id,
                node_type,
                title,
                s.get("body"),
                status,
                json.dumps(meta) if meta else None,
                now,
                now,
            )
        )
    conn.executemany(
        """
        INSERT INTO nodes (id, type, title, body, status, metadata_json,
                           created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        prepared,
    )
    conn.commit()
    results: list[dict[str, Any]] = []
    for s in specs:
        warnings = _build_warnings(
            conn,
            node_id=s["id"],
            node_type=s["type"],
            body=s.get("body"),
            metadata=s.get("metadata"),
        )
        results.append(
            {
                "id": s["id"],
                "type": s["type"],
                "title": s["title"],
                "body": s.get("body"),
                "status": s.get("status", "active"),
                "metadata": s.get("metadata") or {},
                "created_at": now,
                "updated_at": now,
                "warnings": warnings,
            }
        )
    return results

"""CRUD operations for graph nodes."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from lore.graph._common import now_iso, row_to_dict
from lore.graph.schema import (
    SchemaError,
    validate_id,
    validate_node_type,
    validate_status,
)

# Back-compat aliases for any external code that imported these.
_now = now_iso
_row_to_dict = row_to_dict


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
    sqlite3.IntegrityError if the id already exists."""
    validate_id(node_id)
    validate_node_type(type)
    validate_status(status)
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
    return get_node(conn, node_id)  # type: ignore[return-value]


def update_node(
    conn: sqlite3.Connection,
    node_id: str,
    *,
    title: str | None = None,
    body: str | None = None,
    status: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Update mutable fields on an existing node. Pass only the fields to change.
    Passing `metadata` replaces the entire metadata dict."""
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
        fields.append("metadata_json = ?")
        values.append(json.dumps(metadata) if metadata else None)

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


def delete_node(conn: sqlite3.Connection, node_id: str) -> bool:
    """Delete a node and all its edges (via FK cascade). Returns True if a row
    was deleted."""
    cur = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    conn.commit()
    return cur.rowcount > 0


def get_node(conn: sqlite3.Connection, node_id: str) -> dict[str, Any] | None:
    """Fetch a node by id. Returns None if not found."""
    row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    return row_to_dict(row) if row else None


def add_nodes_batch(
    conn: sqlite3.Connection, specs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Insert many nodes in one transaction. Each spec must have keys
    `id`, `type`, `title`; optional: `body`, `status`, `metadata`.

    Fails atomically: if any spec is invalid, none are inserted."""
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
    return [get_node(conn, s["id"]) for s in specs]  # type: ignore[misc]

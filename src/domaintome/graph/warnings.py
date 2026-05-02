"""Soft validation warnings emitted on write operations.

These checks never block persistence — they produce a list of advisory
messages so the LLM (or the user) can self-correct over time. Hard schema
errors live in `schema.py`.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from domaintome.graph.schema import (
    BODY_MIN_CHARS,
    BODY_REQUIRED_TYPES,
    CANONICAL_CONFIDENCES,
    CANONICAL_SOURCES,
)

# Tipos donde un nodo recién creado sin edges salientes suele indicar
# que olvidamos conectarlo (rule sin enforces, decision sin supersedes/...).
ORPHAN_SENSITIVE_TYPES: frozenset[str] = frozenset({"rule", "decision"})


def warnings_for_node_spec(
    *,
    node_type: str,
    body: str | None,
    metadata: dict[str, Any] | None,
) -> list[str]:
    """Soft checks at create time. Returns the list of warning strings."""
    out: list[str] = []
    if node_type in BODY_REQUIRED_TYPES:
        body_len = len(body or "")
        if body_len < BODY_MIN_CHARS:
            out.append(
                f"body_thin: {node_type!r} has body of {body_len} chars "
                f"(< {BODY_MIN_CHARS}). Add a description so future readers "
                f"understand what this {node_type} is."
            )
    meta = metadata or {}
    if meta.get("source") is None:
        out.append(
            "missing_source: metadata.source is required for provenance "
            f"(use one of: {sorted(CANONICAL_SOURCES)})."
        )
    if meta.get("confidence") is None:
        out.append(
            "missing_confidence: metadata.confidence is recommended "
            f"({sorted(CANONICAL_CONFIDENCES)})."
        )
    if meta.get("source_ref") is None:
        out.append(
            "missing_source_ref: metadata.source_ref (path:line) is "
            "recommended so the node can be reconciled with code."
        )
    return out


def orphan_warning(
    conn: sqlite3.Connection, *, node_id: str, node_type: str
) -> str | None:
    """If a freshly created rule/decision has no outgoing edges, suggest
    connecting it to the rest of the graph."""
    if node_type not in ORPHAN_SENSITIVE_TYPES:
        return None
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM edges WHERE from_id = ?",
        (node_id,),
    ).fetchone()
    if row and row["n"] == 0:
        if node_type == "rule":
            hint = "consider rule -enforces-> entity, or part_of/references"
        else:
            hint = "consider decision <-references- (other nodes), or supersedes"
        return f"orphan: {node_type} {node_id!r} has no outgoing edges — {hint}"
    return None

"""Content-quality report. Complements `audit` (which checks structural
integrity) by inspecting how good the *content* of the graph is: provenance
coverage, body length, source vocabulary, orphans by type, top error
patterns from the audit_log.

Used by `dt quality` CLI command and the upcoming MCP probe.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from domaintome.graph.schema import (
    BODY_MIN_CHARS,
    BODY_REQUIRED_TYPES,
    CANONICAL_CONFIDENCES,
    CANONICAL_SOURCES,
)


def _coerce_meta(meta_json: str | None) -> dict[str, Any]:
    if not meta_json:
        return {}
    try:
        v = json.loads(meta_json)
        return v if isinstance(v, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def quality_report(conn: sqlite3.Connection) -> dict[str, Any]:
    """Compute the full quality snapshot. Read-only."""
    rows = conn.execute(
        "SELECT id, type, body, metadata_json FROM nodes"
    ).fetchall()

    by_type: dict[str, dict[str, int]] = {}
    body_thin: list[dict[str, str]] = []
    missing_source: list[str] = []
    non_canonical_source: dict[str, int] = {}
    missing_confidence = 0
    non_canonical_confidence: dict[str, int] = {}
    missing_source_ref = 0

    for r in rows:
        ntype = r["type"]
        bucket = by_type.setdefault(
            ntype, {"total": 0, "with_body": 0, "with_source": 0, "with_ref": 0}
        )
        bucket["total"] += 1
        body = r["body"] or ""
        if body.strip():
            bucket["with_body"] += 1
        if ntype in BODY_REQUIRED_TYPES and len(body) < BODY_MIN_CHARS:
            body_thin.append({"id": r["id"], "type": ntype, "body_len": str(len(body))})

        meta = _coerce_meta(r["metadata_json"])
        src = meta.get("source")
        if src:
            bucket["with_source"] += 1
            if src not in CANONICAL_SOURCES:
                non_canonical_source[src] = non_canonical_source.get(src, 0) + 1
        else:
            missing_source.append(r["id"])

        conf = meta.get("confidence")
        if conf is None:
            missing_confidence += 1
        elif conf not in CANONICAL_CONFIDENCES:
            non_canonical_confidence[conf] = (
                non_canonical_confidence.get(conf, 0) + 1
            )

        if meta.get("source_ref"):
            bucket["with_ref"] += 1
        else:
            missing_source_ref += 1

    # Top rejected relations / id errors from the audit log.
    schema_errors: list[dict[str, Any]] = []
    try:
        rows_err = conn.execute(
            """
            SELECT error, COUNT(*) AS n
            FROM audit_log
            WHERE error IS NOT NULL
            GROUP BY error
            ORDER BY n DESC
            LIMIT 10
            """,
        ).fetchall()
        schema_errors = [{"error": r["error"], "count": r["n"]} for r in rows_err]
    except sqlite3.Error:
        pass

    # Warning distribution (only available on v0.1.0+ DBs).
    warnings_by_tool: list[dict[str, Any]] = []
    try:
        rows_w = conn.execute(
            """
            SELECT tool,
                   SUM(warnings_count) AS w_total,
                   COUNT(*) AS calls
            FROM audit_log
            WHERE warnings_count > 0
            GROUP BY tool
            ORDER BY w_total DESC
            """
        ).fetchall()
        warnings_by_tool = [
            {"tool": r["tool"], "warnings": r["w_total"], "calls": r["calls"]}
            for r in rows_w
        ]
    except sqlite3.Error:
        pass

    # Orphans by type — duplicates structural audit but breaks them out by
    # type so the user sees, e.g., "5 rules orphan, 3 decisions orphan".
    orphan_rows = conn.execute(
        """
        SELECT n.id, n.type
        FROM nodes n
        LEFT JOIN edges e1 ON e1.from_id = n.id
        LEFT JOIN edges e2 ON e2.to_id = n.id
        WHERE e1.from_id IS NULL AND e2.to_id IS NULL
        """
    ).fetchall()
    orphans_by_type: dict[str, int] = {}
    for r in orphan_rows:
        orphans_by_type[r["type"]] = orphans_by_type.get(r["type"], 0) + 1

    return {
        "node_total": len(rows),
        "by_type": by_type,
        "body_thin": body_thin,
        "missing_source": missing_source,
        "non_canonical_source": non_canonical_source,
        "missing_confidence": missing_confidence,
        "non_canonical_confidence": non_canonical_confidence,
        "missing_source_ref": missing_source_ref,
        "orphans_by_type": orphans_by_type,
        "top_errors": schema_errors,
        "warnings_by_tool": warnings_by_tool,
    }


def stats_by_day(
    conn: sqlite3.Connection, *, since: str | None = None
) -> list[dict[str, Any]]:
    """Per-day breakdown of MCP calls + errors + warnings."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()
    rows = conn.execute(
        f"""
        SELECT substr(timestamp, 1, 10) AS day,
               COUNT(*) AS calls,
               SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) AS errors,
               COALESCE(SUM(warnings_count), 0) AS warnings,
               COALESCE(SUM(input_bytes + output_bytes), 0) AS bytes
        FROM audit_log {where}
        GROUP BY day
        ORDER BY day ASC
        """,
        params,
    ).fetchall()
    return [dict(r) for r in rows]


def errors_breakdown(
    conn: sqlite3.Connection, *, since: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Top error messages over the period, with first/last seen."""
    where = "WHERE error IS NOT NULL"
    params: list[Any] = []
    if since:
        where += " AND timestamp >= ?"
        params.append(since)
    rows = conn.execute(
        f"""
        SELECT tool, error,
               COUNT(*) AS n,
               MIN(timestamp) AS first_seen,
               MAX(timestamp) AS last_seen
        FROM audit_log {where}
        GROUP BY tool, error
        ORDER BY n DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()
    return [dict(r) for r in rows]

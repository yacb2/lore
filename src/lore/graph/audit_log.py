"""Append-only log of MCP tool calls for analytics and provenance auditing.

Every MCP tool call writes one row with input/output byte counts so the user
can later answer "how much did Lore cost me this week on this project?"
without depending on external observability.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from lore.graph._common import now_iso


def log_call(
    conn: sqlite3.Connection,
    *,
    tool: str,
    op: str,
    node_id: str | None = None,
    input_bytes: int = 0,
    output_bytes: int = 0,
    error: str | None = None,
) -> None:
    """Insert one audit log row. Swallows its own errors — logging must not
    break tool calls."""
    try:
        conn.execute(
            """
            INSERT INTO audit_log (timestamp, tool, op, node_id, input_bytes,
                                   output_bytes, error)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (now_iso(), tool, op, node_id, input_bytes, output_bytes, error),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def stats(
    conn: sqlite3.Connection,
    *,
    since: str | None = None,
) -> dict[str, Any]:
    """Summarize audit_log usage. If `since` is given (ISO timestamp), only
    count rows at or after that time."""
    where = "WHERE timestamp >= ?" if since else ""
    params: tuple[Any, ...] = (since,) if since else ()

    totals_row = conn.execute(
        f"""
        SELECT
          COUNT(*) AS calls,
          COALESCE(SUM(input_bytes), 0) AS input_bytes,
          COALESCE(SUM(output_bytes), 0) AS output_bytes,
          COALESCE(SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END), 0) AS errors
        FROM audit_log {where}
        """,
        params,
    ).fetchone()

    by_tool = conn.execute(
        f"""
        SELECT tool,
               COUNT(*) AS calls,
               COALESCE(SUM(input_bytes), 0) AS input_bytes,
               COALESCE(SUM(output_bytes), 0) AS output_bytes
        FROM audit_log {where}
        GROUP BY tool
        ORDER BY calls DESC
        """,
        params,
    ).fetchall()

    by_op = conn.execute(
        f"""
        SELECT op, COUNT(*) AS calls
        FROM audit_log {where}
        GROUP BY op
        ORDER BY calls DESC
        """,
        params,
    ).fetchall()

    first_last = conn.execute(
        f"""
        SELECT MIN(timestamp) AS first, MAX(timestamp) AS last
        FROM audit_log {where}
        """,
        params,
    ).fetchone()

    return {
        "since": since,
        "calls": totals_row["calls"],
        "input_bytes": totals_row["input_bytes"],
        "output_bytes": totals_row["output_bytes"],
        "total_bytes": totals_row["input_bytes"] + totals_row["output_bytes"],
        "errors": totals_row["errors"],
        "first_call_at": first_last["first"],
        "last_call_at": first_last["last"],
        "by_tool": [dict(r) for r in by_tool],
        "by_op": [dict(r) for r in by_op],
    }

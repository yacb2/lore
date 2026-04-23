"""Lifecycle operations: detect drift between the graph and the code.

`reconcile` reports three kinds of drift without writing anything to the
graph:

- **dead_refs** — nodes whose `metadata.source_ref` points to a file that
  no longer exists.
- **stale** — nodes with `metadata.last_verified_at` older than
  `stale_days` (default 90).
- **never_verified** — nodes that have a `source_ref` but no
  `last_verified_at` at all. Lower priority than `stale` but worth
  surfacing after a bootstrap.

The caller decides what to do with the findings. Reconcile never mutates.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def reconcile(
    conn: sqlite3.Connection,
    root: Path,
    *,
    since: str | None = None,
    stale_days: int = 90,
) -> dict[str, Any]:
    """Scan the graph and report drift relative to the code at ``root``.

    Parameters
    ----------
    conn
        Open Lore database connection.
    root
        Filesystem path to resolve relative ``source_ref`` values against.
        Typically the directory that contains ``.lore/``.
    since
        Optional git revision. When provided and ``root`` is a git repo,
        restricts the scan to files changed between ``since`` and ``HEAD``.
        If ``root`` is not a git repo the filter is silently dropped and
        the full graph is scanned; the returned report signals this via
        ``warnings``.
    stale_days
        Threshold in days for the ``stale`` category.
    """
    warnings: list[str] = []
    touched: set[str] | None = None
    if since is not None:
        if (root / ".git").exists():
            try:
                out = subprocess.run(
                    ["git", "-C", str(root), "diff", "--name-only", since, "HEAD"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if out.returncode == 0:
                    touched = {
                        line.strip() for line in out.stdout.splitlines() if line.strip()
                    }
                else:
                    warnings.append(
                        f"git diff against {since!r} failed; falling back to full scan"
                    )
            except FileNotFoundError:
                warnings.append("git not available; falling back to full scan")
        else:
            warnings.append(
                f"{root} is not a git repo; `--since` ignored, scanning full graph"
            )

    rows = conn.execute(
        "SELECT id, status, metadata_json FROM nodes WHERE metadata_json IS NOT NULL"
    ).fetchall()

    dead_refs: list[dict[str, Any]] = []
    stale: list[dict[str, Any]] = []
    never_verified: list[dict[str, Any]] = []
    planned: list[dict[str, Any]] = []

    now = datetime.now(timezone.utc)
    scanned = 0

    for row in rows:
        try:
            meta = json.loads(row["metadata_json"]) or {}
        except (TypeError, json.JSONDecodeError):
            continue
        source_ref = meta.get("source_ref")
        if not source_ref:
            continue

        path_str = source_ref.split(":", 1)[0]
        if touched is not None and path_str not in touched:
            continue

        scanned += 1
        if not (root / path_str).exists():
            # Draft nodes are "in-progress, not yet real" by definition;
            # a missing file is expected and informational, not a dead
            # reference. Surface separately so the user still has
            # visibility into what hasn't landed yet.
            if row["status"] == "draft":
                planned.append(
                    {"id": row["id"], "source_ref": source_ref}
                )
            else:
                dead_refs.append(
                    {
                        "id": row["id"],
                        "source_ref": source_ref,
                        "reason": "file_missing",
                    }
                )
            continue

        last_verified = meta.get("last_verified_at")
        if not last_verified:
            never_verified.append({"id": row["id"], "source_ref": source_ref})
            continue

        try:
            lv_raw = str(last_verified).replace("Z", "+00:00")
            lv = datetime.fromisoformat(lv_raw)
            if lv.tzinfo is None:
                lv = lv.replace(tzinfo=timezone.utc)
        except ValueError:
            warnings.append(
                f"node {row['id']!r} has unparseable last_verified_at={last_verified!r}"
            )
            continue

        days = (now - lv).days
        if days >= stale_days:
            stale.append(
                {
                    "id": row["id"],
                    "last_verified_at": last_verified,
                    "days_since": days,
                }
            )

    return {
        "dead_refs": sorted(dead_refs, key=lambda x: x["id"]),
        "stale": sorted(stale, key=lambda x: -x["days_since"]),
        "never_verified": sorted(never_verified, key=lambda x: x["id"]),
        "planned": sorted(planned, key=lambda x: x["id"]),
        "scanned_nodes": scanned,
        "scope": f"since:{since}" if since and touched is not None else "full",
        "stale_threshold_days": stale_days,
        "warnings": warnings,
    }

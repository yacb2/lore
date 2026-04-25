"""Compute the diff between code and graph.

`compute_sync_report` answers the question reconcile cannot: *given a
range of git history, which changed files are already represented in
the graph and which introduce candidates for new nodes?* Both the
PostToolUse `git commit` checkpoint hook and the `/lore:sync` slash
command consume this report.

The logic intentionally mirrors `lifecycle.reconcile`: read-only,
filesystem-bounded, never writes. Persistence happens upstream after
the user reviews the dossier.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any

BORING_SUFFIXES: tuple[str, ...] = (
    ".css", ".scss", ".sass", ".less",
    ".md", ".rst", ".txt",
    ".lock", ".png", ".jpg", ".jpeg", ".svg", ".ico", ".gif",
)
BORING_NAMES: frozenset[str] = frozenset({
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
    "uv.lock", "Cargo.lock", "go.sum",
})


def is_boring(path: str) -> bool:
    """Heuristic: files unlikely to introduce business knowledge worth a node."""
    name = path.rsplit("/", 1)[-1]
    if name in BORING_NAMES:
        return True
    return path.endswith(BORING_SUFFIXES)


def find_git_repos(root: Path, max_depth: int = 2) -> list[Path]:
    """Return git repo roots at or below `root`.

    A workspace may hold several sibling repos (split-repo), or `root`
    itself may be the repo. Limit depth so we don't recurse into deep
    trees. Hidden directories (`.git`, `.lore`, etc.) are skipped.
    """
    found: list[Path] = []
    if (root / ".git").exists():
        found.append(root)
    if max_depth > 0 and root.exists():
        for child in root.iterdir():
            if child.is_dir() and not child.name.startswith("."):
                found.extend(find_git_repos(child, max_depth - 1))
    return found


def _changed_files(repo: Path, since: str | None) -> tuple[str, list[str]] | None:
    """Return (label, files) for the change set since the given revision.

    - `since=None` → just the HEAD commit (last commit only).
    - `since="HEAD~5"` etc. → range diff.

    Returns None on git failure or empty diff.
    """
    try:
        if since is None:
            label = subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, check=True, timeout=5,
            ).stdout.strip()
            files_raw = subprocess.run(
                ["git", "-C", str(repo), "diff-tree", "--no-commit-id",
                 "--name-only", "-r", "HEAD"],
                capture_output=True, text=True, check=True, timeout=5,
            ).stdout
        else:
            label = f"{since}..HEAD"
            files_raw = subprocess.run(
                ["git", "-C", str(repo), "diff", "--name-only", since, "HEAD"],
                capture_output=True, text=True, check=True, timeout=10,
            ).stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        return None
    files = [f for f in files_raw.splitlines() if f.strip()]
    return (label, files) if files else None


def _load_source_ref_index(
    conn: sqlite3.Connection,
) -> dict[str, list[dict[str, str]]]:
    """Index nodes by `metadata.source_ref` (path part only).

    Returns ``{path: [{id, type, title}, ...]}``. Multiple nodes can map
    to the same path; the consumer decides which is most relevant.
    """
    rows = conn.execute(
        "SELECT id, type, title, metadata_json FROM nodes "
        "WHERE metadata_json LIKE '%\"source_ref\"%'"
    ).fetchall()
    index: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        try:
            meta = json.loads(row["metadata_json"] or "{}")
        except json.JSONDecodeError:
            continue
        ref = (meta.get("source_ref") or "").split(":", 1)[0].strip()
        if ref:
            index.setdefault(ref, []).append({
                "id": row["id"],
                "type": row["type"],
                "title": row["title"],
            })
    return index


def compute_sync_report(
    conn: sqlite3.Connection,
    root: Path,
    *,
    since: str | None = None,
    include_boring: bool = False,
) -> dict[str, Any]:
    """Build a sync dossier comparing code changes against graph nodes.

    Parameters
    ----------
    conn
        Open Lore database connection.
    root
        Workspace or repo root. The function discovers git repos under
        it and aggregates results.
    since
        Optional git revision. ``None`` means "last commit only" (the
        commit-checkpoint use case). Any other value (``"HEAD~10"``,
        ``"v2.24.0"``, a sha) means "range diff from `since` to HEAD".
    include_boring
        When True, do not filter lockfiles, CSS, images, docs.

    Returns a dict with this shape::

        {
          "scope": "HEAD" | "<since>..HEAD",
          "repos": [
            {
              "repo": "backend",                      # relative to root
              "label": "abc123" | "HEAD~10..HEAD",
              "mapped": [
                {"path": "...", "nodes": [{id,type,title}, ...]}
              ],
              "unmapped": ["path1", "path2", ...],
              "boring_skipped": int,
            },
            ...
          ],
          "totals": {"mapped": int, "unmapped": int, "boring_skipped": int},
          "warnings": [str, ...],
        }
    """
    warnings: list[str] = []
    repos = find_git_repos(root)
    if not repos:
        warnings.append(f"no git repositories found under {root}")
        return {
            "scope": since or "HEAD",
            "repos": [],
            "totals": {"mapped": 0, "unmapped": 0, "boring_skipped": 0},
            "warnings": warnings,
        }

    ref_index = _load_source_ref_index(conn)
    repo_reports: list[dict[str, Any]] = []
    total_mapped = total_unmapped = total_boring = 0

    for repo in repos:
        info = _changed_files(repo, since)
        if not info:
            continue
        label, files = info
        rel = "." if repo == root else str(repo.relative_to(root))
        mapped: list[dict[str, Any]] = []
        unmapped: list[str] = []
        boring_skipped = 0
        for f in files:
            if not include_boring and is_boring(f):
                boring_skipped += 1
                continue
            hit = ref_index.get(f)
            if hit:
                mapped.append({"path": f, "nodes": hit})
            else:
                unmapped.append(f)
        if not mapped and not unmapped and boring_skipped == 0:
            continue
        repo_reports.append({
            "repo": rel,
            "label": label,
            "mapped": mapped,
            "unmapped": unmapped,
            "boring_skipped": boring_skipped,
        })
        total_mapped += len(mapped)
        total_unmapped += len(unmapped)
        total_boring += boring_skipped

    return {
        "scope": (since + "..HEAD") if since else "HEAD",
        "repos": repo_reports,
        "totals": {
            "mapped": total_mapped,
            "unmapped": total_unmapped,
            "boring_skipped": total_boring,
        },
        "warnings": warnings,
    }

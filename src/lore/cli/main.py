"""Lore CLI — Typer-based interface for inspecting the graph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer

from lore.export import export_markdown as _export_markdown
from datetime import datetime, timezone

from lore.graph import (
    audit as _audit,
)
from lore.graph import (
    update_node as _update_node,
)
from lore.graph.queries import FINDING_KEYS
from lore.lifecycle import reconcile as _reconcile
from lore.graph import (
    find_variants as _find_variants,
)
from lore.graph import (
    get_node,
    list_edges,
    list_nodes,
    open_db,
    query,
)
from lore.graph import (
    stats as _stats,
)

DEFAULT_DB = Path(".lore") / "lore.db"

app = typer.Typer(
    help="Lore — programmatic knowledge graph for your project.",
    no_args_is_help=True,
    add_completion=False,
)


DBOption = Annotated[
    Path,
    typer.Option("--db", help="Path to the Lore SQLite database."),
]


def _require_db(db: Path) -> None:
    """Exit with a clear error if the DB file does not exist.

    Prevents read-only commands from silently creating a fresh DB at the
    given path — which would both surprise the user and give false-negative
    "empty graph" results.
    """
    if not db.exists():
        typer.echo(
            f"No Lore database at {db}. Run `lore init --db {db}` to create one.",
            err=True,
        )
        raise typer.Exit(code=1)


@app.command()
def init(db: DBOption = DEFAULT_DB) -> None:
    """Create an empty Lore database at the given path."""
    if db.exists():
        typer.echo(f"Database already exists at {db}")
        raise typer.Exit(code=1)
    open_db(db).close()
    typer.echo(f"Initialized Lore database at {db}")


@app.command(name="list")
def list_cmd(
    db: DBOption = DEFAULT_DB,
    type: Annotated[str | None, typer.Option(help="Filter by node type.")] = None,
    status: Annotated[str | None, typer.Option(help="Filter by status.")] = None,
    tag: Annotated[str | None, typer.Option(help="Filter by metadata tag.")] = None,
) -> None:
    """List nodes in the graph."""
    _require_db(db)
    conn = open_db(db)
    nodes = list_nodes(conn, type=type, status=status, tag=tag)
    if not nodes:
        typer.echo("(no nodes)")
        return
    for n in nodes:
        typer.echo(f"{n['type']:>12}  {n['id']:<40}  {n['title']}")


@app.command()
def show(
    node_id: str,
    db: DBOption = DEFAULT_DB,
) -> None:
    """Show a single node and its direct relationships."""
    _require_db(db)
    conn = open_db(db)
    node = get_node(conn, node_id)
    if node is None:
        typer.echo(f"Node {node_id!r} not found", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"# {node['title']}  [{node['type']}]")
    typer.echo(f"id: {node['id']}")
    typer.echo(f"status: {node['status']}")
    if node.get("metadata"):
        typer.echo(f"metadata: {json.dumps(node['metadata'])}")
    if node.get("body"):
        typer.echo("")
        typer.echo(node["body"])
    outgoing = list_edges(conn, from_id=node_id)
    incoming = list_edges(conn, to_id=node_id)
    if outgoing:
        typer.echo("\n-- outgoing --")
        for e in outgoing:
            typer.echo(f"  --{e['relation']}--> {e['to_id']}")
    if incoming:
        typer.echo("\n-- incoming --")
        for e in incoming:
            typer.echo(f"  {e['from_id']} --{e['relation']}-->")


@app.command(name="query")
def query_cmd(
    text: str,
    db: DBOption = DEFAULT_DB,
    depth: Annotated[int, typer.Option(help="Neighborhood depth.")] = 1,
) -> None:
    """Flexible search: exact id, title substring, or tag."""
    _require_db(db)
    conn = open_db(db)
    result = query(conn, text, depth=depth)
    if not result["nodes"]:
        typer.echo("(no matches)")
        return
    typer.echo(f"-- {len(result['nodes'])} nodes --")
    for n in result["nodes"]:
        typer.echo(f"  {n['type']:>12}  {n['id']:<40}  {n['title']}")
    if result["edges"]:
        typer.echo(f"\n-- {len(result['edges'])} edges --")
        for e in result["edges"]:
            typer.echo(f"  {e['from_id']} --{e['relation']}--> {e['to_id']}")


@app.command()
def variants(
    capability_id: str,
    db: DBOption = DEFAULT_DB,
) -> None:
    """List all flows that implement the given capability."""
    _require_db(db)
    conn = open_db(db)
    results = _find_variants(conn, capability_id)
    if not results:
        typer.echo(f"(no flows implement {capability_id!r})")
        return
    for n in results:
        typer.echo(f"  {n['id']:<40}  {n['title']}")


@app.command()
def audit(
    db: DBOption = DEFAULT_DB,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the full report as JSON."),
    ] = False,
) -> None:
    """Structural checks + graph summary: counts, orphans, cycles, id hygiene."""
    _require_db(db)
    conn = open_db(db)
    report = _audit(conn)

    if json_output:
        typer.echo(json.dumps(report, indent=2, sort_keys=True))
        return

    typer.echo(
        f"-- summary --\n"
        f"  nodes: {report['nodes_total']}  "
        f"edges: {report['edges_total']}  "
        f"last_mutation: {report['last_mutation_at'] or '-'}"
    )
    if report["nodes_by_type"]:
        parts = ", ".join(f"{k}={v}" for k, v in report["nodes_by_type"].items())
        typer.echo(f"  by type:     {parts}")
    if report["nodes_by_status"]:
        parts = ", ".join(f"{k}={v}" for k, v in report["nodes_by_status"].items())
        typer.echo(f"  by status:   {parts}")
    if report["edges_by_relation"]:
        parts = ", ".join(f"{k}={v}" for k, v in report["edges_by_relation"].items())
        typer.echo(f"  by relation: {parts}")

    any_finding = False
    for key in FINDING_KEYS:
        items = report.get(key) or []
        if items:
            any_finding = True
            typer.echo(f"\n-- {key} ({len(items)}) --")
            for it in items:
                typer.echo(f"  {it}")
    if not any_finding:
        typer.echo("\nOK — no findings")


@app.command()
def export(
    out: Annotated[Path, typer.Option("--out", help="Output directory.")] = Path(
        ".lore/export"
    ),
    db: DBOption = DEFAULT_DB,
) -> None:
    """Export the graph as one markdown file per node."""
    _require_db(db)
    conn = open_db(db)
    written = _export_markdown(conn, out)
    typer.echo(f"Wrote {len(written)} files under {out}")


@app.command()
def verify(
    node_id: str,
    db: DBOption = DEFAULT_DB,
) -> None:
    """Mark a node as verified today — updates metadata.last_verified_at.

    Convenience wrapper around `lore_update_node(metadata_patch=…)`.
    Keeps `reconcile`'s staleness signal useful without having to
    remember the metadata shape each time.
    """
    from lore.graph.schema import SchemaError

    _require_db(db)
    conn = open_db(db)
    today = datetime.now(timezone.utc).date().isoformat()
    try:
        _update_node(
            conn, node_id, metadata_patch={"last_verified_at": today}
        )
    except SchemaError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Verified {node_id} (last_verified_at={today})")


@app.command()
def reconcile(
    db: DBOption = DEFAULT_DB,
    since: Annotated[
        str | None,
        typer.Option("--since", help="Git rev — restrict scan to files changed since."),
    ] = None,
    stale_days: Annotated[
        int,
        typer.Option("--stale-days", help="Days threshold for `stale` findings."),
    ] = 90,
    root: Annotated[
        Path | None,
        typer.Option(
            "--root",
            help="Project root used to resolve source_ref. Defaults to the DB's parent's parent (i.e. the dir that contains .lore/).",
        ),
    ] = None,
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit the full report as JSON."),
    ] = False,
    quiet: Annotated[
        bool,
        typer.Option(
            "--quiet",
            help="Suppress output on clean scans. Exit 0 if no drift, 1 otherwise. Useful for hooks.",
        ),
    ] = False,
) -> None:
    """Detect drift between the code and the graph. Read-only.

    Reports three categories: `dead_refs` (source_ref points at a file that
    no longer exists), `stale` (last_verified_at older than --stale-days),
    `never_verified` (has source_ref but no last_verified_at).
    """
    _require_db(db)
    resolved_root = root or db.resolve().parent.parent
    conn = open_db(db)
    report = _reconcile(
        conn, resolved_root, since=since, stale_days=stale_days
    )
    # Drift = actionable findings. `planned` is informational (draft
    # nodes whose code hasn't landed yet), not drift — never affects
    # exit code.
    drift = (
        len(report["dead_refs"])
        + len(report["stale"])
        + len(report["never_verified"])
    )

    if json_output:
        typer.echo(json.dumps(report, indent=2, sort_keys=True))
        raise typer.Exit(code=1 if drift else 0)

    if quiet:
        if drift == 0:
            raise typer.Exit(code=0)
        typer.echo(
            f"drift: dead={len(report['dead_refs'])} "
            f"stale={len(report['stale'])} "
            f"never_verified={len(report['never_verified'])}"
        )
        raise typer.Exit(code=1)

    typer.echo(
        f"-- reconcile ({report['scope']}, scanned {report['scanned_nodes']} "
        f"nodes with source_ref) --"
    )
    for w in report["warnings"]:
        typer.echo(f"  warning: {w}")

    if drift == 0 and not report["planned"]:
        typer.echo("OK — no drift")
        return

    for category in ("dead_refs", "stale", "never_verified", "planned"):
        items = report[category]
        if not items:
            continue
        label = category if category != "planned" else "planned (draft nodes — code not yet landed)"
        typer.echo(f"\n-- {label} ({len(items)}) --")
        for it in items:
            typer.echo(f"  {it}")

    if drift == 0:
        typer.echo("\nOK — no drift (planned nodes reported as informational)")
        return
    raise typer.Exit(code=1)


POST_COMMIT_TEMPLATE = """\
#!/bin/sh
# Installed by `lore install-hooks`. Runs Lore reconcile against the
# commit's delta and prints a one-line drift summary if anything changed.
# Non-blocking: failures never abort a commit.

DB="{db_path}"
if ! command -v lore >/dev/null 2>&1; then
    exit 0
fi
lore reconcile --db "$DB" --since HEAD~1 --quiet 2>&1 || true
"""


@app.command(name="hook-session-start")
def hook_session_start(
    db: DBOption = DEFAULT_DB,
) -> None:
    """Emit JSON for a Claude Code SessionStart hook.

    Injects `additionalContext` that Claude picks up at session start.
    Three states:

    - No `.lore/` directory at all → suggest running `/lore:init` if
      this looks like a codebase.
    - `.lore/lore.db` exists but is empty → suggest `/lore:init` to
      seed modules.
    - `.lore/lore.db` exists with nodes → run reconcile; if drift,
      surface a nudge.
    """
    # Use a fresh payload each time — the runtime consumes this on stdout.
    out: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "",
        }
    }

    # Heuristic: is the cwd a codebase? Look for common project markers
    # so we only nudge users in places where Lore makes sense.
    looks_like_project = any(
        (db.parent.parent / marker).exists()
        for marker in (
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "go.mod",
            "Gemfile",
            ".git",
        )
    ) or any(
        any((child / marker).exists() for marker in ("package.json", "pyproject.toml"))
        for child in (db.parent.parent.iterdir() if db.parent.parent.exists() else [])
        if child.is_dir() and not child.name.startswith(".")
    )

    if not db.exists():
        if looks_like_project:
            out["hookSpecificOutput"]["additionalContext"] = (
                "The Lore plugin is installed and this directory looks like "
                "a project, but no Lore graph exists yet. Suggest to the "
                "user that they run `/lore:init` to set up a knowledge "
                "graph for this project. Do not run it yourself — let the "
                "user decide."
            )
        typer.echo(json.dumps(out))
        return

    # DB exists — open it and check.
    try:
        conn = open_db(db)
        node_count = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
    except Exception:
        typer.echo(json.dumps(out))
        return

    if node_count == 0:
        out["hookSpecificOutput"]["additionalContext"] = (
            "Lore graph is empty for this project. Suggest to the user "
            "that they run `/lore:init` to seed top-level modules."
        )
        typer.echo(json.dumps(out))
        return

    # Graph has content — run a cheap reconcile and surface drift summary.
    root = db.resolve().parent.parent
    report = _reconcile(conn, root)
    drift = (
        len(report["dead_refs"])
        + len(report["stale"])
        + len(report["never_verified"])
    )
    if drift > 0:
        out["hookSpecificOutput"]["additionalContext"] = (
            f"Lore reconcile at session start detected drift: "
            f"{len(report['dead_refs'])} dead refs, "
            f"{len(report['stale'])} stale, "
            f"{len(report['never_verified'])} never verified. "
            f"If the user touches any affected area, mention it and "
            f"suggest running `/lore:reconcile` to review details."
        )
    typer.echo(json.dumps(out))


@app.command(name="install-hooks")
def install_hooks(
    repo: Annotated[
        Path,
        typer.Option(
            "--repo",
            help="Git repository where the post-commit hook should be installed.",
        ),
    ],
    db: DBOption = DEFAULT_DB,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Overwrite an existing post-commit hook. Without this flag, refuses to clobber.",
        ),
    ] = False,
) -> None:
    """Install a git post-commit hook that runs `lore reconcile` on the commit.

    Workspace note: if you maintain a single Lore graph at the workspace
    root and have several repos under it, run this command once per repo,
    passing the same `--db` each time.
    """
    repo = repo.resolve()
    git_dir = repo / ".git"
    if not git_dir.exists():
        typer.echo(f"{repo} is not a git repository (no .git/)", err=True)
        raise typer.Exit(code=1)
    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    target = hooks_dir / "post-commit"

    if target.exists() and not force:
        typer.echo(
            f"{target} already exists. Use --force to overwrite, or edit it manually.",
            err=True,
        )
        raise typer.Exit(code=1)

    db_resolved = db.resolve()
    _require_db(db_resolved)
    target.write_text(
        POST_COMMIT_TEMPLATE.format(db_path=db_resolved), encoding="utf-8"
    )
    target.chmod(0o755)
    typer.echo(
        f"Installed post-commit hook at {target} (reconciles against {db_resolved})"
    )


@app.command()
def mcp(db: DBOption = DEFAULT_DB) -> None:
    """Run the Lore MCP server over stdio."""
    from lore.mcp.server import run

    run(db)


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} {unit}"
        n = n / 1024  # type: ignore[assignment]
    return f"{n:.1f} TB"


@app.command()
def stats(
    db: DBOption = DEFAULT_DB,
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="ISO timestamp — only count calls at or after this time.",
        ),
    ] = None,
) -> None:
    """Show token/byte usage analytics for this project's Lore MCP.

    Reports total calls, bytes exchanged, per-tool breakdown, and error
    rate. Token count is not directly measurable from the MCP server, so
    `bytes_exchanged` is the honest proxy — multiply by ~0.3 for a rough
    token estimate."""
    _require_db(db)
    conn = open_db(db)
    data = _stats(conn, since=since)
    if data["calls"] == 0:
        scope = f" since {since}" if since else ""
        typer.echo(f"(no tool calls recorded{scope})")
        return

    # Rough byte→token conversion. See `lore stats --help` for why this is
    # a proxy, not a measurement. UTF-8 text / JSON bounces around 3–4
    # bytes per token; 0.3 is conservative and enough for relative
    # comparisons between tools / time periods.
    def _tokens(b: int) -> str:
        return f"~{int(b * 0.3):,}".replace(",", ".")

    typer.echo(f"-- Lore usage ({data['first_call_at']} → {data['last_call_at']}) --")
    typer.echo(f"  calls:   {data['calls']}")
    typer.echo(f"  errors:  {data['errors']}")
    typer.echo(
        f"  input:   {_format_bytes(data['input_bytes']):>10}  "
        f"({_tokens(data['input_bytes'])} tokens)"
    )
    typer.echo(
        f"  output:  {_format_bytes(data['output_bytes']):>10}  "
        f"({_tokens(data['output_bytes'])} tokens)"
    )
    typer.echo(
        f"  total:   {_format_bytes(data['total_bytes']):>10}  "
        f"({_tokens(data['total_bytes'])} tokens)"
    )

    typer.echo("\n-- by tool --")
    for row in data["by_tool"]:
        total = row["input_bytes"] + row["output_bytes"]
        typer.echo(
            f"  {row['tool']:<24} {row['calls']:>5} calls  "
            f"{_format_bytes(total):>10}  ({_tokens(total)} tokens)"
        )

    typer.echo("\n-- by op --")
    for row in data["by_op"]:
        typer.echo(f"  {row['op']:<16} {row['calls']:>5}")


if __name__ == "__main__":
    app()

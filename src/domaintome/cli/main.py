"""DomainTome CLI — Typer-based interface for inspecting the graph."""

from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from domaintome.export import export_markdown as _export_markdown
from domaintome.graph import (
    audit as _audit,
)
from domaintome.graph import (
    find_variants as _find_variants,
)
from domaintome.graph import (
    get_node,
    list_edges,
    list_nodes,
    open_db,
    query,
)
from domaintome.graph import (
    stats as _stats,
)
from domaintome.graph import (
    update_node as _update_node,
)
from domaintome.graph.quality import (
    errors_breakdown as _errors_breakdown,
)
from domaintome.graph.quality import (
    quality_report as _quality_report,
)
from domaintome.graph.quality import (
    stats_by_day as _stats_by_day,
)
from domaintome.graph.queries import FINDING_KEYS
from domaintome.lifecycle import reconcile as _reconcile
from domaintome.sync import (
    compute_sync_report as _compute_sync_report,
)
from domaintome.sync import (
    is_boring,
    load_source_ref_index,
)

_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}

# Diff-content signals that suggest a code change introduces business
# behavior worth a graph node (new endpoint, model, signal, rule, etc.).
# Patterns are deliberately framework-level — a new private helper does
# not match. False positives are cheap (Claude reads the diff and skips
# the persist call); false negatives are equivalent to today's baseline.
_BUSINESS_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(async\s+)?def\s+\w+\s*\(", re.MULTILINE),
    re.compile(r"^\s*class\s+\w+", re.MULTILINE),
    re.compile(
        r"@(receiver|api_view|action|shared_task|login_required|"
        r"require_\w+|app\.(route|get|post|put|delete|patch)|"
        r"router\.(get|post|put|delete|patch))\b"
    ),
    re.compile(r"\burlpatterns\b"),
    re.compile(r"\bpath\(\s*[\"']"),
    re.compile(r"\bmodels\.\w+Field\("),
    re.compile(r"\bvalidate_\w+\s*\("),
    re.compile(r"\bsignals?\.\w+\.connect\("),
    re.compile(r"\b(export\s+)?(async\s+)?function\s+\w+"),
    re.compile(r"\b(export\s+)?const\s+\w+\s*=\s*(async\s+)?\("),
    re.compile(r"\b(defineStore|defineProps|defineEmits)\("),
    re.compile(r"\b(useRouter|useStore|createRouter)\("),
)

_TEST_PATH = re.compile(
    r"(^|/)tests?/|\.test\.|\.spec\.|(^|/)test_\w+\.py$|_test\.py$"
)

DEFAULT_DB = Path(".dt") / "graph.db"

app = typer.Typer(
    help="DomainTome — programmatic knowledge graph for your project.",
    no_args_is_help=True,
    add_completion=False,
)


DBOption = Annotated[
    Path,
    typer.Option("--db", help="Path to the DomainTome SQLite database."),
]


def _require_db(db: Path) -> None:
    """Exit with a clear error if the DB file does not exist.

    Prevents read-only commands from silently creating a fresh DB at the
    given path — which would both surprise the user and give false-negative
    "empty graph" results.
    """
    if not db.exists():
        typer.echo(
            f"No DomainTome database at {db}. Run `dt init --db {db}` to create one.",
            err=True,
        )
        raise typer.Exit(code=1)


@app.command()
def init(db: DBOption = DEFAULT_DB) -> None:
    """Create an empty DomainTome database at the given path."""
    if db.exists():
        typer.echo(f"Database already exists at {db}")
        raise typer.Exit(code=1)
    open_db(db).close()
    typer.echo(f"Initialized DomainTome database at {db}")


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
        ".dt/export"
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

    Convenience wrapper around `dt_update_node(metadata_patch=…)`.
    Keeps `reconcile`'s staleness signal useful without having to
    remember the metadata shape each time.
    """
    from domaintome.graph.schema import SchemaError

    _require_db(db)
    conn = open_db(db)
    today = datetime.now(UTC).date().isoformat()
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
            help=(
                "Project root used to resolve source_ref. Defaults to the "
                "DB's parent's parent (i.e. the dir that contains .dt/)."
            ),
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
            help=(
                "Suppress output on clean scans. Exit 0 if no drift, "
                "1 otherwise. Useful for hooks."
            ),
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
# Installed by `dt install-hooks`. Runs DomainTome reconcile against the
# commit's delta and prints a one-line drift summary if anything changed.
# Non-blocking: failures never abort a commit.

DB="{db_path}"
if ! command -v dt >/dev/null 2>&1; then
    exit 0
fi
dt reconcile --db "$DB" --since HEAD~1 --quiet 2>&1 || true
"""


@app.command(name="hook-session-start")
def hook_session_start(
    db: DBOption = DEFAULT_DB,
) -> None:
    """Emit JSON for a Claude Code SessionStart hook.

    Injects `additionalContext` that Claude picks up at session start.
    Three states:

    - No `.dt/` directory at all → suggest running `/dt:init` if
      this looks like a codebase.
    - `.dt/graph.db` exists but is empty → suggest `/dt:init` to
      seed modules.
    - `.dt/graph.db` exists with nodes → run reconcile; if drift,
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
    # so we only nudge users in places where DomainTome makes sense.
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
                "The DomainTome plugin is installed and this directory looks like "
                "a project, but no DomainTome graph exists yet. Suggest to the "
                "user that they run `/dt:init` to set up a knowledge "
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
            "DomainTome graph is empty for this project. Suggest to the user "
            "that they run `/dt:init` to seed top-level modules."
        )
        typer.echo(json.dumps(out))
        return

    # Graph has content — always inject an operating directive so the
    # `dt-usage` skill stays top of mind for the whole session, then
    # append a drift summary if reconcile finds anything.
    root = db.resolve().parent.parent
    report = _reconcile(conn, root)
    drift = (
        len(report["dead_refs"])
        + len(report["stale"])
        + len(report["never_verified"])
    )
    parts = [
        f"This project has a DomainTome knowledge graph at `{db}` with "
        f"{node_count} nodes. The DomainTome MCP server (`dt_*` tools) and "
        f"the `dt-usage` skill are available.",
        "Operating rules for this session:",
        "1. Before answering questions about how something works in this "
        "project, query the graph first with `dt_query`/`dt_list`/"
        "`dt_get_node`. Cite node ids when you use them.",
        "2. After editing code that introduces or changes business "
        "behavior — new endpoints, models, commands, signals, events, "
        "rules, forms, modules, decisions, or supersedes relations — "
        "persist the change with `dt_add_node`/`dt_add_edge`/"
        "`dt_update_node`. Always set `metadata.source`, "
        "`metadata.confidence`, and `metadata.source_ref` (path:line).",
        "3. Skip persistence only for pure refactors with no behavior "
        "change, dependency bumps, CSS-only changes, and exploratory "
        "talk.",
        "4. If a `git commit` happens during the session, treat it as a "
        "checkpoint: confirm the changed files have been reflected in "
        "the graph before moving on.",
        "Read the `dt-usage` skill for full conventions (provenance, "
        "soft-delete, relation pairs, naming).",
    ]
    if drift > 0:
        parts.append(
            f"Reconcile at session start detected drift: "
            f"{len(report['dead_refs'])} dead refs, "
            f"{len(report['stale'])} stale, "
            f"{len(report['never_verified'])} never verified. "
            f"If the user touches any affected area, mention it and "
            f"suggest running `/dt:reconcile`."
        )
    out["hookSpecificOutput"]["additionalContext"] = "\n".join(parts)
    typer.echo(json.dumps(out))


def _format_sync_blocks(report: dict[str, Any], *, max_lines: int) -> list[str]:
    """Render a sync report as human-readable blocks for hook nudges."""
    blocks: list[str] = []
    for repo in report.get("repos", []):
        block = [f"Commit {repo['label']} in `{repo['repo']}` touched:"]
        if repo["mapped"]:
            block.append(
                "Files already mapped to graph nodes — review whether "
                "the change updates them:"
            )
            for entry in repo["mapped"][:max_lines]:
                ids = ", ".join(f"`{n['id']}`" for n in entry["nodes"][:3])
                block.append(f"  - {entry['path']} → {ids}")
            extra = len(repo["mapped"]) - max_lines
            if extra > 0:
                block.append(f"  - …and {extra} more mapped files")
        if repo["unmapped"]:
            block.append(
                "Unmapped files — if any introduces a new flow, "
                "capability, rule, command, model, signal, event, form, "
                "or decision, persist it now via `dt_add_node`/"
                "`dt_add_edge` with `metadata.source_ref`:"
            )
            for f in repo["unmapped"][:max_lines]:
                block.append(f"  - {f}")
            extra = len(repo["unmapped"]) - max_lines
            if extra > 0:
                block.append(f"  - …and {extra} more unmapped files")
        if len(block) > 1:
            blocks.append("\n".join(block))
    return blocks


def _match_edit_path_to_nodes(
    ref_index: dict[str, list[dict[str, str]]],
    abs_path: str,
) -> list[dict[str, str]]:
    """Return nodes whose source_ref path is a suffix of abs_path.

    Source refs in the wild are stored relative to repo or workspace root
    (e.g. ``backend/apps/x/views.py`` or ``apps/x/views.py``); the absolute
    path coming from an Edit/Write tool is canonical. Suffix matching makes
    the lookup robust to either convention without forcing one.
    """
    if not abs_path:
        return []
    norm = abs_path.replace("\\", "/")
    matches: list[dict[str, str]] = []
    seen: set[str] = set()
    for key, nodes in ref_index.items():
        if not key:
            continue
        if norm == key or norm.endswith("/" + key):
            for n in nodes:
                if n["id"] not in seen:
                    seen.add(n["id"])
                    matches.append(n)
    return matches


def _edit_target_path(tool_name: str, tool_input: dict[str, Any]) -> str:
    if tool_name == "NotebookEdit":
        return tool_input.get("notebook_path", "") or ""
    return tool_input.get("file_path", "") or ""


def _edit_old_new_text(
    tool_name: str, tool_input: dict[str, Any]
) -> tuple[str, str]:
    """Pull old/new text out of the heterogeneous Edit-family tool inputs."""
    if tool_name == "Edit":
        return (
            tool_input.get("old_string", "") or "",
            tool_input.get("new_string", "") or "",
        )
    if tool_name == "Write":
        return ("", tool_input.get("content", "") or "")
    if tool_name == "MultiEdit":
        edits = tool_input.get("edits") or []
        old = "\n".join((e.get("old_string", "") or "") for e in edits)
        new = "\n".join((e.get("new_string", "") or "") for e in edits)
        return old, new
    if tool_name == "NotebookEdit":
        return (
            tool_input.get("old_source", "") or "",
            tool_input.get("new_source", "") or "",
        )
    return "", ""


def _classify_edit_diff(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Cheap inference of whether an edit introduces business behavior.

    Returns ``"business"`` if the new text adds at least one occurrence of
    a framework-level signal (route decorator, model field, signal hook,
    new function/class, store, etc.) that is not already in the old text.
    Returns ``"boring"`` for paths that are structurally not business
    (lockfiles, css, docs, tests). Returns ``"unknown"`` otherwise.
    """
    path = _edit_target_path(tool_name, tool_input)
    if not path:
        return "unknown"
    norm = path.replace("\\", "/")
    if is_boring(norm) or _TEST_PATH.search(norm):
        return "boring"
    old, new = _edit_old_new_text(tool_name, tool_input)
    for pattern in _BUSINESS_PATTERNS:
        if len(pattern.findall(new)) > len(pattern.findall(old)):
            return "business"
    return "unknown"


@app.command(name="hook-post-tool-use")
def hook_post_tool_use(
    db: DBOption = DEFAULT_DB,
) -> None:
    """Emit JSON for a Claude Code PostToolUse hook.

    Reads the hook payload on stdin. Two responsibilities:

    - On a successful ``git commit`` (``Bash`` tool), list the files in
      the resulting HEAD commit and nudge the model to reflect them in
      the DomainTome graph.
    - On ``Edit``/``Write``/``MultiEdit``/``NotebookEdit``, look up the
      affected file path against ``metadata.source_ref`` of every node
      and, when there is a match, nudge the model to verify or update
      the linked nodes before moving on.

    Stays silent for everything else, when the graph is missing or empty,
    or when the edit path matches no node.
    """
    out: dict[str, Any] = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": "",
        }
    }

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        typer.echo(json.dumps(out))
        return

    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}

    if tool_name == "Bash":
        if "git commit" not in tool_input.get("command", ""):
            typer.echo(json.dumps(out))
            return
    elif tool_name in _EDIT_TOOLS:
        if not _edit_target_path(tool_name, tool_input):
            typer.echo(json.dumps(out))
            return
    else:
        typer.echo(json.dumps(out))
        return

    # Bail out early if the graph isn't set up yet.
    if not db.exists():
        typer.echo(json.dumps(out))
        return
    try:
        conn = open_db(db)
        node_count = conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()["c"]
    except Exception:
        typer.echo(json.dumps(out))
        return
    if node_count == 0:
        typer.echo(json.dumps(out))
        return

    if tool_name == "Bash":
        report = _compute_sync_report(conn, Path.cwd())
        blocks = _format_sync_blocks(report, max_lines=15)
        if blocks:
            intro = (
                "DomainTome checkpoint after `git commit`. The graph is the "
                "project's living memory; reflect substantive changes "
                "before moving on."
            )
            out["hookSpecificOutput"]["additionalContext"] = (
                intro + "\n\n" + "\n\n".join(blocks)
            )
    else:
        path = _edit_target_path(tool_name, tool_input)
        ref_index = load_source_ref_index(conn)
        nodes = _match_edit_path_to_nodes(ref_index, path)
        if nodes:
            ids = ", ".join(f"`{n['id']}`" for n in nodes[:5])
            extra = f" (+{len(nodes) - 5} more)" if len(nodes) > 5 else ""
            out["hookSpecificOutput"]["additionalContext"] = (
                f"DomainTome: you just edited `{path}` — linked nodes: "
                f"{ids}{extra}. If business behavior changed, update them "
                f"via `dt_update_node` (or `dt_add_node`/"
                f"`dt_add_edge` for new behavior) before moving on."
            )
        elif _classify_edit_diff(tool_name, tool_input) == "business":
            out["hookSpecificOutput"]["additionalContext"] = (
                f"DomainTome: you edited `{path}` and the diff looks like new "
                f"behavior (new function, class, route, model field, "
                f"signal, or store). If this introduces a new endpoint, "
                f"model, signal, rule, flow, form, or decision, persist "
                f"it now via `dt_add_node`/`dt_add_edge` with "
                f"`metadata.source_ref` pointing at this file."
            )
    typer.echo(json.dumps(out))


@app.command(name="sync-plan")
def sync_plan(
    since: Annotated[
        str | None,
        typer.Option(
            "--since",
            help="Git revision to diff against HEAD (e.g. HEAD~10, v2.24.0, a sha). "
                 "Default scans only the most recent commit.",
        ),
    ] = None,
    db: DBOption = DEFAULT_DB,
    include_boring: Annotated[
        bool,
        typer.Option(
            "--include-boring",
            help="Do not filter lockfiles, CSS, images, docs.",
        ),
    ] = False,
) -> None:
    """Emit a JSON dossier of changed files vs graph nodes.

    Compares the changed files in `since..HEAD` (or just HEAD when
    `--since` is omitted) against `metadata.source_ref` on every node,
    and reports `mapped` (files whose path appears in some node) vs
    `unmapped` (candidates for new nodes). Read-only.

    Designed to be consumed by `/dt:sync`. Exit code is 0 on success
    and 1 if there are unmapped files (so it can be used in scripts).
    """
    _require_db(db)
    conn = open_db(db)
    report = _compute_sync_report(
        conn, Path.cwd(), since=since, include_boring=include_boring
    )
    typer.echo(json.dumps(report, indent=2))
    if report["totals"]["unmapped"] > 0:
        raise typer.Exit(code=1)


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
    """Install a git post-commit hook that runs `dt reconcile` on the commit.

    Workspace note: if you maintain a single DomainTome graph at the workspace
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
    """Run the DomainTome MCP server over stdio."""
    from domaintome.mcp.server import run

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
    by_day: Annotated[
        bool,
        typer.Option(
            "--by-day",
            help="Print a per-day breakdown of calls, errors and warnings.",
        ),
    ] = False,
    errors: Annotated[
        bool,
        typer.Option(
            "--errors",
            help="Print top error messages with counts and last-seen.",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON instead of pretty text."),
    ] = False,
) -> None:
    """Show token/byte usage analytics for this project's DomainTome MCP.

    Reports total calls, bytes exchanged, per-tool breakdown, and error
    rate. Token count is not directly measurable from the MCP server, so
    `bytes_exchanged` is the honest proxy — multiply by ~0.3 for a rough
    token estimate."""
    _require_db(db)
    conn = open_db(db)
    data = _stats(conn, since=since)
    extra: dict[str, Any] = {}
    if by_day:
        extra["by_day"] = _stats_by_day(conn, since=since)
    if errors:
        extra["errors"] = _errors_breakdown(conn, since=since)
    if json_out:
        typer.echo(json.dumps({**data, **extra}, indent=2))
        return
    if data["calls"] == 0:
        scope = f" since {since}" if since else ""
        typer.echo(f"(no tool calls recorded{scope})")
        return

    # Rough byte→token conversion. See `dt stats --help` for why this is
    # a proxy, not a measurement. UTF-8 text / JSON bounces around 3–4
    # bytes per token; 0.3 is conservative and enough for relative
    # comparisons between tools / time periods.
    def _tokens(b: int) -> str:
        return f"~{int(b * 0.3):,}".replace(",", ".")

    typer.echo(f"-- DomainTome usage ({data['first_call_at']} → {data['last_call_at']}) --")
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

    if "by_day" in extra:
        typer.echo("\n-- by day --")
        typer.echo(f"  {'day':<10}  {'calls':>6}  {'errors':>6}  {'warns':>6}  {'bytes':>10}")
        for row in extra["by_day"]:
            typer.echo(
                f"  {row['day']:<10}  {row['calls']:>6}  {row['errors']:>6}  "
                f"{row['warnings']:>6}  {_format_bytes(row['bytes']):>10}"
            )

    if "errors" in extra:
        typer.echo("\n-- top errors --")
        if not extra["errors"]:
            typer.echo("  (none)")
        for row in extra["errors"]:
            typer.echo(f"  [{row['n']:>3}× {row['tool']}] {row['error']}")
            typer.echo(
                f"        first: {row['first_seen']}   last: {row['last_seen']}"
            )


@app.command()
def quality(
    db: DBOption = DEFAULT_DB,
    json_out: Annotated[
        bool, typer.Option("--json", help="Emit JSON instead of pretty text.")
    ] = False,
) -> None:
    """Content-quality report: provenance coverage, body coverage,
    orphans by type, top schema errors, warnings distribution.

    Complements `dt audit` (structural integrity) by inspecting how good
    the *content* of the graph is. Run after a few days of activity to see
    where the LLM keeps slipping (missing source, thin bodies, isolated
    rules/decisions, repeated relation rejections)."""
    _require_db(db)
    conn = open_db(db)
    rep = _quality_report(conn)
    if json_out:
        typer.echo(json.dumps(rep, indent=2))
        return

    total = rep["node_total"]
    typer.echo(f"-- DomainTome quality — {total} nodes --\n")

    typer.echo("-- coverage by type --")
    typer.echo(f"  {'type':<12}  {'total':>6}  {'body':>6}  {'src':>6}  {'ref':>6}")
    for ntype, c in sorted(rep["by_type"].items()):
        t = c["total"] or 1
        typer.echo(
            f"  {ntype:<12}  {c['total']:>6}  "
            f"{c['with_body']*100//t:>5}%  "
            f"{c['with_source']*100//t:>5}%  "
            f"{c['with_ref']*100//t:>5}%"
        )

    if rep["body_thin"]:
        typer.echo(f"\n-- thin body ({len(rep['body_thin'])} nodes) --")
        for n in rep["body_thin"][:10]:
            typer.echo(f"  {n['type']:<12}  {n['id']:<40}  body={n['body_len']} chars")
        if len(rep["body_thin"]) > 10:
            typer.echo(f"  … +{len(rep['body_thin']) - 10} more")

    if rep["missing_source"]:
        typer.echo(f"\n-- missing metadata.source ({len(rep['missing_source'])}) --")
        for nid in rep["missing_source"][:10]:
            typer.echo(f"  {nid}")
        if len(rep["missing_source"]) > 10:
            typer.echo(f"  … +{len(rep['missing_source']) - 10} more")

    if rep["non_canonical_source"]:
        typer.echo("\n-- non-canonical metadata.source --")
        for src, n in sorted(
            rep["non_canonical_source"].items(), key=lambda x: -x[1]
        ):
            typer.echo(f"  {n:>4}  {src}")

    typer.echo("\n-- orphans by type --")
    if not rep["orphans_by_type"]:
        typer.echo("  (none)")
    for t, n in sorted(rep["orphans_by_type"].items(), key=lambda x: -x[1]):
        typer.echo(f"  {n:>4}  {t}")

    if rep["top_errors"]:
        typer.echo("\n-- top schema errors --")
        for e in rep["top_errors"][:5]:
            short = e["error"][:120]
            typer.echo(f"  {e['count']:>4}× {short}")

    if rep["warnings_by_tool"]:
        typer.echo("\n-- warnings by tool --")
        for w in rep["warnings_by_tool"]:
            typer.echo(
                f"  {w['tool']:<24} {w['warnings']:>5} warnings over "
                f"{w['calls']} calls"
            )


if __name__ == "__main__":
    app()

"""Lore CLI — Typer-based interface for inspecting the graph."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from lore.export import export_markdown as _export_markdown
from lore.graph import (
    audit as _audit,
)
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
    conn = open_db(db)
    results = _find_variants(conn, capability_id)
    if not results:
        typer.echo(f"(no flows implement {capability_id!r})")
        return
    for n in results:
        typer.echo(f"  {n['id']:<40}  {n['title']}")


@app.command()
def audit(db: DBOption = DEFAULT_DB) -> None:
    """Structural checks: orphans, dangling edges, id hygiene, cycles."""
    conn = open_db(db)
    report = _audit(conn)
    any_finding = False
    for key, items in report.items():
        if items:
            any_finding = True
            typer.echo(f"\n-- {key} ({len(items)}) --")
            for it in items:
                typer.echo(f"  {it}")
    if not any_finding:
        typer.echo("OK — no findings")


@app.command()
def export(
    out: Annotated[Path, typer.Option("--out", help="Output directory.")] = Path(
        ".lore/export"
    ),
    db: DBOption = DEFAULT_DB,
) -> None:
    """Export the graph as one markdown file per node."""
    conn = open_db(db)
    written = _export_markdown(conn, out)
    typer.echo(f"Wrote {len(written)} files under {out}")


@app.command()
def mcp(db: DBOption = DEFAULT_DB) -> None:
    """Run the Lore MCP server over stdio."""
    from lore.mcp.server import run

    run(db)


@app.command(name="install-claude")
def install_claude(
    target: Annotated[
        Path,
        typer.Option(
            "--target",
            help="Root directory where .claude/ should live (defaults to CWD).",
        ),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", help="Overwrite existing command/skill files."),
    ] = False,
) -> None:
    """Install Lore slash commands, skill, and CLAUDE.md snippet into a project.

    Copies templates into `<target>/.claude/commands/lore/`,
    `<target>/.claude/skills/`, and appends the integration snippet to
    `<target>/CLAUDE.md` (creating it if missing).
    """
    from lore.templates import install

    report = install(target, force=force)
    for line in report:
        typer.echo(line)


if __name__ == "__main__":
    app()

"""Bootstrap a DomainTome graph that models DomainTome itself — used for dogfooding.

Run:

    uv run python examples/dogfood_lore.py

Creates `.dt/graph.db` at the repo root and populates it with nodes describing
the architecture of the `domaintome` package (modules, capabilities, flows, entities,
rules, decisions).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from domaintome.graph import add_edge, add_node, open_db

DB_PATH = Path(".dt") / "graph.db"


def _reset_db(path: Path) -> None:
    if path.exists():
        path.unlink()
    # Also remove any -journal/-wal sibling files
    for suffix in ("-journal", "-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    if (path.parent / "export").exists():
        shutil.rmtree(path.parent / "export")


def seed(db_path: Path = DB_PATH) -> None:
    _reset_db(db_path)
    conn = open_db(db_path)

    # ------------------------------------------------------------------
    # Modules (top-level structural grouping)
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="graph-engine",
        type="module",
        title="Graph engine",
        body="SQLite-backed CRUD and query layer for nodes and edges.",
    )
    add_node(
        conn,
        node_id="cli-module",
        type="module",
        title="CLI",
        body="Typer-based command-line interface for humans inspecting the graph.",
    )
    add_node(
        conn,
        node_id="mcp-server",
        type="module",
        title="MCP server",
        body="FastMCP server exposing the graph tools to LLM clients over stdio.",
    )
    add_node(
        conn,
        node_id="export-module",
        type="module",
        title="Markdown export",
        body="Regenerable markdown view of the graph for PR review.",
    )

    # ------------------------------------------------------------------
    # Capabilities (what the system knows how to do)
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="store-knowledge-graph",
        type="capability",
        title="Store a typed knowledge graph locally",
    )
    add_node(
        conn,
        node_id="query-graph",
        type="capability",
        title="Query the graph flexibly",
    )
    add_node(
        conn,
        node_id="expose-to-llm",
        type="capability",
        title="Expose graph tools to an LLM",
    )
    add_node(
        conn,
        node_id="inspect-by-human",
        type="capability",
        title="Inspect the graph from the shell",
    )
    add_node(
        conn,
        node_id="export-graph",
        type="capability",
        title="Export the graph to a reviewable format",
    )

    # ------------------------------------------------------------------
    # Flows (concrete ways of implementing capabilities)
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="init-database-flow",
        type="flow",
        title="Initialize an empty DomainTome database",
        body="Create .dt/graph.db, apply the schema, enable foreign keys.",
    )
    add_node(
        conn,
        node_id="add-node-flow",
        type="flow",
        title="Add a node via the graph API",
        body="Validate id, type and status; insert with timestamps.",
    )
    add_node(
        conn,
        node_id="add-edge-flow",
        type="flow",
        title="Add an edge with schema validation",
        body="Verify both nodes exist and the (relation, from_type, to_type) "
        "triple is allowed.",
    )
    add_node(
        conn,
        node_id="query-by-id-or-title-flow",
        type="flow",
        title="Query by id, title substring or tag",
        body="Resolve text → exact id match, fuzzy title match, then tag match. "
        "Expand neighborhood up to `depth` and return nodes + edges.",
    )
    add_node(
        conn,
        node_id="traverse-flow",
        type="flow",
        title="Traverse the graph by following relations",
        body="BFS from a start node, optionally filtering which relations to follow.",
    )
    add_node(
        conn,
        node_id="find-variants-flow",
        type="flow",
        title="Find all flows that implement a capability",
        body="Answers the central PRD question: how many ways of doing X?",
    )
    add_node(
        conn,
        node_id="audit-flow",
        type="flow",
        title="Audit graph structure",
        body="Detect orphans, dangling edges, invalid ids, generic ids, "
        "unknown types and supersedes cycles.",
    )
    add_node(
        conn,
        node_id="export-markdown-flow",
        type="flow",
        title="Export the graph as one markdown file per node",
        body="Regenerable view with YAML frontmatter grouping outgoing edges "
        "by relation.",
    )
    add_node(
        conn,
        node_id="mcp-stdio-flow",
        type="flow",
        title="Serve graph tools over MCP stdio",
        body="Build a FastMCP server with 12 tools, share one SQLite connection.",
    )
    add_node(
        conn,
        node_id="cli-inspect-flow",
        type="flow",
        title="Inspect the graph from the CLI",
        body="Subcommands: init, list, show, query, variants, audit, export, mcp.",
    )

    # ------------------------------------------------------------------
    # Events (automatic happenings)
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="node-created",
        type="event",
        title="node.created",
        body="Fired logically when a node is inserted (not yet wired in code).",
    )
    add_node(
        conn,
        node_id="edge-created",
        type="event",
        title="edge.created",
        body="Fired logically when an edge is inserted.",
    )
    add_node(
        conn,
        node_id="audit-failed",
        type="event",
        title="audit.failed",
        body="Fired when `dt audit` finds structural issues.",
    )

    # ------------------------------------------------------------------
    # Forms (validation surfaces)
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="add-node-tool-form",
        type="form",
        title="dt_add_node MCP tool input",
        body="Validates id, type, title, status, metadata from an LLM call.",
    )
    add_node(
        conn,
        node_id="add-edge-tool-form",
        type="form",
        title="dt_add_edge MCP tool input",
        body="Validates (from_id, to_id, relation) from an LLM call.",
    )

    # ------------------------------------------------------------------
    # Deprecated flow (exercises Q14)
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="query-by-id-only-flow-v0",
        type="flow",
        title="Query by exact id only (v0)",
        body="Early version superseded by query-by-id-or-title-flow.",
        status="superseded",
    )

    # ------------------------------------------------------------------
    # Entities (domain concepts)
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="node-entity",
        type="entity",
        title="Node",
        body="Row in the `nodes` table: id, type, title, body, status, metadata.",
    )
    add_node(
        conn,
        node_id="edge-entity",
        type="entity",
        title="Edge",
        body="Row in the `edges` table: (from_id, to_id, relation) PK.",
    )

    # ------------------------------------------------------------------
    # Rules (invariants)
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="id-must-be-kebab-case",
        type="rule",
        title="Node ids must be kebab-case",
        body="Lowercase, digits, hyphens; no leading/trailing or double hyphen.",
    )
    add_node(
        conn,
        node_id="edge-types-must-match-schema",
        type="rule",
        title="Edges must use a whitelisted (relation, from_type, to_type) triple",
        body="Enforced by domaintome.graph.schema.ALLOWED_RELATIONS at write time.",
    )
    add_node(
        conn,
        node_id="generic-ids-should-be-prefixed",
        type="rule",
        title="Generic ids should be prefixed with a module",
        body="Soft rule: audit warns on ids like `overview`, `create`, `list`.",
    )
    add_node(
        conn,
        node_id="no-supersedes-cycles",
        type="rule",
        title="`supersedes` must not form a cycle",
        body="Enforced retrospectively by audit (not at write time).",
    )

    # ------------------------------------------------------------------
    # Decisions
    # ------------------------------------------------------------------
    add_node(
        conn,
        node_id="sqlite-over-kuzu",
        type="decision",
        title="Use SQLite instead of an embedded graph DB",
        body="Kùzu was archived Oct 2025. Oxigraph is RDF (wrong shape). SQLite "
        "is stdlib, inspectable, and sufficient at <5k nodes. Migration path "
        "stays mechanical if the schema ever outgrows CTEs.",
    )
    add_node(
        conn,
        node_id="kebab-case-flat-ids",
        type="decision",
        title="Flat kebab-case ids without module namespace",
        body="Simpler to type, no parsing ambiguity against the `type:id` "
        "notation used in docs. Generic names should be prefixed by convention; "
        "audit flags the obvious ones.",
    )
    add_node(
        conn,
        node_id="fastmcp-over-low-level",
        type="decision",
        title="Use FastMCP instead of the low-level MCP Server",
        body="Tools map directly to Python functions with type hints, no manual "
        "JSON schema wiring.",
    )
    add_node(
        conn,
        node_id="typer-over-click",
        type="decision",
        title="Typer over Click for the CLI",
        body="Type hints drive the CLI, matching the style of the rest of the "
        "codebase and MCP tools.",
    )

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    # part_of: flow/capability/form/event → module
    # (capabilities/flows inside the relevant module)
    for fid in (
        "init-database-flow",
        "add-node-flow",
        "add-edge-flow",
        "query-by-id-or-title-flow",
        "traverse-flow",
        "find-variants-flow",
        "audit-flow",
    ):
        add_edge(conn, from_id=fid, to_id="graph-engine", relation="part_of")
    add_edge(conn, from_id="cli-inspect-flow", to_id="cli-module", relation="part_of")
    add_edge(conn, from_id="mcp-stdio-flow", to_id="mcp-server", relation="part_of")
    add_edge(
        conn, from_id="export-markdown-flow", to_id="export-module", relation="part_of"
    )
    add_edge(
        conn, from_id="store-knowledge-graph", to_id="graph-engine", relation="part_of"
    )
    add_edge(conn, from_id="query-graph", to_id="graph-engine", relation="part_of")
    add_edge(conn, from_id="expose-to-llm", to_id="mcp-server", relation="part_of")
    add_edge(conn, from_id="inspect-by-human", to_id="cli-module", relation="part_of")
    add_edge(conn, from_id="export-graph", to_id="export-module", relation="part_of")

    # implements: flow → capability
    add_edge(
        conn,
        from_id="init-database-flow",
        to_id="store-knowledge-graph",
        relation="implements",
    )
    add_edge(
        conn,
        from_id="add-node-flow",
        to_id="store-knowledge-graph",
        relation="implements",
    )
    add_edge(
        conn,
        from_id="add-edge-flow",
        to_id="store-knowledge-graph",
        relation="implements",
    )
    # three flows implement query-graph → variants answer
    add_edge(
        conn,
        from_id="query-by-id-or-title-flow",
        to_id="query-graph",
        relation="implements",
    )
    add_edge(
        conn, from_id="traverse-flow", to_id="query-graph", relation="implements"
    )
    add_edge(
        conn, from_id="find-variants-flow", to_id="query-graph", relation="implements"
    )
    add_edge(
        conn, from_id="audit-flow", to_id="query-graph", relation="implements"
    )
    add_edge(
        conn,
        from_id="mcp-stdio-flow",
        to_id="expose-to-llm",
        relation="implements",
    )
    add_edge(
        conn,
        from_id="cli-inspect-flow",
        to_id="inspect-by-human",
        relation="implements",
    )
    add_edge(
        conn,
        from_id="export-markdown-flow",
        to_id="export-graph",
        relation="implements",
    )

    # part_of: events & forms live in modules
    for eid in ("node-created", "edge-created"):
        add_edge(conn, from_id=eid, to_id="graph-engine", relation="part_of")
    add_edge(conn, from_id="audit-failed", to_id="graph-engine", relation="part_of")
    add_edge(
        conn, from_id="add-node-tool-form", to_id="mcp-server", relation="part_of"
    )
    add_edge(
        conn, from_id="add-edge-tool-form", to_id="mcp-server", relation="part_of"
    )
    add_edge(
        conn, from_id="query-by-id-only-flow-v0", to_id="graph-engine", relation="part_of"
    )

    # triggers: flow → event / event → flow
    add_edge(
        conn, from_id="add-node-flow", to_id="node-created", relation="triggers"
    )
    add_edge(
        conn, from_id="add-edge-flow", to_id="edge-created", relation="triggers"
    )
    add_edge(
        conn, from_id="audit-flow", to_id="audit-failed", relation="triggers"
    )

    # validates: form → rule
    add_edge(
        conn,
        from_id="add-node-tool-form",
        to_id="id-must-be-kebab-case",
        relation="validates",
    )
    add_edge(
        conn,
        from_id="add-edge-tool-form",
        to_id="edge-types-must-match-schema",
        relation="validates",
    )

    # supersedes: new flow obsoletes the v0
    add_edge(
        conn,
        from_id="query-by-id-or-title-flow",
        to_id="query-by-id-only-flow-v0",
        relation="supersedes",
    )
    # The flow that implemented query-graph v0 — add implements for realism
    add_edge(
        conn,
        from_id="query-by-id-only-flow-v0",
        to_id="query-graph",
        relation="implements",
    )

    # depends_on: module/flow → module/flow
    add_edge(
        conn, from_id="cli-module", to_id="graph-engine", relation="depends_on"
    )
    add_edge(
        conn, from_id="mcp-server", to_id="graph-engine", relation="depends_on"
    )
    add_edge(
        conn, from_id="export-module", to_id="graph-engine", relation="depends_on"
    )
    add_edge(
        conn,
        from_id="add-edge-flow",
        to_id="add-node-flow",
        relation="depends_on",
    )

    # enforces: rule → entity
    add_edge(
        conn, from_id="id-must-be-kebab-case", to_id="node-entity", relation="enforces"
    )
    add_edge(
        conn,
        from_id="edge-types-must-match-schema",
        to_id="edge-entity",
        relation="enforces",
    )
    add_edge(
        conn,
        from_id="generic-ids-should-be-prefixed",
        to_id="node-entity",
        relation="enforces",
    )
    add_edge(
        conn,
        from_id="no-supersedes-cycles",
        to_id="edge-entity",
        relation="enforces",
    )

    # references: various → decision
    add_edge(
        conn, from_id="graph-engine", to_id="sqlite-over-kuzu", relation="references"
    )
    add_edge(
        conn,
        from_id="id-must-be-kebab-case",
        to_id="kebab-case-flat-ids",
        relation="references",
    )
    add_edge(
        conn,
        from_id="mcp-stdio-flow",
        to_id="fastmcp-over-low-level",
        relation="references",
    )
    add_edge(
        conn,
        from_id="cli-inspect-flow",
        to_id="typer-over-click",
        relation="references",
    )

    conn.close()
    print(f"Seeded {db_path}")


if __name__ == "__main__":
    seed()

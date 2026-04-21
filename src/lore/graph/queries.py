"""Higher-level queries over the graph: search, traversal, audit."""

from __future__ import annotations

import sqlite3
from typing import Any

from lore.graph._common import placeholders as _ph
from lore.graph._common import row_to_dict
from lore.graph.nodes import get_node
from lore.graph.schema import GENERIC_ID_WORDS, NODE_TYPES, is_valid_id

CYCLE_RELATIONS: tuple[str, ...] = ("supersedes", "depends_on", "triggers")


def list_nodes(
    conn: sqlite3.Connection,
    *,
    type: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    summary_only: bool = False,
) -> list[dict[str, Any]]:
    """List nodes filtered by type, status, and/or a tag in metadata.tags.

    When `summary_only=True`, returns only id/type/title/status (drops body
    and metadata). Use this to cheaply scan large graphs; follow up with
    `get_node` for full detail."""
    clauses: list[str] = []
    values: list[Any] = []
    if type is not None:
        clauses.append("type = ?")
        values.append(type)
    if status is not None:
        clauses.append("status = ?")
        values.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    if summary_only and tag is None:
        rows = conn.execute(
            f"SELECT id, type, title, status FROM nodes {where} ORDER BY type, id",
            values,
        ).fetchall()
        return [dict(r) for r in rows]

    rows = conn.execute(
        f"SELECT * FROM nodes {where} ORDER BY type, id", values
    ).fetchall()
    nodes = [row_to_dict(r) for r in rows]
    if tag is not None:
        nodes = [n for n in nodes if tag in n.get("metadata", {}).get("tags", [])]
    if summary_only:
        nodes = [
            {k: n[k] for k in ("id", "type", "title", "status")} for n in nodes
        ]
    return nodes


def query(
    conn: sqlite3.Connection,
    text_or_id: str,
    *,
    depth: int = 1,
) -> dict[str, Any]:
    """Flexible search.

    Resolution order:
    1. Exact id match.
    2. Case-insensitive substring match on title.
    3. Tag match (metadata.tags contains text_or_id).

    Returns a dict with `nodes` (matched nodes + neighborhood up to `depth`) and
    `edges` (all edges within the returned node set).
    """
    matched = _resolve_query(conn, text_or_id)
    seen_ids: set[str] = {n["id"] for n in matched}
    frontier = list(seen_ids)
    all_nodes = {n["id"]: n for n in matched}

    for _ in range(max(depth, 0)):
        if not frontier:
            break
        ph = _ph(len(frontier))
        rows = conn.execute(
            f"""
            SELECT * FROM nodes WHERE id IN (
                SELECT to_id FROM edges WHERE from_id IN ({ph})
                UNION
                SELECT from_id FROM edges WHERE to_id IN ({ph})
            )
            """,
            frontier + frontier,
        ).fetchall()
        next_frontier: list[str] = []
        for r in rows:
            node = row_to_dict(r)
            if node["id"] not in seen_ids:
                seen_ids.add(node["id"])
                all_nodes[node["id"]] = node
                next_frontier.append(node["id"])
        frontier = next_frontier

    edges = _edges_within(conn, seen_ids)
    return {
        "nodes": sorted(all_nodes.values(), key=lambda n: (n["type"], n["id"])),
        "edges": edges,
    }


def _resolve_query(conn: sqlite3.Connection, text: str) -> list[dict[str, Any]]:
    exact = get_node(conn, text)
    if exact:
        return [exact]
    like = f"%{text}%"
    rows = conn.execute(
        "SELECT * FROM nodes WHERE LOWER(title) LIKE LOWER(?) ORDER BY type, id",
        (like,),
    ).fetchall()
    if rows:
        return [row_to_dict(r) for r in rows]
    # Tag fallback
    all_nodes = conn.execute("SELECT * FROM nodes").fetchall()
    matches: list[dict[str, Any]] = []
    for r in all_nodes:
        node = row_to_dict(r)
        if text in node.get("metadata", {}).get("tags", []):
            matches.append(node)
    return matches


def _edges_within(
    conn: sqlite3.Connection, node_ids: set[str]
) -> list[dict[str, Any]]:
    if not node_ids:
        return []
    ph = _ph(len(node_ids))
    ids = list(node_ids)
    rows = conn.execute(
        f"""
        SELECT * FROM edges
        WHERE from_id IN ({ph}) AND to_id IN ({ph})
        ORDER BY relation, from_id, to_id
        """,
        ids + ids,
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def traverse(
    conn: sqlite3.Connection,
    from_id: str,
    *,
    relations: list[str] | None = None,
    max_depth: int = 3,
) -> dict[str, Any]:
    """Walk the graph from `from_id` following edges whose relation is in
    `relations` (or any relation if None). Returns nodes and edges reached,
    including the starting node."""
    start = get_node(conn, from_id)
    if start is None:
        return {"nodes": [], "edges": []}

    seen_ids: set[str] = {from_id}
    all_nodes: dict[str, dict[str, Any]] = {from_id: start}
    collected_edges: list[dict[str, Any]] = []
    frontier = [from_id]

    for _ in range(max(max_depth, 0)):
        if not frontier:
            break
        edge_sql = f"SELECT * FROM edges WHERE from_id IN ({_ph(len(frontier))})"
        params: list[Any] = list(frontier)
        if relations:
            edge_sql += f" AND relation IN ({_ph(len(relations))})"
            params.extend(relations)
        edge_rows = conn.execute(edge_sql, params).fetchall()

        next_frontier: list[str] = []
        for e in edge_rows:
            edge = row_to_dict(e)
            collected_edges.append(edge)
            if edge["to_id"] not in seen_ids:
                seen_ids.add(edge["to_id"])
                node = get_node(conn, edge["to_id"])
                if node:
                    all_nodes[edge["to_id"]] = node
                    next_frontier.append(edge["to_id"])
        frontier = next_frontier

    return {
        "nodes": sorted(all_nodes.values(), key=lambda n: (n["type"], n["id"])),
        "edges": collected_edges,
    }


def find_variants(
    conn: sqlite3.Connection, capability_id: str
) -> list[dict[str, Any]]:
    """Return all flows that `implements` the given capability."""
    rows = conn.execute(
        """
        SELECT n.* FROM nodes n
        JOIN edges e ON e.from_id = n.id
        WHERE e.relation = 'implements' AND e.to_id = ?
        ORDER BY n.id
        """,
        (capability_id,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


def audit(conn: sqlite3.Connection) -> dict[str, Any]:
    """Run structural checks against the graph.

    Returns a dict with lists: `orphans`, `dangling_edges`, `invalid_ids`,
    `generic_ids`, `unknown_types`, and one `cycles_<relation>` key per
    entry in :data:`CYCLE_RELATIONS`.
    """
    findings: dict[str, list[Any]] = {
        "orphans": [],
        "dangling_edges": [],
        "invalid_ids": [],
        "generic_ids": [],
        "unknown_types": [],
    }
    for rel in CYCLE_RELATIONS:
        findings[f"cycles_{rel}"] = []

    all_nodes = conn.execute("SELECT id, type FROM nodes").fetchall()
    node_ids = {r["id"] for r in all_nodes}

    connected = {
        row["id"]
        for row in conn.execute(
            "SELECT from_id AS id FROM edges UNION SELECT to_id AS id FROM edges"
        ).fetchall()
    }
    findings["orphans"] = sorted(node_ids - connected)

    # FK cascade should prevent this; defensive scan catches legacy rows.
    for r in conn.execute("SELECT from_id, to_id, relation FROM edges").fetchall():
        if r["from_id"] not in node_ids or r["to_id"] not in node_ids:
            findings["dangling_edges"].append(dict(r))

    for r in all_nodes:
        nid = r["id"]
        if not is_valid_id(nid):
            findings["invalid_ids"].append(nid)
        if nid in GENERIC_ID_WORDS:
            findings["generic_ids"].append(nid)
        if r["type"] not in NODE_TYPES:
            findings["unknown_types"].append({"id": nid, "type": r["type"]})

    for rel in CYCLE_RELATIONS:
        findings[f"cycles_{rel}"] = _find_cycles(conn, rel)

    return findings


def _find_cycles(conn: sqlite3.Connection, relation: str) -> list[list[str]]:
    edges = conn.execute(
        "SELECT from_id, to_id FROM edges WHERE relation = ?", (relation,)
    ).fetchall()
    graph: dict[str, list[str]] = {}
    for e in edges:
        graph.setdefault(e["from_id"], []).append(e["to_id"])

    cycles: list[list[str]] = []
    visited: set[str] = set()
    on_stack: set[str] = set()
    # Iterative DFS: each stack frame holds (node, iterator over children).
    # Avoids Python recursion limits on deep chains (supersedes, depends_on).
    for start in list(graph.keys()):
        if start in visited:
            continue
        path: list[str] = []
        work: list[tuple[str, Any]] = [(start, iter(graph.get(start, [])))]
        visited.add(start)
        on_stack.add(start)
        path.append(start)
        while work:
            node, children = work[-1]
            nxt = next(children, None)
            if nxt is None:
                on_stack.discard(node)
                path.pop()
                work.pop()
                continue
            if nxt in on_stack:
                cycles.append(path[path.index(nxt):] + [nxt])
                continue
            if nxt in visited:
                continue
            visited.add(nxt)
            on_stack.add(nxt)
            path.append(nxt)
            work.append((nxt, iter(graph.get(nxt, []))))

    return cycles

"""Higher-level queries over the graph: search, traversal, audit."""

from __future__ import annotations

import sqlite3
from typing import Any

from domaintome.graph._common import placeholders as _ph
from domaintome.graph._common import row_to_dict
from domaintome.graph.nodes import get_node
from domaintome.graph.schema import GENERIC_ID_WORDS, NODE_TYPES, is_valid_id

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
    if tag is not None:
        clauses.append(
            "EXISTS (SELECT 1 FROM json_each("
            "json_extract(metadata_json, '$.tags')) WHERE value = ?)"
        )
        values.append(tag)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    if summary_only:
        rows = conn.execute(
            f"SELECT id, type, title, status FROM nodes {where} ORDER BY type, id",
            values,
        ).fetchall()
        return [dict(r) for r in rows]

    rows = conn.execute(
        f"SELECT * FROM nodes {where} ORDER BY type, id", values
    ).fetchall()
    return [row_to_dict(r) for r in rows]


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
        ph_f = _ph(len(frontier))
        seen_list = list(seen_ids)
        ph_s = _ph(len(seen_list))
        rows = conn.execute(
            f"""
            SELECT * FROM nodes WHERE id IN (
                SELECT to_id FROM edges WHERE from_id IN ({ph_f})
                UNION
                SELECT from_id FROM edges WHERE to_id IN ({ph_f})
            ) AND id NOT IN ({ph_s})
            """,
            frontier + frontier + seen_list,
        ).fetchall()
        next_frontier: list[str] = []
        for r in rows:
            node = row_to_dict(r)
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
    rows = conn.execute(
        """
        SELECT * FROM nodes
        WHERE EXISTS (
            SELECT 1 FROM json_each(json_extract(metadata_json, '$.tags'))
            WHERE value = ?
        )
        ORDER BY type, id
        """,
        (text,),
    ).fetchall()
    return [row_to_dict(r) for r in rows]


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

        new_ids: list[str] = []
        for e in edge_rows:
            edge = row_to_dict(e)
            collected_edges.append(edge)
            if edge["to_id"] not in seen_ids:
                seen_ids.add(edge["to_id"])
                new_ids.append(edge["to_id"])
        if new_ids:
            node_rows = conn.execute(
                f"SELECT * FROM nodes WHERE id IN ({_ph(len(new_ids))})",
                new_ids,
            ).fetchall()
            for r in node_rows:
                n = row_to_dict(r)
                all_nodes[n["id"]] = n
        frontier = new_ids

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


FINDING_KEYS: tuple[str, ...] = (
    "orphans",
    "dangling_edges",
    "invalid_ids",
    "generic_ids",
    "unknown_types",
    *(f"cycles_{r}" for r in CYCLE_RELATIONS),
)


def audit(conn: sqlite3.Connection) -> dict[str, Any]:
    """Run structural checks against the graph and summarize counts.

    Returns a flat dict combining:

    - Finding lists (see :data:`FINDING_KEYS`): `orphans`, `dangling_edges`,
      `invalid_ids`, `generic_ids`, `unknown_types`, and one
      `cycles_<relation>` per entry in :data:`CYCLE_RELATIONS`.
    - Counters for quick at-a-glance health: `nodes_total`, `edges_total`,
      `nodes_by_type`, `nodes_by_status`, `edges_by_relation`,
      `last_mutation_at`.
    """
    findings: dict[str, list[Any]] = {k: [] for k in FINDING_KEYS}

    all_nodes = conn.execute(
        "SELECT id, type, status FROM nodes"
    ).fetchall()
    node_ids = {r["id"] for r in all_nodes}

    connected = {
        row["id"]
        for row in conn.execute(
            "SELECT from_id AS id FROM edges UNION SELECT to_id AS id FROM edges"
        ).fetchall()
    }
    findings["orphans"] = sorted(node_ids - connected)

    all_edges = conn.execute(
        "SELECT from_id, to_id, relation FROM edges"
    ).fetchall()

    # FK cascade should prevent this; defensive scan catches legacy rows.
    for r in all_edges:
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

    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for r in all_nodes:
        by_type[r["type"]] = by_type.get(r["type"], 0) + 1
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1

    by_relation: dict[str, int] = {}
    for r in all_edges:
        by_relation[r["relation"]] = by_relation.get(r["relation"], 0) + 1

    last_mutation = conn.execute(
        "SELECT MAX(updated_at) AS t FROM nodes"
    ).fetchone()

    return {
        **findings,
        "nodes_total": len(all_nodes),
        "edges_total": len(all_edges),
        "nodes_by_type": dict(sorted(by_type.items())),
        "nodes_by_status": dict(sorted(by_status.items())),
        "edges_by_relation": dict(sorted(by_relation.items())),
        "last_mutation_at": last_mutation["t"] if last_mutation else None,
    }


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

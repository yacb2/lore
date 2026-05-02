"""Generate a realistic large graph for scale testing.

Shape: simulates a mid-size SaaS project with ~1000 nodes and ~5000 edges:
- 10 modules
- 40 capabilities (4 per module)
- 300 flows (variants — avg 7.5 per capability, with a long tail)
- 150 events
- 200 rules
- 80 forms
- 60 entities
- 50 decisions

Edges model realistic density: flows implement capabilities, trigger events,
live in modules; forms validate rules; rules enforce entities; flows depend
on each other across modules.

Also exercises:
- Deep trigger chain (20 flows linked head-to-tail via `triggers`)
- Wide fan-out (one capability with 100 implementing flows)
- Unicode + long body text

Run:

    uv run python examples/stress/build_large_graph.py

Writes .dt/stress.db (overwritten on each run).
"""

from __future__ import annotations

import random
import sqlite3
from pathlib import Path

from domaintome.graph import add_edge, add_node, open_db
from domaintome.graph.schema import ALLOWED_RELATIONS

DB_PATH = Path(".dt") / "stress.db"

random.seed(42)  # reproducible

LOREM_ES = (
    "El flujo valida la entrada contra las reglas del dominio, aplica las "
    "transformaciones necesarias y persiste el resultado en la base de datos. "
    "Incluye manejo de errores, idempotencia y notificación a los sistemas "
    "suscritos. 🚀 Casos de uso: creación, actualización, consulta. "
    "Diacríticos: áéíóú ñ ¿ ¡ — pruebas de unicode."
)


def _reset(path: Path) -> None:
    if path.exists():
        path.unlink()
    for suffix in ("-journal", "-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()


def _safe_add_edge(conn: sqlite3.Connection, **kwargs) -> bool:
    try:
        add_edge(conn, **kwargs)
        return True
    except Exception:
        return False


def build(db_path: Path = DB_PATH) -> dict:
    _reset(db_path)
    conn = open_db(db_path)

    counts = {
        "module": 10,
        "capability": 40,
        "flow": 300,
        "event": 150,
        "rule": 200,
        "form": 80,
        "entity": 60,
        "decision": 50,
    }

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------
    ids: dict[str, list[str]] = {t: [] for t in counts}

    for i in range(counts["module"]):
        nid = f"module-{i:02d}"
        add_node(conn, node_id=nid, type="module", title=f"Module {i:02d}")
        ids["module"].append(nid)

    for i in range(counts["capability"]):
        nid = f"cap-{i:03d}"
        add_node(
            conn,
            node_id=nid,
            type="capability",
            title=f"Capability {i:03d}",
            metadata={"tags": [f"domain-{i % 5}"]},
        )
        ids["capability"].append(nid)

    for i in range(counts["flow"]):
        nid = f"flow-{i:03d}"
        # Long-ish body to stress storage/export
        body = f"{LOREM_ES} Índice {i}. "
        add_node(
            conn,
            node_id=nid,
            type="flow",
            title=f"Flow {i:03d} — registrar acción",
            body=body,
            metadata={"tags": [f"domain-{i % 5}", f"team-{i % 7}"]},
        )
        ids["flow"].append(nid)

    for i in range(counts["event"]):
        nid = f"event-{i:03d}"
        add_node(conn, node_id=nid, type="event", title=f"event.emitted.{i:03d}")
        ids["event"].append(nid)

    for i in range(counts["rule"]):
        nid = f"rule-{i:03d}"
        add_node(conn, node_id=nid, type="rule", title=f"Rule {i:03d}")
        ids["rule"].append(nid)

    for i in range(counts["form"]):
        nid = f"form-{i:03d}"
        add_node(conn, node_id=nid, type="form", title=f"Form {i:03d}")
        ids["form"].append(nid)

    for i in range(counts["entity"]):
        nid = f"entity-{i:03d}"
        add_node(conn, node_id=nid, type="entity", title=f"Entity {i:03d}")
        ids["entity"].append(nid)

    for i in range(counts["decision"]):
        nid = f"decision-{i:03d}"
        add_node(conn, node_id=nid, type="decision", title=f"Decision {i:03d}")
        ids["decision"].append(nid)

    # ------------------------------------------------------------------
    # Edges (realistic density)
    # ------------------------------------------------------------------
    edges_added = 0

    # Capabilities part_of a module (distributed)
    for i, cid in enumerate(ids["capability"]):
        if _safe_add_edge(
            conn,
            from_id=cid,
            to_id=ids["module"][i % len(ids["module"])],
            relation="part_of",
        ):
            edges_added += 1

    # Flows part_of module + implements capability
    for i, fid in enumerate(ids["flow"]):
        if _safe_add_edge(
            conn,
            from_id=fid,
            to_id=ids["module"][i % len(ids["module"])],
            relation="part_of",
        ):
            edges_added += 1
        if _safe_add_edge(
            conn,
            from_id=fid,
            to_id=ids["capability"][i % len(ids["capability"])],
            relation="implements",
        ):
            edges_added += 1

    # Flows trigger random events (avg 1.5 per flow)
    for fid in ids["flow"]:
        for _ in range(random.choice([1, 1, 2, 2, 3])):
            if _safe_add_edge(
                conn,
                from_id=fid,
                to_id=random.choice(ids["event"]),
                relation="triggers",
            ):
                edges_added += 1

    # Events trigger other events (cascade)
    for eid in ids["event"][:100]:
        if random.random() < 0.3:
            target = random.choice(ids["event"])
            if target != eid:
                if _safe_add_edge(
                    conn, from_id=eid, to_id=target, relation="triggers"
                ):
                    edges_added += 1

    # Events part_of a module
    for i, eid in enumerate(ids["event"]):
        if _safe_add_edge(
            conn,
            from_id=eid,
            to_id=ids["module"][i % len(ids["module"])],
            relation="part_of",
        ):
            edges_added += 1

    # Forms validate rules (each form validates 2-4 rules)
    for fid in ids["form"]:
        for _ in range(random.randint(2, 4)):
            if _safe_add_edge(
                conn,
                from_id=fid,
                to_id=random.choice(ids["rule"]),
                relation="validates",
            ):
                edges_added += 1

    # Forms part_of module
    for i, fid in enumerate(ids["form"]):
        if _safe_add_edge(
            conn,
            from_id=fid,
            to_id=ids["module"][i % len(ids["module"])],
            relation="part_of",
        ):
            edges_added += 1

    # Rules enforce entities (each rule enforces 1 entity)
    for rid in ids["rule"]:
        if _safe_add_edge(
            conn,
            from_id=rid,
            to_id=random.choice(ids["entity"]),
            relation="enforces",
        ):
            edges_added += 1

    # Cross-module depends_on (modules depend on other modules)
    for mid in ids["module"]:
        for _ in range(random.randint(1, 3)):
            other = random.choice(ids["module"])
            if other != mid:
                if _safe_add_edge(
                    conn, from_id=mid, to_id=other, relation="depends_on"
                ):
                    edges_added += 1

    # Flow-to-flow depends_on
    for fid in random.sample(ids["flow"], 50):
        other = random.choice(ids["flow"])
        if other != fid:
            if _safe_add_edge(
                conn, from_id=fid, to_id=other, relation="depends_on"
            ):
                edges_added += 1

    # references: everything refs random decisions
    for src in ids["flow"][:80] + ids["rule"][:40] + ids["module"]:
        if _safe_add_edge(
            conn,
            from_id=src,
            to_id=random.choice(ids["decision"]),
            relation="references",
        ):
            edges_added += 1

    # ------------------------------------------------------------------
    # Stress structures
    # ------------------------------------------------------------------

    # Deep trigger chain: 20 flows linked head-to-tail
    chain_ids = [f"chain-flow-{i:02d}" for i in range(20)]
    for nid in chain_ids:
        add_node(conn, node_id=nid, type="flow", title=f"Chain step {nid}")
    for a, b in zip(chain_ids, chain_ids[1:]):
        if _safe_add_edge(conn, from_id=a, to_id=b, relation="triggers"):
            edges_added += 1

    # Wide fan-out: one capability with 100 variants
    add_node(
        conn,
        node_id="wide-cap",
        type="capability",
        title="Capability with 100 variants",
    )
    for i in range(100):
        nid = f"wide-flow-{i:03d}"
        add_node(conn, node_id=nid, type="flow", title=f"Wide variant {i:03d}")
        if _safe_add_edge(
            conn, from_id=nid, to_id="wide-cap", relation="implements"
        ):
            edges_added += 1

    conn.close()

    total_nodes = sum(counts.values()) + 20 + 100 + 1  # chain + wide + wide-cap
    return {
        "path": str(db_path),
        "nodes": total_nodes,
        "edges": edges_added,
        "allowed_triples": len(ALLOWED_RELATIONS),
    }


if __name__ == "__main__":
    stats = build()
    print(
        f"Built {stats['path']}: {stats['nodes']} nodes, {stats['edges']} edges, "
        f"{stats['allowed_triples']} allowed (relation, from_type, to_type) triples"
    )

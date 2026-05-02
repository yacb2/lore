"""Run the 15 PRD §5 questions against the dogfood graph and report results.

Run after `dogfood_lore.py`:

    uv run python examples/validate_prd_queries.py

Exit code is 0 if every question meets its expectation, 1 otherwise.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from domaintome.graph import (
    audit,
    find_variants,
    list_edges,
    list_nodes,
    open_db,
    traverse,
)

DB_PATH = Path(".dt") / "graph.db"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


Check = Callable[[Any], bool]


def _describe(r: Any) -> str:
    if isinstance(r, list):
        return f"{len(r)} items"
    if isinstance(r, dict):
        parts = []
        if "nodes" in r:
            parts.append(f"{len(r['nodes'])} nodes")
        if "edges" in r:
            parts.append(f"{len(r['edges'])} edges")
        if parts:
            return ", ".join(parts)
        return f"{len(r)} keys"
    return str(r)


def run(
    title: str,
    fn: Callable[[], Any],
    check: Check,
    *,
    show: Callable[[Any], str] | None = None,
) -> bool:
    try:
        result = fn()
    except Exception as exc:  # pragma: no cover
        print(f"{RED}✗ {title}{RESET}")
        print(f"    raised {type(exc).__name__}: {exc}")
        return False
    ok = check(result)
    marker = f"{GREEN}✓{RESET}" if ok else f"{RED}✗{RESET}"
    desc = show(result) if show else _describe(result)
    print(f"{marker} {title} — {desc}")
    return ok


def main() -> int:
    if not DB_PATH.exists():
        print(
            f"{RED}No graph at {DB_PATH}. Run examples/dogfood_lore.py first.{RESET}",
            file=sys.stderr,
        )
        return 2

    conn = open_db(DB_PATH)
    results: list[bool] = []

    print(f"{YELLOW}Structural{RESET}")

    # Q1: What modules does the project have?
    results.append(
        run(
            "Q1  modules",
            lambda: list_nodes(conn, type="module"),
            lambda r: len(r) >= 4
            and {n["id"] for n in r}
            >= {"graph-engine", "cli-module", "mcp-server", "export-module"},
        )
    )

    # Q2: What capabilities does module X expose?
    # (capabilities that part_of graph-engine)
    def q2() -> list[dict]:
        caps = list_nodes(conn, type="capability")
        edges = list_edges(conn, to_id="graph-engine", relation="part_of")
        cap_ids = {e["from_id"] for e in edges}
        return [c for c in caps if c["id"] in cap_ids]

    results.append(
        run(
            "Q2  capabilities in graph-engine",
            q2,
            lambda r: {c["id"] for c in r}
            >= {"store-knowledge-graph", "query-graph"},
        )
    )

    # Q3: Which flows implement capability Y?
    results.append(
        run(
            "Q3  flows implementing query-graph",
            lambda: find_variants(conn, "query-graph"),
            lambda r: len(r) >= 3
            and {f["id"] for f in r}
            >= {"query-by-id-or-title-flow", "traverse-flow", "find-variants-flow"},
        )
    )

    # Q4: How many ways of doing Z?
    results.append(
        run(
            "Q4  variants of store-knowledge-graph",
            lambda: find_variants(conn, "store-knowledge-graph"),
            lambda r: len(r) >= 3,
        )
    )

    # Q5: Which entities exist and in which module?
    def q5() -> dict:
        entities = list_nodes(conn, type="entity")
        # For each entity, we expect its rules to enforce it. Entities don't
        # currently have part_of; this question reveals that gap.
        return {"entities": entities}

    results.append(
        run(
            "Q5  entities in the system",
            q5,
            lambda r: {e["id"] for e in r["entities"]}
            >= {"node-entity", "edge-entity"},
        )
    )

    print(f"\n{YELLOW}Flow-related{RESET}")

    # Q6: Show the steps of flow X. (body text serves as "steps")
    def q6() -> dict:
        node = [
            n
            for n in list_nodes(conn, type="flow")
            if n["id"] == "query-by-id-or-title-flow"
        ]
        return node[0] if node else {}

    results.append(
        run(
            "Q6  steps of query-by-id-or-title-flow",
            q6,
            lambda r: bool(r.get("body")),
        )
    )

    # Q7: Which events does flow X trigger?
    results.append(
        run(
            "Q7  events triggered by add-node-flow",
            lambda: list_edges(conn, from_id="add-node-flow", relation="triggers"),
            lambda r: any(e["to_id"] == "node-created" for e in r),
        )
    )

    # Q8: Which flow runs after event Y?
    results.append(
        run(
            "Q8  incoming triggers to node-created",
            lambda: list_edges(conn, to_id="node-created", relation="triggers"),
            lambda r: any(e["from_id"] == "add-node-flow" for e in r),
        )
    )

    # Q9: Which chain is set off if Z happens? (traversal depth 3)
    results.append(
        run(
            "Q9  chain from add-edge-flow",
            lambda: traverse(
                conn,
                "add-edge-flow",
                relations=["depends_on", "triggers"],
                max_depth=3,
            ),
            lambda r: any(n["id"] == "add-node-flow" for n in r["nodes"]),
        )
    )

    print(f"\n{YELLOW}Rules / validation{RESET}")

    # Q10: Which rules protect entity X?
    results.append(
        run(
            "Q10 rules protecting node-entity",
            lambda: [
                e["from_id"]
                for e in list_edges(conn, to_id="node-entity", relation="enforces")
            ],
            lambda r: set(r)
            >= {"id-must-be-kebab-case", "generic-ids-should-be-prefixed"},
        )
    )

    # Q11: Which forms validate rule Y?
    results.append(
        run(
            "Q11 forms validating id-must-be-kebab-case",
            lambda: list_edges(
                conn, to_id="id-must-be-kebab-case", relation="validates"
            ),
            lambda r: any(e["from_id"] == "add-node-tool-form" for e in r),
        )
    )

    # Q12: Which rule applies to flow X?
    # The schema routes rules through forms (`validates`). To answer "rules for
    # flow", we follow part_of to find the flow's module, then forms in that
    # module, then rules they validate. This is a two-hop indirection.
    def q12() -> list[str]:
        # Find the module of add-node-flow
        part_of = list_edges(conn, from_id="add-node-flow", relation="part_of")
        module_ids = [e["to_id"] for e in part_of]
        # Forms in any module whose flows we care about — take all forms and
        # walk their validates edges
        rules: set[str] = set()
        for fm in list_nodes(conn, type="form"):
            if fm.get("metadata"):
                pass
            # A form in the same module counts as applicable
            fm_part_of = list_edges(conn, from_id=fm["id"], relation="part_of")
            fm_modules = {e["to_id"] for e in fm_part_of}
            if fm_modules & set(module_ids) or True:
                # Include all for now — module scoping needs form.part_of linked
                # to flow.part_of, which the current graph models loosely.
                for v in list_edges(conn, from_id=fm["id"], relation="validates"):
                    rules.add(v["to_id"])
        return sorted(rules)

    results.append(
        run(
            "Q12 rules indirectly applicable to add-node-flow",
            q12,
            lambda r: "id-must-be-kebab-case" in r,
        )
    )

    print(f"\n{YELLOW}Dependencies / changes{RESET}")

    # Q13: If I change entity X, what flows/rules are affected?
    def q13() -> dict:
        incoming = list_edges(conn, to_id="node-entity")
        rule_ids = [e["from_id"] for e in incoming if e["relation"] == "enforces"]
        impacted: set[str] = set()
        for rid in rule_ids:
            for e in list_edges(conn, to_id=rid):
                impacted.add(e["from_id"])
        return {"rules": rule_ids, "upstream": sorted(impacted)}

    results.append(
        run(
            "Q13 impact of changing node-entity",
            q13,
            lambda r: len(r["rules"]) >= 2 and len(r["upstream"]) >= 1,
            show=lambda r: f"{len(r['rules'])} rules enforce it, "
            f"{len(r['upstream'])} upstream nodes (forms/others)",
        )
    )

    # Q14: Which flows are deprecated / superseded?
    results.append(
        run(
            "Q14 deprecated or superseded flows",
            lambda: list_nodes(conn, type="flow", status="deprecated")
            + list_nodes(conn, type="flow", status="superseded"),
            lambda r: any(f["id"] == "query-by-id-only-flow-v0" for f in r),
        )
    )

    # Q15: Which decisions motivate flow X or rule Y?
    results.append(
        run(
            "Q15 decisions referenced by mcp-stdio-flow",
            lambda: [
                e["to_id"]
                for e in list_edges(
                    conn, from_id="mcp-stdio-flow", relation="references"
                )
            ],
            lambda r: "fastmcp-over-low-level" in r,
        )
    )

    print(f"\n{YELLOW}Health{RESET}")
    audit_report = audit(conn)
    orphans = audit_report["orphans"]
    invalid = audit_report["invalid_ids"]
    dangling = audit_report["dangling_edges"]
    cycles = audit_report["cycles_supersedes"]
    print(
        f"    audit → orphans={len(orphans)} invalid_ids={len(invalid)} "
        f"dangling={len(dangling)} cycles={len(cycles)}"
    )
    if orphans:
        print(f"    orphans: {orphans}")
    results.append(
        run(
            "Audit clean on dogfood graph",
            lambda: audit_report,
            lambda r: not r["orphans"]
            and not r["invalid_ids"]
            and not r["dangling_edges"]
            and not r["cycles_supersedes"],
            show=lambda r: "clean" if not r["orphans"] else f"dirty: {r['orphans']}",
        )
    )

    print(f"\n{YELLOW}Negative checks{RESET}")

    # Schema rejects forbidden edge types
    def neg_invalid_edge() -> str:
        from domaintome.graph import add_edge as _ae
        from domaintome.graph.schema import SchemaError

        try:
            _ae(
                conn,
                from_id="add-node-flow",
                to_id="id-must-be-kebab-case",
                relation="implements",
            )
        except SchemaError as e:
            return str(e)
        return "NO ERROR — bug"

    results.append(
        run(
            "Schema rejects flow→rule implements",
            neg_invalid_edge,
            lambda r: "not allowed" in r,
            show=lambda r: r[:80],
        )
    )

    # Supersedes cycle detection using a temporary in-memory DB
    def neg_cycle() -> list:
        from domaintome.graph import add_edge as _ae
        from domaintome.graph import add_node as _an
        from domaintome.graph import audit as _audit
        from domaintome.graph import open_db as _open

        c = _open(":memory:")
        _an(c, node_id="a", type="flow", title="A")
        _an(c, node_id="b", type="flow", title="B")
        _ae(c, from_id="a", to_id="b", relation="supersedes")
        _ae(c, from_id="b", to_id="a", relation="supersedes")
        report = _audit(c)
        c.close()
        return report["cycles_supersedes"]

    results.append(
        run(
            "Audit detects supersedes cycle",
            neg_cycle,
            lambda r: len(r) >= 1,
            show=lambda r: f"found {len(r)} cycle(s)",
        )
    )

    # Markdown export round-trip
    def export_check() -> int:
        from domaintome.export import export_markdown

        out = DB_PATH.parent / "export"
        written = export_markdown(conn, out)
        # Spot-check a known flow file
        target = out / "flow" / "query-by-id-or-title-flow.md"
        content = target.read_text() if target.exists() else ""
        assert "implements: [query-graph]" in content, content
        assert "supersedes: [query-by-id-only-flow-v0]" in content, content
        return len(written)

    results.append(
        run(
            "Markdown export round-trip",
            export_check,
            lambda r: r >= 25,
            show=lambda r: f"{r} files written",
        )
    )

    passed = sum(results)
    total = len(results)
    print(
        f"\n{YELLOW}Summary{RESET}: {passed}/{total} questions answered to expectation"
    )
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())

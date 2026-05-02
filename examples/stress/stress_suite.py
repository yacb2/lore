"""Stress & gap suite for DomainTome.

Three axes:
  1. Performance at scale (timing core queries on a 1k-node graph)
  2. Correctness edge cases (idempotency, cascades, cycles, unicode, …)
  3. Product gaps — questions a real team WOULD ask that DomainTome cannot answer
     cleanly today. Recorded as findings, not failures.

Run:

    uv run python examples/stress/build_large_graph.py
    uv run python examples/stress/stress_suite.py

Writes a human-readable report to stdout and saves the structured findings to
`.dt/stress_report.json`.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from domaintome.graph import (
    add_edge,
    add_node,
    audit,
    delete_node,
    find_variants,
    list_edges,
    list_nodes,
    open_db,
    query,
    traverse,
    update_node,
)
from domaintome.graph.schema import SchemaError

STRESS_DB = Path(".dt") / "stress.db"
REPORT_PATH = Path(".dt") / "stress_report.json"

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"


@dataclass
class Finding:
    category: str
    title: str
    status: str  # "ok" | "slow" | "bug" | "gap"
    detail: str
    metric_ms: float | None = None


@dataclass
class Report:
    perf: list[Finding] = field(default_factory=list)
    edge_cases: list[Finding] = field(default_factory=list)
    product_gaps: list[Finding] = field(default_factory=list)


def _time(fn: Callable[[], Any]) -> tuple[Any, float]:
    t0 = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - t0) * 1000


def _emit(report: Report, section: str, f: Finding) -> None:
    getattr(report, section).append(f)
    color = {"ok": GREEN, "slow": YELLOW, "bug": RED, "gap": CYAN}[f.status]
    marker = {"ok": "✓", "slow": "⚠", "bug": "✗", "gap": "◆"}[f.status]
    suffix = f" {DIM}({f.metric_ms:.1f}ms){RESET}" if f.metric_ms is not None else ""
    print(f"{color}{marker}{RESET} {f.title}{suffix}")
    if f.detail:
        print(f"   {DIM}{f.detail}{RESET}")


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------


def perf_suite(conn: sqlite3.Connection, report: Report) -> None:
    print(f"\n{YELLOW}▌ 1. PERFORMANCE AT SCALE{RESET} ({conn.execute('SELECT COUNT(*) FROM nodes').fetchone()[0]} nodes)")

    cases: list[tuple[str, Callable[[], Any], int]] = [
        ("list_nodes (all)", lambda: list_nodes(conn), 50),
        ("list_nodes by type=flow", lambda: list_nodes(conn, type="flow"), 30),
        ("list_nodes by tag=domain-0", lambda: list_nodes(conn, tag="domain-0"), 80),
        (
            "query by id (exact)",
            lambda: query(conn, "flow-042", depth=1),
            20,
        ),
        (
            "query by title substring",
            lambda: query(conn, "registrar", depth=0),
            150,
        ),
        (
            "query by title substring depth=2",
            lambda: query(conn, "registrar", depth=2),
            500,
        ),
        (
            "find_variants on wide-cap (100 flows)",
            lambda: find_variants(conn, "wide-cap"),
            30,
        ),
        (
            "traverse triggers max_depth=5 from flow-000",
            lambda: traverse(conn, "flow-000", relations=["triggers"], max_depth=5),
            100,
        ),
        (
            "traverse deep chain (max_depth=20)",
            lambda: traverse(
                conn, "chain-flow-00", relations=["triggers"], max_depth=25
            ),
            100,
        ),
        ("audit full graph", lambda: audit(conn), 300),
    ]

    for name, fn, budget_ms in cases:
        _, elapsed = _time(fn)
        status = "ok" if elapsed <= budget_ms else "slow"
        _emit(
            report,
            "perf",
            Finding(
                category="perf",
                title=name,
                status=status,
                detail=f"budget {budget_ms}ms",
                metric_ms=elapsed,
            ),
        )

    # Specific correctness at scale: did traverse reach chain tail?
    walk = traverse(
        conn, "chain-flow-00", relations=["triggers"], max_depth=25
    )
    reached = {n["id"] for n in walk["nodes"]}
    if "chain-flow-19" in reached:
        _emit(
            report,
            "perf",
            Finding(
                category="perf",
                title="Deep chain traversal reaches tail",
                status="ok",
                detail=f"walked {len(reached)} nodes, got to chain-flow-19",
            ),
        )
    else:
        _emit(
            report,
            "perf",
            Finding(
                category="perf",
                title="Deep chain traversal reaches tail",
                status="bug",
                detail=f"chain-flow-19 not reached, visited {len(reached)}",
            ),
        )

    # Wide fan-out correctness
    variants = find_variants(conn, "wide-cap")
    if len(variants) == 100:
        _emit(
            report,
            "perf",
            Finding(
                category="perf",
                title="Wide fan-out returns all 100 variants",
                status="ok",
                detail="",
            ),
        )
    else:
        _emit(
            report,
            "perf",
            Finding(
                category="perf",
                title="Wide fan-out variant count",
                status="bug",
                detail=f"expected 100, got {len(variants)}",
            ),
        )


# ---------------------------------------------------------------------------
# Edge cases / correctness
# ---------------------------------------------------------------------------


def edge_case_suite(report: Report) -> None:
    print(f"\n{YELLOW}▌ 2. CORRECTNESS EDGE CASES{RESET}")

    # --- Idempotent bootstrap ---
    try:
        conn = open_db(":memory:")
        add_node(conn, node_id="x", type="flow", title="X")
        add_node(conn, node_id="x", type="flow", title="X")
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="Re-adding same id",
                status="bug",
                detail="Should have raised IntegrityError",
            ),
        )
    except sqlite3.IntegrityError:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="Duplicate id is rejected",
                status="ok",
                detail="(but there is no add_or_update helper — see gap #1)",
            ),
        )

    # --- Delete cascade: does deleting a capability wipe edges? ---
    conn = open_db(":memory:")
    add_node(conn, node_id="cap", type="capability", title="Cap")
    for i in range(5):
        add_node(conn, node_id=f"f{i}", type="flow", title=f"F{i}")
        add_edge(conn, from_id=f"f{i}", to_id="cap", relation="implements")
    delete_node(conn, "cap")
    remaining_edges = list_edges(conn)
    if not remaining_edges:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="Deleting a node cascades to its edges",
                status="ok",
                detail="FK cascade works, but deletion is silent — see gap #2",
            ),
        )
    else:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="Deleting a node cascades to its edges",
                status="bug",
                detail=f"{len(remaining_edges)} orphan edges remain",
            ),
        )

    # --- Unicode round-trip ---
    conn = open_db(":memory:")
    body = "Probamos diacríticos: áéíóú ñ ¿¡ — y emoji 🚀✨💡"
    add_node(
        conn,
        node_id="u-1",
        type="flow",
        title="Título con ñ y 🚀",
        body=body,
    )
    from domaintome.graph import get_node

    got = get_node(conn, "u-1")
    if got and got["body"] == body and "🚀" in got["title"]:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="Unicode and emoji round-trip",
                status="ok",
                detail="",
            ),
        )
    else:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="Unicode round-trip",
                status="bug",
                detail=repr(got),
            ),
        )

    # --- Very long body (100KB) ---
    conn = open_db(":memory:")
    big = "línea\n" * 20000  # ~120KB
    add_node(conn, node_id="big", type="flow", title="Big", body=big)
    got_big = get_node(conn, "big")
    if got_big and len(got_big["body"]) == len(big):
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="100KB body round-trip",
                status="ok",
                detail="but this probably shouldn't be encouraged — see gap #3",
            ),
        )

    # --- depends_on cycle — NOT DETECTED by audit ---
    conn = open_db(":memory:")
    add_node(conn, node_id="m1", type="module", title="M1")
    add_node(conn, node_id="m2", type="module", title="M2")
    add_edge(conn, from_id="m1", to_id="m2", relation="depends_on")
    add_edge(conn, from_id="m2", to_id="m1", relation="depends_on")
    report_audit = audit(conn)
    status_dep = "ok" if report_audit.get("cycles_depends_on") else "bug"
    _emit(
        report,
        "edge_cases",
        Finding(
            category="edge",
            title="depends_on cycles detected by audit",
            status=status_dep,
            detail="audit flags depends_on A->B->A (BUG-001 resolved)"
            if status_dep == "ok"
            else "audit missed depends_on cycle — BUG-001",
        ),
    )

    # --- triggers cycle ---
    conn = open_db(":memory:")
    add_node(conn, node_id="e1", type="event", title="e1")
    add_node(conn, node_id="e2", type="event", title="e2")
    add_edge(conn, from_id="e1", to_id="e2", relation="triggers")
    add_edge(conn, from_id="e2", to_id="e1", relation="triggers")
    report_audit2 = audit(conn)
    status_trg = "ok" if report_audit2.get("cycles_triggers") else "bug"
    _emit(
        report,
        "edge_cases",
        Finding(
            category="edge",
            title="triggers cycles detected by audit",
            status=status_trg,
            detail="audit flags triggers A->B->A (BUG-002 resolved)"
            if status_trg == "ok"
            else "audit missed triggers cycle — BUG-002",
        ),
    )

    # --- Update node idempotency: update twice with same values ---
    conn = open_db(":memory:")
    add_node(conn, node_id="u", type="flow", title="U")
    update_node(conn, "u", title="V")
    r1 = get_node(conn, "u")
    update_node(conn, "u", title="V")
    r2 = get_node(conn, "u")
    if r1 and r2 and r2["updated_at"] >= r1["updated_at"]:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="Redundant update bumps updated_at",
                status="gap",
                detail="No-op updates still bump the timestamp. Arguable, but "
                "makes 'recently changed' noisy — GAP-TIMESTAMP",
            ),
        )

    # --- Full-text search miss on body ---
    conn = open_db(":memory:")
    add_node(
        conn,
        node_id="doc",
        type="flow",
        title="Processing",
        body="This explains the refund logic in detail.",
    )
    res = query(conn, "refund")
    if not res["nodes"]:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="query() does not match body text",
                status="gap",
                detail="'refund' is in the body but query() only searches title/id"
                "/tag. For an LLM, bodies are exactly where the answer lives — "
                "GAP-FTS",
            ),
        )
    else:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="query() matches body text",
                status="ok",
                detail="",
            ),
        )

    # --- Schema gap: entity → part_of → module is NOT allowed ---
    conn = open_db(":memory:")
    add_node(conn, node_id="m", type="module", title="M")
    add_node(conn, node_id="e", type="entity", title="E")
    try:
        add_edge(conn, from_id="e", to_id="m", relation="part_of")
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="entity part_of module",
                status="ok",
                detail="",
            ),
        )
    except SchemaError:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="entity cannot be part_of module",
                status="bug",
                detail="PRD §5 Q5 asks 'which entities and in which module?' but "
                "the schema forbids this edge — BUG-SCHEMA-Q5",
            ),
        )

    # --- Schema gap: flow → rule direct (no form in between) ---
    conn = open_db(":memory:")
    add_node(conn, node_id="fl", type="flow", title="Fl")
    add_node(conn, node_id="rl", type="rule", title="Rl")
    try:
        add_edge(conn, from_id="fl", to_id="rl", relation="validates")
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="flow validates rule (no form)",
                status="ok",
                detail="",
            ),
        )
    except SchemaError:
        _emit(
            report,
            "edge_cases",
            Finding(
                category="edge",
                title="flow cannot directly relate to rule",
                status="bug",
                detail="For UI-less projects (CLI, data pipelines) rules apply "
                "directly to flows — we force an artificial 'form' — "
                "BUG-SCHEMA-Q12",
            ),
        )


# ---------------------------------------------------------------------------
# Product gaps — things a real team would ask
# ---------------------------------------------------------------------------


PRODUCT_GAPS = [
    # (title, detail)
    (
        "Ownership: who owns module X?",
        "No `person`/`team`/`owner` node type. Real teams ask 'who do I ping?' "
        "Workaround: tags (metadata.tags=['team-payments']) — weak and "
        "stringly-typed. Proposal: add `team` node + `owned_by` relation.",
    ),
    (
        "HTTP API surface: what endpoints do we expose?",
        "No `endpoint` type. Backends live and die by their API surface. "
        "Forcing it into `flow` loses verb/path/auth. Proposal: add `endpoint` "
        "with method, path, auth fields in metadata.",
    ),
    (
        "UI: which screens trigger this flow?",
        "No `screen`/`page` type. For frontend-heavy projects, the question "
        "'what screens touch X?' is the #1 ask. Proposal: add `screen` and "
        "`user_journey`.",
    ),
    (
        "External integrations: what third-party services do we call?",
        "No `integration`/`external_service` type. Critical for incident "
        "response and vendor lock-in analysis. Proposal: add `integration`.",
    ),
    (
        "Entity attributes: what fields does Invoice have?",
        "`entity` has no attributes/schema. Can't answer 'what changes if I add "
        "a column'. Proposal: allow nested `field` nodes or store a JSON schema "
        "in metadata.",
    ),
    (
        "Entity-to-entity relations: how is Invoice connected to Payment?",
        "Schema doesn't allow `entity → entity` relations. No ER diagram is "
        "derivable. Proposal: allow a generic `relates_to` between entities.",
    ),
    (
        "Tests: what's tested and what isn't?",
        "No `test` type. Can't answer 'is this flow covered?' Proposal: add "
        "`test` + `covers` relation to flow/rule/endpoint.",
    ),
    (
        "Compliance / data classification",
        "No way to mark PII or regulated data. Proposal: `metadata.pii: true` "
        "convention, plus a `classification` node for shared tags like GDPR.",
    ),
    (
        "Recently changed: what moved this week?",
        "No tool filters by `updated_at`. CTE would be 3 lines but there's no "
        "CLI/MCP surface. Proposal: `dt recent --since 7d` + "
        "`dt_recent(since)` MCP tool.",
    ),
    (
        "Count/analytics: how many flows per capability?",
        "No aggregation tool. Have to list+filter in client. Proposal: "
        "`dt_stats()` returning counts by type, top-N connected nodes, "
        "orphan/island ratio.",
    ),
    (
        "Path finding: is A connected to B, and how?",
        "No shortest-path / any-path API. Traverse only walks from a fixed "
        "source. Proposal: `dt_paths(from, to, max_depth)`.",
    ),
    (
        "Centrality: what are the most connected nodes?",
        "No degree/centrality summary. Important for 'what will break if I "
        "touch this?' Proposal: `dt_hotspots()` returning top-N by degree.",
    ),
    (
        "Changelog / history: why was this node changed?",
        "Only `created_at` and `updated_at` are stored. No history, no reason. "
        "Proposal: optional `node_history` table or a `revisions` view built "
        "from MCP-captured diffs.",
    ),
    (
        "Cross-cutting slices: everything related to 'auth'",
        "Tags partially answer this but can't combine (AND/OR), and there's "
        "no CLI. Proposal: `dt query --tag auth --tag critical`.",
    ),
    (
        "Bidirectional query: who references this decision?",
        "`dt show <decision>` shows INCOMING references already — good. But "
        "there's no tool to list 'most-referenced decisions' or 'decisions "
        "with zero references' (probably obsolete).",
    ),
    (
        "Validation: run schema migrations / re-check all edges",
        "If we change ALLOWED_RELATIONS, nothing re-validates existing rows. "
        "Proposal: `dt audit --strict` re-validates every edge against "
        "current schema.",
    ),
    (
        "Export formats beyond markdown",
        "No JSON/GraphViz/Mermaid export. A Mermaid export of a capability "
        "neighborhood would slot straight into PRs and READMEs. Proposal: "
        "`dt export --format mermaid`.",
    ),
    (
        "LLM-friendly tool for 'summarize module X'",
        "The closest is `dt query module-id --depth 2`, returning raw nodes. "
        "An LLM would benefit from a pre-digested `dt_summarize(node_id)` "
        "that groups and labels. Not critical but would reduce token use.",
    ),
    (
        "Confidence / freshness flags on nodes",
        "No way to mark 'I'm not 100% sure about this' or 'this may be stale'. "
        "Useful for LLM edits. Proposal: `metadata.confidence: 'low'` convention "
        "+ audit warning on nodes > N days old.",
    ),
    (
        "Project bootstrap: generate seed from codebase",
        "PRD §3 explicitly defers this (no parser). That's fine now, but "
        "having seen how tedious the seed is, a 'dt suggest' that proposes "
        "module nodes from folder structure would make bootstrap 10× faster.",
    ),
]


def product_gap_suite(report: Report) -> None:
    print(f"\n{YELLOW}▌ 3. PRODUCT GAPS{RESET} (things a real team would ask)")
    for title, detail in PRODUCT_GAPS:
        _emit(
            report,
            "product_gaps",
            Finding(category="product", title=title, status="gap", detail=detail),
        )


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def main() -> int:
    if not STRESS_DB.exists():
        print(
            f"{RED}No stress graph at {STRESS_DB}. "
            f"Run examples/stress/build_large_graph.py first.{RESET}"
        )
        return 2

    report = Report()
    conn = open_db(STRESS_DB)
    perf_suite(conn, report)
    conn.close()

    edge_case_suite(report)
    product_gap_suite(report)

    # Summary
    print(f"\n{YELLOW}▌ SUMMARY{RESET}")
    by_status: dict[str, int] = {}
    for section in (report.perf, report.edge_cases, report.product_gaps):
        for f in section:
            by_status[f.status] = by_status.get(f.status, 0) + 1
    for s in ("ok", "slow", "bug", "gap"):
        if s in by_status:
            color = {"ok": GREEN, "slow": YELLOW, "bug": RED, "gap": CYAN}[s]
            print(f"  {color}{s:>5}{RESET}  {by_status[s]}")

    REPORT_PATH.write_text(
        json.dumps(
            {
                "perf": [asdict(f) for f in report.perf],
                "edge_cases": [asdict(f) for f in report.edge_cases],
                "product_gaps": [asdict(f) for f in report.product_gaps],
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nStructured report written to {REPORT_PATH}")

    # Exit non-zero if any bugs found
    bugs = by_status.get("bug", 0)
    return 0 if bugs == 0 else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())

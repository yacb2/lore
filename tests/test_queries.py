"""Query and traversal tests."""

from __future__ import annotations

from domaintome.graph import (
    add_edge,
    add_node,
    audit,
    find_variants,
    list_nodes,
    query,
    traverse,
)


def test_list_nodes_by_type(seeded_conn):
    flows = list_nodes(seeded_conn, type="flow")
    ids = {n["id"] for n in flows}
    assert ids == {"payment-by-transfer", "payment-by-tpv"}


def test_list_nodes_summary_only_drops_body(seeded_conn):
    flows = list_nodes(seeded_conn, type="flow", summary_only=True)
    assert flows, "seed has flows"
    for n in flows:
        assert set(n.keys()) == {"id", "type", "title", "status"}
        assert "body" not in n
        assert "metadata" not in n


def test_list_nodes_by_status(seeded_conn):
    actives = list_nodes(seeded_conn, status="active")
    assert len(actives) >= 1
    deprecated = list_nodes(seeded_conn, status="deprecated")
    assert deprecated == []


def test_list_nodes_by_tag(conn):
    add_node(conn, node_id="a", type="flow", title="A", metadata={"tags": ["billing"]})
    add_node(conn, node_id="b", type="flow", title="B", metadata={"tags": ["core"]})
    billing = list_nodes(conn, tag="billing")
    assert [n["id"] for n in billing] == ["a"]


def test_query_by_exact_id(seeded_conn):
    result = query(seeded_conn, "payment-by-transfer", depth=0)
    ids = {n["id"] for n in result["nodes"]}
    assert "payment-by-transfer" in ids
    # depth=0 means only the matched node, no neighborhood
    assert len(ids) == 1


def test_query_by_title_fuzzy(seeded_conn):
    result = query(seeded_conn, "transfer", depth=0)
    ids = {n["id"] for n in result["nodes"]}
    assert "payment-by-transfer" in ids


def test_query_with_depth_expands_neighborhood(seeded_conn):
    result = query(seeded_conn, "payment-by-transfer", depth=1)
    ids = {n["id"] for n in result["nodes"]}
    # At depth 1 should include payments (part_of), payment-registration
    # (implements), payment-recorded (triggers)
    assert "payments" in ids
    assert "payment-registration" in ids
    assert "payment-recorded" in ids
    # Edges within the returned set are included
    assert len(result["edges"]) >= 3


def test_find_variants(seeded_conn):
    variants = find_variants(seeded_conn, "payment-registration")
    ids = {n["id"] for n in variants}
    assert ids == {"payment-by-transfer", "payment-by-tpv"}


def test_traverse_follow_specific_relations(seeded_conn):
    result = traverse(
        seeded_conn,
        "payment-by-transfer",
        relations=["triggers"],
        max_depth=3,
    )
    ids = {n["id"] for n in result["nodes"]}
    assert ids == {"payment-by-transfer", "payment-recorded"}


def test_traverse_all_relations(seeded_conn):
    result = traverse(seeded_conn, "payment-by-transfer", max_depth=1)
    ids = {n["id"] for n in result["nodes"]}
    # Should reach payments, payment-registration, payment-recorded via outgoing
    assert "payments" in ids
    assert "payment-registration" in ids
    assert "payment-recorded" in ids


def test_traverse_unknown_start(conn):
    result = traverse(conn, "ghost")
    assert result == {"nodes": [], "edges": []}


def test_audit_finds_orphans(conn):
    add_node(conn, node_id="lonely", type="decision", title="Lonely decision")
    report = audit(conn)
    assert "lonely" in report["orphans"]


def test_audit_detects_generic_id(conn):
    add_node(conn, node_id="overview", type="module", title="Generic")
    report = audit(conn)
    assert "overview" in report["generic_ids"]


def test_audit_detects_supersedes_cycle(conn):
    add_node(conn, node_id="a", type="flow", title="A")
    add_node(conn, node_id="b", type="flow", title="B")
    add_edge(conn, from_id="a", to_id="b", relation="supersedes")
    add_edge(conn, from_id="b", to_id="a", relation="supersedes")
    report = audit(conn)
    assert report["cycles_supersedes"], "should detect cycle"


def test_audit_detects_depends_on_cycle(conn):
    add_node(conn, node_id="m1", type="module", title="M1")
    add_node(conn, node_id="m2", type="module", title="M2")
    add_edge(conn, from_id="m1", to_id="m2", relation="depends_on")
    add_edge(conn, from_id="m2", to_id="m1", relation="depends_on")
    report = audit(conn)
    assert report["cycles_depends_on"], "should detect depends_on cycle"
    assert not report["cycles_supersedes"], "wrong relation should not trigger"


def test_audit_detects_triggers_cycle(conn):
    add_node(conn, node_id="e1", type="event", title="e1")
    add_node(conn, node_id="e2", type="event", title="e2")
    add_edge(conn, from_id="e1", to_id="e2", relation="triggers")
    add_edge(conn, from_id="e2", to_id="e1", relation="triggers")
    report = audit(conn)
    assert report["cycles_triggers"], "should detect triggers cycle"


def test_audit_acyclic_graph_has_no_cycles(seeded_conn):
    report = audit(seeded_conn)
    assert report["cycles_supersedes"] == []
    assert report["cycles_depends_on"] == []
    assert report["cycles_triggers"] == []


def test_audit_reports_counts_and_breakdowns(seeded_conn):
    report = audit(seeded_conn)
    assert report["nodes_total"] > 0
    assert report["edges_total"] > 0
    assert isinstance(report["nodes_by_type"], dict)
    assert isinstance(report["nodes_by_status"], dict)
    assert isinstance(report["edges_by_relation"], dict)
    assert sum(report["nodes_by_type"].values()) == report["nodes_total"]
    assert sum(report["nodes_by_status"].values()) == report["nodes_total"]
    assert sum(report["edges_by_relation"].values()) == report["edges_total"]
    assert report["last_mutation_at"] is not None


def test_audit_empty_graph_has_zero_counts(conn):
    report = audit(conn)
    assert report["nodes_total"] == 0
    assert report["edges_total"] == 0
    assert report["nodes_by_type"] == {}
    assert report["last_mutation_at"] is None

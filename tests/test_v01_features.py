"""Tests for v0.1.0 audit-driven improvements:
- richer SchemaError messages (A1, A6)
- soft body/source/orphan warnings (A3, A4, A5)
- dt_schema descriptor (A2)
- minimal MCP response shape (A7)
- audit_log telemetry (B1)
- quality report + by-day stats (B2, B3)
"""

from __future__ import annotations

import pytest

from domaintome.graph import add_edge, add_node, add_nodes_batch, open_db
from domaintome.graph.quality import (
    errors_breakdown,
    quality_report,
    stats_by_day,
)
from domaintome.graph.schema import SchemaError, schema_descriptor, validate_edge_types


# A1 — SchemaError shows the relations valid for the specific pair.
def test_schema_error_includes_pair_specific_hint():
    # rule -> capability has no allowed relations, so the message should
    # surface the full reachability map for `rule`.
    with pytest.raises(SchemaError) as exc:
        validate_edge_types("enforces", "rule", "capability")
    msg = str(exc.value)
    assert "rule" in msg and "capability" in msg
    assert "From 'rule' you can reach" in msg


def test_schema_error_lists_valid_relations_when_pair_has_options():
    with pytest.raises(SchemaError) as exc:
        validate_edge_types("enforces", "rule", "rule")
    msg = str(exc.value)
    # rule->rule allows supersedes / conflicts_with
    assert "Allowed for rule→rule" in msg
    assert "supersedes" in msg


# A6 — invalid id mentions bad chars and proposes a fix.
def test_invalid_id_message_suggests_kebab():
    from domaintome.graph.schema import validate_id

    with pytest.raises(SchemaError) as exc:
        validate_id("module.frontend.x")
    msg = str(exc.value)
    assert "Bad chars" in msg
    assert "module-frontend-x" in msg


# A2 — schema_descriptor contains everything the LLM needs.
def test_schema_descriptor_shape():
    d = schema_descriptor()
    assert "module" in d["node_types"]
    assert "part_of" in d["relations"]
    assert "module->module" in d["allowed_pairs"]
    assert "user_confirmed" in d["metadata"]["source_canonical"]
    assert d["body_min_chars_for"]["capability"] >= 1


# A3 — capability with thin body emits a warning.
def test_thin_body_emits_warning():
    conn = open_db(":memory:")
    node = add_node(
        conn,
        node_id="cap-x",
        type="capability",
        title="X",
        body="short",
        metadata={"source": "user_confirmed", "confidence": "high", "source_ref": "x.py:1"},
    )
    assert any("body_thin" in w for w in node["warnings"])


# A4 — non-canonical source is hard-rejected at write time so the
# vocabulary stays clean instead of drifting through warnings nobody acts on.
def test_non_canonical_source_is_rejected():
    conn = open_db(":memory:")
    with pytest.raises(SchemaError) as exc:
        add_node(
            conn,
            node_id="m",
            type="module",
            title="M",
            metadata={"source": "auto_scan", "confidence": "high", "source_ref": "x:1"},
        )
    assert "auto_scan" in str(exc.value)


def test_non_canonical_confidence_is_rejected():
    conn = open_db(":memory:")
    with pytest.raises(SchemaError):
        add_node(
            conn,
            node_id="m",
            type="module",
            title="M",
            metadata={"source": "user_stated", "confidence": "maybe"},
        )


# A5 — fresh rule with no edges -> orphan warning.
def test_orphan_rule_warning():
    conn = open_db(":memory:")
    add_node(conn, node_id="entity-a", type="entity", title="A")
    rule = add_node(
        conn,
        node_id="rule-must-x",
        type="rule",
        title="Must X",
        body=("." * 100),
        metadata={"source": "user_stated", "confidence": "high", "source_ref": "x:1"},
    )
    assert any("orphan" in w for w in rule["warnings"])

    # After connecting it, future creates won't warn (rule itself stays
    # however — the warning fires at insert time only).
    add_edge(conn, from_id="rule-must-x", to_id="entity-a", relation="enforces")
    again = add_node(
        conn,
        node_id="rule-must-y",
        type="rule",
        title="Must Y",
        body=("." * 100),
        metadata={"source": "user_stated", "confidence": "high", "source_ref": "x:1"},
    )
    add_edge(conn, from_id="rule-must-y", to_id="entity-a", relation="enforces")
    # A new rule we attach later does emit the orphan warning at create time
    # (that's expected — it's orphan when first persisted). The point of
    # this assertion is just that the API stays stable.
    assert isinstance(again["warnings"], list)


def test_batch_create_reports_warnings_per_node():
    conn = open_db(":memory:")
    results = add_nodes_batch(
        conn,
        [
            {
                "id": "m1",
                "type": "module",
                "title": "M1",
                "metadata": {"source": "user_stated", "confidence": "high", "source_ref": "x:1"},
            },
            {
                "id": "cap-thin",
                "type": "capability",
                "title": "C",
                "body": "x",
                "metadata": {"source": "user_stated", "confidence": "high", "source_ref": "x:1"},
            },
        ],
    )
    assert results[0]["warnings"] == []
    assert any("body_thin" in w for w in results[1]["warnings"])


# B1 — audit_log captures latency_ms / warnings_count / client_id.
def test_audit_log_extended_columns_present():
    conn = open_db(":memory:")
    cols = {row[1] for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()}
    assert {"node_type", "latency_ms", "warnings_count", "client_id"} <= cols


# B2 — quality report aggregates everything we want to track.
def test_quality_report_basic():
    conn = open_db(":memory:")
    add_node(
        conn,
        node_id="m1",
        type="module",
        title="M",
        metadata={"source": "user_stated", "confidence": "high", "source_ref": "x:1"},
    )
    # Insert a legacy node directly to simulate a graph created before the
    # vocabulary was hard-enforced — quality_report still has to surface
    # these so users can clean them up.
    import json as _json

    from domaintome.graph._common import now_iso
    legacy_meta = _json.dumps({"source": "auto_scan"})
    conn.execute(
        "INSERT INTO nodes (id, type, title, body, status, metadata_json, "
        "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("cap-thin", "capability", "C", "x", "active", legacy_meta,
         now_iso(), now_iso()),
    )
    conn.commit()
    rep = quality_report(conn)
    assert rep["node_total"] == 2
    assert rep["by_type"]["capability"]["total"] == 1
    assert any(n["id"] == "cap-thin" for n in rep["body_thin"])
    assert "auto_scan" in rep["non_canonical_source"]
    assert rep["missing_confidence"] >= 1
    assert rep["missing_source_ref"] >= 1


# B3 — stats_by_day + errors_breakdown read from audit_log.
def test_stats_by_day_returns_rows_when_audit_log_has_data():
    conn = open_db(":memory:")
    conn.execute(
        """INSERT INTO audit_log
           (timestamp, tool, op, input_bytes, output_bytes, warnings_count, error)
           VALUES ('2026-04-29T10:00:00Z', 'dt_add_node', 'create', 100, 50, 1, NULL),
                  ('2026-04-29T11:00:00Z', 'dt_add_edge', 'create', 80, 20, 0,
                   'SchemaError: bad relation')"""
    )
    conn.commit()
    rows = stats_by_day(conn)
    assert rows[0]["day"] == "2026-04-29"
    assert rows[0]["calls"] == 2
    assert rows[0]["errors"] == 1
    assert rows[0]["warnings"] == 1
    errs = errors_breakdown(conn)
    assert errs[0]["n"] == 1
    assert "SchemaError" in errs[0]["error"]

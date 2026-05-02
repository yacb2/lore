"""Schema validation tests."""

from __future__ import annotations

import pytest

from domaintome.graph.schema import (
    SchemaError,
    is_relation_allowed,
    is_valid_id,
    validate_edge_types,
    validate_id,
    validate_node_type,
    validate_relation,
    validate_status,
)


class TestNodeTypes:
    def test_valid_type_passes(self):
        validate_node_type("flow")

    def test_invalid_type_raises(self):
        with pytest.raises(SchemaError):
            validate_node_type("service")


class TestStatus:
    def test_valid_statuses(self):
        for s in ("active", "draft", "deprecated", "superseded", "archived"):
            validate_status(s)

    def test_invalid_status(self):
        with pytest.raises(SchemaError):
            validate_status("frozen")


class TestRelation:
    def test_valid_relation(self):
        validate_relation("implements")

    def test_invalid_relation(self):
        with pytest.raises(SchemaError):
            validate_relation("uses")


class TestAllowedRelations:
    def test_flow_implements_capability(self):
        assert is_relation_allowed("implements", "flow", "capability")

    def test_capability_cannot_implement_flow(self):
        assert not is_relation_allowed("implements", "capability", "flow")

    def test_rule_enforces_entity(self):
        assert is_relation_allowed("enforces", "rule", "entity")

    def test_references_from_any_to_decision(self):
        for t in ("module", "capability", "flow", "event", "rule", "form", "entity"):
            assert is_relation_allowed("references", t, "decision")

    def test_supersedes_only_same_type(self):
        assert is_relation_allowed("supersedes", "flow", "flow")
        assert is_relation_allowed("supersedes", "rule", "rule")
        assert not is_relation_allowed("supersedes", "flow", "rule")

    def test_conflicts_with_rule_and_flow(self):
        assert is_relation_allowed("conflicts_with", "rule", "rule")
        assert is_relation_allowed("conflicts_with", "flow", "flow")
        assert not is_relation_allowed("conflicts_with", "rule", "flow")

    def test_validate_edge_types_raises_on_invalid(self):
        with pytest.raises(SchemaError):
            validate_edge_types("validates", "module", "rule")

    def test_part_of_supports_module_to_module_hierarchy(self):
        """Inner module `part_of` parent module (e.g. Django app inside
        a workspace-level `backend` repo module). Required for multi-repo
        hierarchical layouts."""
        assert is_relation_allowed("part_of", "module", "module")

    def test_part_of_remains_restricted_for_other_types(self):
        assert is_relation_allowed("part_of", "flow", "module")
        assert is_relation_allowed("part_of", "capability", "module")
        assert not is_relation_allowed("part_of", "module", "flow")
        assert not is_relation_allowed("part_of", "module", "capability")


class TestIds:
    @pytest.mark.parametrize(
        "good",
        [
            "payments",
            "payment-by-transfer",
            "invoice-create-form",
            "module-1",
            "a",
        ],
    )
    def test_valid_ids(self, good):
        assert is_valid_id(good)

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "Payments",
            "payment_by_transfer",
            "-payments",
            "payments-",
            "payment--by",
            "payment by transfer",
            "payments:overview",
        ],
    )
    def test_invalid_ids(self, bad):
        assert not is_valid_id(bad)

    def test_validate_id_raises(self):
        with pytest.raises(SchemaError):
            validate_id("BadId")

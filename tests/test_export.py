"""Markdown export tests."""

from __future__ import annotations

from domaintome.export import export_markdown


def test_export_writes_file_per_node(seeded_conn, tmp_path):
    written = export_markdown(seeded_conn, tmp_path)
    assert len(written) == 8
    # flows/
    flow_file = tmp_path / "flow" / "payment-by-transfer.md"
    assert flow_file.exists()
    content = flow_file.read_text()
    assert "id: payment-by-transfer" in content
    assert "type: flow" in content
    assert "implements: [payment-registration]" in content
    assert "triggers: [payment-recorded]" in content


def test_export_includes_tags(conn, tmp_path):
    from domaintome.graph import add_node

    add_node(
        conn,
        node_id="x",
        type="flow",
        title="X",
        metadata={"tags": ["billing", "core"]},
    )
    export_markdown(conn, tmp_path)
    content = (tmp_path / "flow" / "x.md").read_text()
    assert "tags: [billing, core]" in content

"""Tests for domaintome.lifecycle — reconcile drift detection."""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from domaintome.graph import add_node, open_db
from domaintome.lifecycle import reconcile


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Fake project root with a .dt/ subdir and some source files."""
    (tmp_path / ".dt").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "foo.py").write_text("# alive\n")
    return tmp_path


@pytest.fixture
def conn(project_root: Path):
    conn = open_db(project_root / ".dt" / "graph.db")
    yield conn
    conn.close()


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _days_ago(n: int) -> str:
    return (datetime.now(UTC) - timedelta(days=n)).date().isoformat()


def test_reconcile_empty_graph_has_no_drift(conn, project_root):
    report = reconcile(conn, project_root)
    assert report["dead_refs"] == []
    assert report["stale"] == []
    assert report["never_verified"] == []
    assert report["scanned_nodes"] == 0
    assert report["warnings"] == []


def test_reconcile_draft_node_with_missing_file_is_planned_not_dead(
    conn, project_root
):
    add_node(
        conn,
        node_id="flow-future",
        type="flow",
        title="Not yet implemented",
        status="draft",
        metadata={
            "source": "user_stated",
            "source_ref": "backend/apps/future/views.py:FutureView.post",
            "last_verified_at": _today(),
        },
    )
    add_node(
        conn,
        node_id="flow-real-dead",
        type="flow",
        title="Was real, file removed",
        status="active",
        metadata={
            "source": "inferred_from_code",
            "source_ref": "src/ghost.py:10",
            "last_verified_at": _today(),
        },
    )
    report = reconcile(conn, project_root)
    dead_ids = {x["id"] for x in report["dead_refs"]}
    planned_ids = {x["id"] for x in report["planned"]}
    assert "flow-real-dead" in dead_ids
    assert "flow-future" in planned_ids
    assert "flow-future" not in dead_ids, (
        "draft nodes must not be classified as dead refs"
    )


def test_reconcile_detects_dead_ref(conn, project_root):
    add_node(
        conn,
        node_id="flow-foo",
        type="flow",
        title="Foo",
        metadata={
            "source": "inferred_from_code",
            "confidence": "medium",
            "source_ref": "src/ghost.py:10",
            "last_verified_at": _today(),
        },
    )
    add_node(
        conn,
        node_id="flow-alive",
        type="flow",
        title="Alive",
        metadata={
            "source": "inferred_from_code",
            "confidence": "medium",
            "source_ref": "src/foo.py:1",
            "last_verified_at": _today(),
        },
    )
    report = reconcile(conn, project_root)
    assert len(report["dead_refs"]) == 1
    assert report["dead_refs"][0]["id"] == "flow-foo"
    assert report["dead_refs"][0]["source_ref"] == "src/ghost.py:10"
    assert report["stale"] == []
    assert report["never_verified"] == []


def test_reconcile_detects_stale_node(conn, project_root):
    add_node(
        conn,
        node_id="flow-aged",
        type="flow",
        title="Aged",
        metadata={
            "source_ref": "src/foo.py",
            "last_verified_at": _days_ago(120),
        },
    )
    report = reconcile(conn, project_root, stale_days=90)
    assert len(report["stale"]) == 1
    assert report["stale"][0]["id"] == "flow-aged"
    assert report["stale"][0]["days_since"] >= 120


def test_reconcile_stale_threshold_respected(conn, project_root):
    add_node(
        conn,
        node_id="flow-recent",
        type="flow",
        title="Recent",
        metadata={
            "source_ref": "src/foo.py",
            "last_verified_at": _days_ago(30),
        },
    )
    report = reconcile(conn, project_root, stale_days=90)
    assert report["stale"] == []


def test_reconcile_detects_never_verified(conn, project_root):
    add_node(
        conn,
        node_id="flow-unchecked",
        type="flow",
        title="Unchecked",
        metadata={"source_ref": "src/foo.py"},
    )
    report = reconcile(conn, project_root)
    assert len(report["never_verified"]) == 1
    assert report["never_verified"][0]["id"] == "flow-unchecked"
    assert report["stale"] == []


def test_reconcile_ignores_nodes_without_source_ref(conn, project_root):
    add_node(conn, node_id="flow-abstract", type="flow", title="No ref")
    report = reconcile(conn, project_root)
    assert report["scanned_nodes"] == 0
    assert report["dead_refs"] == []


def test_reconcile_since_falls_back_when_not_git(conn, project_root):
    add_node(
        conn,
        node_id="flow-foo",
        type="flow",
        title="Foo",
        metadata={"source_ref": "src/foo.py", "last_verified_at": _today()},
    )
    report = reconcile(conn, project_root, since="HEAD~1")
    assert any(
        "not a git repo" in w for w in report["warnings"]
    ), f"expected not-a-git warning, got: {report['warnings']}"
    assert report["scope"] == "full"


def test_reconcile_since_filters_to_changed_files(conn, project_root):
    subprocess.run(
        ["git", "init", "-q", str(project_root)],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project_root), "config", "user.email", "t@e.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(project_root), "config", "user.name", "Test"],
        check=True,
    )
    (project_root / "src" / "bar.py").write_text("# bar\n")
    subprocess.run(
        ["git", "-C", str(project_root), "add", "."], check=True
    )
    subprocess.run(
        ["git", "-C", str(project_root), "commit", "-qm", "initial"], check=True
    )
    (project_root / "src" / "foo.py").write_text("# changed\n")
    subprocess.run(
        ["git", "-C", str(project_root), "commit", "-aqm", "touch foo"], check=True
    )

    add_node(
        conn,
        node_id="flow-foo",
        type="flow",
        title="Foo",
        metadata={
            "source_ref": "src/foo.py",
            "last_verified_at": _days_ago(120),
        },
    )
    add_node(
        conn,
        node_id="flow-bar",
        type="flow",
        title="Bar",
        metadata={
            "source_ref": "src/bar.py",
            "last_verified_at": _days_ago(120),
        },
    )
    report = reconcile(conn, project_root, since="HEAD~1", stale_days=90)
    stale_ids = {x["id"] for x in report["stale"]}
    assert "flow-foo" in stale_ids
    assert "flow-bar" not in stale_ids, (
        "bar.py was not changed since HEAD~1, so its node should be skipped"
    )
    assert report["scope"] == "since:HEAD~1"

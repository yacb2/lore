"""Tests for the sync report and the `lore sync-plan` CLI command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lore.cli import app
from lore.graph import add_node, open_db
from lore.sync import (
    BORING_SUFFIXES,
    compute_sync_report,
    find_git_repos,
    is_boring,
)

runner = CliRunner()


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "commit", "--allow-empty", "-m", "initial")


def _commit_file(repo: Path, rel: str, content: str = "x\n") -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", f"add {rel}")


def test_is_boring_filters_lockfiles_and_assets():
    assert is_boring("frontend/pnpm-lock.yaml")
    assert is_boring("backend/poetry.lock")
    assert is_boring("frontend/src/components/Foo.css")
    assert is_boring("docs/readme.md")
    assert not is_boring("backend/people/views.py")
    assert not is_boring("frontend/src/components/Foo.vue")


def test_boring_suffixes_match_documented_set():
    # If this list shrinks accidentally, the hook will start nagging
    # about lockfiles.
    assert ".css" in BORING_SUFFIXES
    assert ".lock" in BORING_SUFFIXES


def test_find_git_repos_handles_workspace_layout(tmp_path):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    _init_repo(backend)
    _init_repo(frontend)
    (tmp_path / "_scratch").mkdir()  # bare dir, ignored
    (tmp_path / ".cache").mkdir()  # hidden, skipped

    repos = find_git_repos(tmp_path)
    assert {r.name for r in repos} == {"backend", "frontend"}


def test_find_git_repos_handles_single_repo(tmp_path):
    _init_repo(tmp_path)
    repos = find_git_repos(tmp_path)
    assert repos == [tmp_path]


def test_compute_sync_report_splits_mapped_and_unmapped(tmp_path):
    _init_repo(tmp_path)
    _commit_file(tmp_path, "src/people/views.py")  # will be mapped
    _commit_file(tmp_path, "src/people/commands/cleanup.py")  # unmapped
    _commit_file(tmp_path, "frontend/styles.css")  # boring

    db = tmp_path / ".lore" / "lore.db"
    conn = open_db(db)
    add_node(
        conn,
        node_id="flow-people-list",
        type="flow",
        title="People list",
        metadata={"source_ref": "src/people/views.py"},
    )
    conn.close()

    conn = open_db(db)
    report = compute_sync_report(conn, tmp_path, since="HEAD~3")

    assert report["totals"]["mapped"] == 1
    assert report["totals"]["unmapped"] == 1
    assert report["totals"]["boring_skipped"] == 1
    assert report["scope"] == "HEAD~3..HEAD"

    repo = report["repos"][0]
    assert repo["repo"] == "."
    assert repo["mapped"][0]["path"] == "src/people/views.py"
    assert repo["mapped"][0]["nodes"][0]["id"] == "flow-people-list"
    assert "src/people/commands/cleanup.py" in repo["unmapped"]


def test_compute_sync_report_walks_workspace_with_two_repos(tmp_path):
    backend = tmp_path / "backend"
    frontend = tmp_path / "frontend"
    _init_repo(backend)
    _init_repo(frontend)
    _commit_file(backend, "people/views.py")
    _commit_file(frontend, "src/pages/People.vue")

    db = tmp_path / ".lore" / "lore.db"
    conn = open_db(db)
    # Map only the backend file. The frontend page is unmapped.
    add_node(
        conn,
        node_id="flow-people",
        type="flow",
        title="people",
        metadata={"source_ref": "people/views.py"},
    )
    conn.close()

    conn = open_db(db)
    report = compute_sync_report(conn, tmp_path, since="HEAD~1")
    repos_by_name = {r["repo"]: r for r in report["repos"]}
    assert "backend" in repos_by_name
    assert "frontend" in repos_by_name
    assert repos_by_name["backend"]["mapped"][0]["path"] == "people/views.py"
    assert "src/pages/People.vue" in repos_by_name["frontend"]["unmapped"]


def test_compute_sync_report_returns_empty_when_no_repos(tmp_path):
    db = tmp_path / ".lore" / "lore.db"
    conn = open_db(db)
    report = compute_sync_report(conn, tmp_path)
    assert report["repos"] == []
    assert report["totals"] == {"mapped": 0, "unmapped": 0, "boring_skipped": 0}
    assert any("no git repositories" in w for w in report["warnings"])


def test_sync_plan_cli_emits_json_and_exits_one_when_unmapped(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    _commit_file(tmp_path, "src/foo.py")
    db = tmp_path / ".lore" / "lore.db"
    open_db(db).close()  # empty graph: every changed file is unmapped

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["sync-plan", "--since", "HEAD~1", "--db", str(db)]
    )
    # Exit 1 because there are unmapped files.
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["totals"]["unmapped"] == 1
    assert payload["totals"]["mapped"] == 0


def test_sync_plan_cli_exits_zero_when_all_mapped(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    _commit_file(tmp_path, "src/foo.py")

    db = tmp_path / ".lore" / "lore.db"
    conn = open_db(db)
    add_node(
        conn,
        node_id="flow-foo",
        type="flow",
        title="foo",
        metadata={"source_ref": "src/foo.py"},
    )
    conn.close()

    monkeypatch.chdir(tmp_path)
    result = runner.invoke(
        app, ["sync-plan", "--since", "HEAD~1", "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["totals"]["mapped"] == 1
    assert payload["totals"]["unmapped"] == 0


@pytest.fixture(autouse=True)
def _quiet_git_advice(monkeypatch):
    """Silence init.defaultBranch advice in test output."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", "/dev/null")

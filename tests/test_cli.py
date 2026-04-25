"""CLI smoke tests."""

from __future__ import annotations

from typer.testing import CliRunner

from lore.cli import app
from lore.graph import add_edge, add_node, open_db

runner = CliRunner()


def _seed(db_path):
    conn = open_db(db_path)
    add_node(conn, node_id="payments", type="module", title="Payments")
    add_node(conn, node_id="pay-cap", type="capability", title="Pay Cap")
    add_node(conn, node_id="pay-flow", type="flow", title="Pay Flow")
    add_edge(conn, from_id="pay-flow", to_id="pay-cap", relation="implements")
    add_edge(conn, from_id="pay-flow", to_id="payments", relation="part_of")
    add_edge(conn, from_id="pay-cap", to_id="payments", relation="part_of")
    conn.close()


def test_init_creates_db(tmp_path):
    db = tmp_path / "lore.db"
    result = runner.invoke(app, ["init", "--db", str(db)])
    assert result.exit_code == 0
    assert db.exists()


def test_init_fails_if_exists(tmp_path):
    db = tmp_path / "lore.db"
    runner.invoke(app, ["init", "--db", str(db)])
    result = runner.invoke(app, ["init", "--db", str(db)])
    assert result.exit_code == 1


def test_list_empty(tmp_path):
    db = tmp_path / "lore.db"
    open_db(db).close()
    result = runner.invoke(app, ["list", "--db", str(db)])
    assert result.exit_code == 0
    assert "(no nodes)" in result.output


def test_list_shows_nodes(tmp_path):
    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(app, ["list", "--db", str(db)])
    assert "pay-flow" in result.output
    assert "payments" in result.output


def test_show_node(tmp_path):
    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(app, ["show", "pay-flow", "--db", str(db)])
    assert result.exit_code == 0
    assert "Pay Flow" in result.output
    assert "implements" in result.output


def test_show_missing(tmp_path):
    db = tmp_path / "lore.db"
    open_db(db).close()
    result = runner.invoke(app, ["show", "ghost", "--db", str(db)])
    assert result.exit_code == 1


def test_query(tmp_path):
    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(app, ["query", "Pay", "--db", str(db)])
    assert result.exit_code == 0
    assert "pay-flow" in result.output


def test_variants(tmp_path):
    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(app, ["variants", "pay-cap", "--db", str(db)])
    assert result.exit_code == 0
    assert "pay-flow" in result.output


def test_audit_clean(tmp_path):
    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(app, ["audit", "--db", str(db)])
    assert result.exit_code == 0
    assert "OK" in result.output


def test_read_commands_refuse_missing_db(tmp_path):
    missing = tmp_path / "nope" / "lore.db"
    for cmd in (["list"], ["audit"], ["stats"], ["query", "x"]):
        result = runner.invoke(app, [*cmd, "--db", str(missing)])
        assert result.exit_code == 1, f"{cmd} should fail on missing DB"
        assert not missing.exists(), f"{cmd} must not create the DB"


def test_install_hooks_creates_post_commit(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    db = tmp_path / "lore.db"
    _seed(db)

    result = runner.invoke(
        app, ["install-hooks", "--repo", str(repo), "--db", str(db)]
    )
    assert result.exit_code == 0, result.output
    hook = repo / ".git" / "hooks" / "post-commit"
    assert hook.exists()
    assert hook.stat().st_mode & 0o111, "hook must be executable"
    content = hook.read_text()
    assert str(db.resolve()) in content
    assert "lore reconcile" in content


def test_hook_session_start_suggests_init_when_no_db_in_project(tmp_path):
    import json as _json

    # Fake project: has pyproject.toml (so looks_like_project == True)
    project = tmp_path / "proj"
    project.mkdir()
    (project / "pyproject.toml").write_text('[project]\nname="x"\n')
    db = project / ".lore" / "lore.db"
    result = runner.invoke(app, ["hook-session-start", "--db", str(db)])
    assert result.exit_code == 0, result.output
    payload = _json.loads(result.output)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    assert "/lore:init" in ctx
    assert "no Lore graph exists" in ctx


def test_hook_session_start_is_silent_outside_a_project(tmp_path):
    import json as _json

    # tmp_path has no project markers.
    db = tmp_path / ".lore" / "lore.db"
    result = runner.invoke(app, ["hook-session-start", "--db", str(db)])
    assert result.exit_code == 0
    payload = _json.loads(result.output)
    assert payload["hookSpecificOutput"]["additionalContext"] == "", (
        "hook must stay silent outside project-like directories"
    )


def test_hook_session_start_notes_empty_graph(tmp_path):
    import json as _json

    db = tmp_path / "lore.db"
    _seed_empty_db(db) if False else None  # placeholder; we need real seed
    from lore.graph import open_db as _open
    _open(db).close()  # materialize empty DB
    result = runner.invoke(app, ["hook-session-start", "--db", str(db)])
    assert result.exit_code == 0
    payload = _json.loads(result.output)
    assert "empty" in payload["hookSpecificOutput"]["additionalContext"].lower()
    assert "/lore:init" in payload["hookSpecificOutput"]["additionalContext"]


def test_hook_session_start_injects_operating_directive_when_populated(tmp_path):
    import json as _json

    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(app, ["hook-session-start", "--db", str(db)])
    assert result.exit_code == 0, result.output
    ctx = _json.loads(result.output)["hookSpecificOutput"]["additionalContext"]
    # Must mention the MCP tools and the operating rules — this is the
    # whole point of nudging the model every session.
    assert "lore_query" in ctx
    assert "lore_add_node" in ctx or "lore_add_edge" in ctx
    assert "lore-usage" in ctx


def test_hook_post_tool_use_silent_for_non_bash_tool(tmp_path):
    import json as _json

    db = tmp_path / "lore.db"
    _seed(db)
    payload = _json.dumps({"tool_name": "Edit", "tool_input": {}})
    result = runner.invoke(
        app, ["hook-post-tool-use", "--db", str(db)], input=payload
    )
    assert result.exit_code == 0
    assert _json.loads(result.output)["hookSpecificOutput"]["additionalContext"] == ""


def test_hook_post_tool_use_silent_when_command_is_not_git_commit(tmp_path):
    import json as _json

    db = tmp_path / "lore.db"
    _seed(db)
    payload = _json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "ls -la"}}
    )
    result = runner.invoke(
        app, ["hook-post-tool-use", "--db", str(db)], input=payload
    )
    assert result.exit_code == 0
    assert _json.loads(result.output)["hookSpecificOutput"]["additionalContext"] == ""


def test_hook_post_tool_use_silent_when_db_missing(tmp_path):
    import json as _json

    db = tmp_path / "missing.db"  # never created
    payload = _json.dumps(
        {"tool_name": "Bash", "tool_input": {"command": "git commit -m x"}}
    )
    result = runner.invoke(
        app, ["hook-post-tool-use", "--db", str(db)], input=payload
    )
    assert result.exit_code == 0
    assert _json.loads(result.output)["hookSpecificOutput"]["additionalContext"] == ""


def test_verify_updates_last_verified_at(tmp_path):
    import json as _json

    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(app, ["verify", "pay-flow", "--db", str(db)])
    assert result.exit_code == 0, result.output
    assert "last_verified_at=" in result.output

    from lore.graph import get_node, open_db as _open
    conn = _open(db)
    node = get_node(conn, "pay-flow")
    assert node is not None
    assert node["metadata"].get("last_verified_at"), (
        "last_verified_at must be set after verify"
    )


def test_verify_unknown_node_fails(tmp_path):
    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(app, ["verify", "ghost", "--db", str(db)])
    assert result.exit_code == 1


def test_install_hooks_refuses_non_git(tmp_path):
    not_a_repo = tmp_path / "plain"
    not_a_repo.mkdir()
    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(
        app, ["install-hooks", "--repo", str(not_a_repo), "--db", str(db)]
    )
    assert result.exit_code == 1
    assert "not a git repository" in result.output


def test_install_hooks_refuses_to_clobber(tmp_path):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / ".git" / "hooks").mkdir(exist_ok=True)
    existing = repo / ".git" / "hooks" / "post-commit"
    existing.write_text("#!/bin/sh\necho custom\n")
    db = tmp_path / "lore.db"
    _seed(db)
    result = runner.invoke(
        app, ["install-hooks", "--repo", str(repo), "--db", str(db)]
    )
    assert result.exit_code == 1
    assert "already exists" in result.output
    assert existing.read_text() == "#!/bin/sh\necho custom\n", (
        "must not overwrite without --force"
    )

    result2 = runner.invoke(
        app, ["install-hooks", "--repo", str(repo), "--db", str(db), "--force"]
    )
    assert result2.exit_code == 0
    assert "lore reconcile" in existing.read_text()


def test_export(tmp_path):
    db = tmp_path / "lore.db"
    _seed(db)
    out = tmp_path / "export"
    result = runner.invoke(app, ["export", "--db", str(db), "--out", str(out)])
    assert result.exit_code == 0
    assert (out / "flow" / "pay-flow.md").exists()

"""Tests for `lore install-claude` and the underlying template installer."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from lore.cli.main import app
from lore.templates import SNIPPET_BEGIN, SNIPPET_END, install

runner = CliRunner()


def test_install_into_empty_project(tmp_path: Path) -> None:
    report = install(tmp_path)

    commands = tmp_path / ".claude" / "commands" / "lore"
    skills = tmp_path / ".claude" / "skills"

    assert (commands / "init.md").exists()
    assert (commands / "audit.md").exists()
    assert (commands / "show.md").exists()
    assert (commands / "recent.md").exists()
    assert (commands / "impact.md").exists()
    assert (skills / "lore-capture.md").exists()

    claude_md = (tmp_path / "CLAUDE.md").read_text()
    assert SNIPPET_BEGIN in claude_md
    assert SNIPPET_END in claude_md
    assert any(line.startswith("write") for line in report)


def test_install_appends_to_existing_claude_md(tmp_path: Path) -> None:
    existing = tmp_path / "CLAUDE.md"
    existing.write_text("# Project rules\n\nSome instructions.\n")

    install(tmp_path)

    merged = existing.read_text()
    assert "# Project rules" in merged
    assert SNIPPET_BEGIN in merged
    assert merged.index("# Project rules") < merged.index(SNIPPET_BEGIN)


def test_install_is_idempotent_without_force(tmp_path: Path) -> None:
    install(tmp_path)
    claude_md_before = (tmp_path / "CLAUDE.md").read_text()

    report = install(tmp_path)

    claude_md_after = (tmp_path / "CLAUDE.md").read_text()
    assert claude_md_before == claude_md_after
    assert any("skip" in line for line in report)


def test_install_force_replaces_snippet_in_place(tmp_path: Path) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        f"# Top\n\n{SNIPPET_BEGIN}\nOLD STALE CONTENT\n{SNIPPET_END}\n\n# Bottom\n"
    )

    install(tmp_path, force=True)

    merged = claude_md.read_text()
    assert "OLD STALE CONTENT" not in merged
    assert "# Top" in merged
    assert "# Bottom" in merged
    assert SNIPPET_BEGIN in merged


def test_cli_install_claude_command(tmp_path: Path) -> None:
    result = runner.invoke(app, ["install-claude", "--target", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".claude" / "commands" / "lore" / "init.md").exists()
    assert (tmp_path / ".claude" / "skills" / "lore-capture.md").exists()
    assert (tmp_path / "CLAUDE.md").exists()

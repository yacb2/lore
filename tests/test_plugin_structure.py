"""Validate the shape of the Claude Code plugin and marketplace manifests.

This is a lightweight stand-in for `claude plugin validate` that runs in
regular pytest CI. It catches the common failure modes listed in the Claude
Code plugins-reference docs: missing required fields, wrong file locations,
and malformed frontmatter.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
PLUGIN_DIR = REPO_ROOT / "plugins" / "lore"
PLUGIN_MANIFEST = PLUGIN_DIR / ".claude-plugin" / "plugin.json"
MCP_MANIFEST = PLUGIN_DIR / ".mcp.json"
SKILLS_DIR = PLUGIN_DIR / "skills"
COMMANDS_DIR = PLUGIN_DIR / "commands" / "lore"


def _parse_frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise AssertionError(f"{path} missing frontmatter opening")
    end = text.find("\n---", 4)
    if end == -1:
        raise AssertionError(f"{path} missing frontmatter closing")
    block = text[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def test_marketplace_manifest_has_required_fields() -> None:
    data = json.loads(MARKETPLACE.read_text())
    assert data["name"] == "lore"
    assert data["owner"]["name"], "owner.name is required"
    assert "url" not in data["owner"], "owner.url is not a valid field"
    assert isinstance(data["plugins"], list) and data["plugins"], "plugins[] required"
    for p in data["plugins"]:
        assert p["name"], "plugin.name required"
        assert p["source"].startswith("./"), "plugin.source must be relative"


def test_plugin_manifest_has_required_fields() -> None:
    data = json.loads(PLUGIN_MANIFEST.read_text())
    assert data["name"] == "lore"
    assert data["version"], "version required — bump on every release"
    assert data["description"]


def test_mcp_manifest_is_valid() -> None:
    data = json.loads(MCP_MANIFEST.read_text())
    assert "mcpServers" in data
    assert "lore" in data["mcpServers"]
    server = data["mcpServers"]["lore"]
    assert server["command"], "command is required"
    assert isinstance(server.get("args", []), list)


def test_plugin_components_live_at_plugin_root_not_in_claude_plugin_dir() -> None:
    claude_plugin_dir = PLUGIN_DIR / ".claude-plugin"
    for forbidden in ("skills", "commands", "agents", "hooks", ".mcp.json"):
        assert not (claude_plugin_dir / forbidden).exists(), (
            f"{forbidden} must live at plugin root, not inside .claude-plugin/"
        )


def test_plugin_source_path_resolves() -> None:
    data = json.loads(MARKETPLACE.read_text())
    plugin_root = data.get("metadata", {}).get("pluginRoot", "./")
    source = data["plugins"][0]["source"]
    resolved = (REPO_ROOT / plugin_root / source).resolve()
    assert resolved == PLUGIN_DIR.resolve(), (
        f"marketplace source resolves to {resolved}, expected {PLUGIN_DIR}"
    )


@pytest.mark.parametrize("skill_dir", [d.name for d in SKILLS_DIR.iterdir() if d.is_dir()])
def test_skill_has_valid_frontmatter(skill_dir: str) -> None:
    path = SKILLS_DIR / skill_dir / "SKILL.md"
    assert path.exists(), f"{path} missing"
    fm = _parse_frontmatter(path)
    assert fm.get("name"), f"{path}: name required in frontmatter"
    assert fm.get("description"), f"{path}: description required"


@pytest.mark.parametrize(
    "cmd_path", sorted(p.name for p in COMMANDS_DIR.glob("*.md"))
)
def test_command_has_description(cmd_path: str) -> None:
    path = COMMANDS_DIR / cmd_path
    fm = _parse_frontmatter(path)
    assert fm.get("description"), f"{path}: description required"


def test_expected_plugin_files_present() -> None:
    expected = [
        PLUGIN_MANIFEST,
        MCP_MANIFEST,
        SKILLS_DIR / "lore-usage" / "SKILL.md",
        SKILLS_DIR / "lore-commit" / "SKILL.md",
        COMMANDS_DIR / "init.md",
        COMMANDS_DIR / "audit.md",
        COMMANDS_DIR / "show.md",
        COMMANDS_DIR / "recent.md",
        COMMANDS_DIR / "impact.md",
    ]
    missing = [str(p.relative_to(REPO_ROOT)) for p in expected if not p.exists()]
    assert not missing, f"plugin files missing: {missing}"

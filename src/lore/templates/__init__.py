"""Install-time templates: CLAUDE.md snippet, slash commands, skills."""

from __future__ import annotations

import shutil
from importlib import resources
from pathlib import Path

SNIPPET_BEGIN = "<!-- BEGIN LORE INTEGRATION — do not edit the markers -->"
SNIPPET_END = "<!-- END LORE INTEGRATION -->"


def _templates_root() -> Path:
    return Path(str(resources.files("lore.templates")))


def install(target: Path, *, force: bool = False) -> list[str]:
    """Copy commands + skill into `<target>/.claude/` and merge the snippet
    into `<target>/CLAUDE.md`. Returns a list of human-readable lines."""
    target = Path(target).resolve()
    claude_dir = target / ".claude"
    commands_dst = claude_dir / "commands" / "lore"
    skills_dst = claude_dir / "skills"
    lines: list[str] = []

    src_root = _templates_root()
    commands_src = src_root / "commands" / "lore"
    skills_src = src_root / "skills"
    snippet_src = src_root / "CLAUDE.md.snippet"

    commands_dst.mkdir(parents=True, exist_ok=True)
    skills_dst.mkdir(parents=True, exist_ok=True)

    for src in sorted(commands_src.glob("*.md")):
        dst = commands_dst / src.name
        if dst.exists() and not force:
            lines.append(f"skip  {dst.relative_to(target)} (exists — use --force)")
            continue
        shutil.copyfile(src, dst)
        lines.append(f"write {dst.relative_to(target)}")

    for src in sorted(skills_src.glob("*.md")):
        dst = skills_dst / src.name
        if dst.exists() and not force:
            lines.append(f"skip  {dst.relative_to(target)} (exists — use --force)")
            continue
        shutil.copyfile(src, dst)
        lines.append(f"write {dst.relative_to(target)}")

    snippet_text = snippet_src.read_text(encoding="utf-8").rstrip() + "\n"
    claude_md = target / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(snippet_text, encoding="utf-8")
        lines.append(f"write {claude_md.relative_to(target)} (new)")
    else:
        current = claude_md.read_text(encoding="utf-8")
        if SNIPPET_BEGIN in current:
            if not force:
                lines.append(
                    f"skip  {claude_md.relative_to(target)} "
                    "(Lore section present — use --force to replace)"
                )
            else:
                before, _, rest = current.partition(SNIPPET_BEGIN)
                _, _, after = rest.partition(SNIPPET_END)
                merged = before.rstrip() + "\n\n" + snippet_text + after.lstrip()
                claude_md.write_text(merged, encoding="utf-8")
                lines.append(f"write {claude_md.relative_to(target)} (replaced block)")
        else:
            with claude_md.open("a", encoding="utf-8") as f:
                f.write("\n" + snippet_text)
            lines.append(f"write {claude_md.relative_to(target)} (appended)")

    lines.append("")
    lines.append("Done. Restart Claude Code to pick up the new skill and commands.")
    return lines

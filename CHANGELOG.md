# Changelog

All notable changes to Lore are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.6] — 2026-04-22

### Fixed
- Slash commands now resolve as `/lore:init`, `/lore:audit`, `/lore:probe`, etc. instead of the doubled-namespace `/lore:lore:init`. The command files lived in `plugins/lore/commands/lore/` which Claude Code interpreted as an extra namespace level. Flattened to `plugins/lore/commands/`.

## [0.0.5] — 2026-04-22

### Added
- `/lore:probe <path>` slash command (model: haiku) — audit a Lore graph that
  lives in another project without switching working directory.
- `graph.audit()` now reports graph-wide counts: `nodes_total`, `edges_total`,
  `nodes_by_type`, `nodes_by_status`, `edges_by_relation`, `last_mutation_at`.
- `lore audit --json` for structured output (consumed by `/lore:probe`).

### Fixed
- **Read-only CLI commands no longer create a phantom DB** when `--db` points
  to a missing file. `list`, `show`, `query`, `variants`, `audit`, `export`,
  `stats` now exit with code 1 and a clear message. Only `lore init` creates
  a DB.
- **MCP server refuses to start against a missing DB.** Prevents the common
  footgun where Claude Code is launched from a parent directory (e.g. a
  workspace root instead of the actual project root) and all graph mutations
  silently land in a fresh `.lore/lore.db` at the wrong location. The server
  now logs the resolved DB path on startup.

### Changed
- Plugin `.mcp.json` simplified: the `--db .lore/lore.db` arg was redundant
  with the CLI default and is now omitted. Resolution still happens relative
  to Claude Code's cwd.
- Documentation and slash commands clarified to state that Lore's "project"
  can be a single repo **or** a workspace containing multiple repos/packages.
  `SKILL.md`, `README.md`, `/lore:init` and `/lore:bootstrap` now explicitly
  describe both layouts; `/lore:bootstrap` auto-detects `single_repo` vs
  `workspace` and adjusts its scan patterns accordingly.

## [Initial] — before this session
- Initial repo scaffolding.
- PRD v2 approved (MCP + SQLite architecture).

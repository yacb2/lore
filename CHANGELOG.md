# Changelog

All notable changes to Lore are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.0.13] — 2026-04-23

### Changed
- **`/lore:bootstrap` caps are now tiered by project size.** The old
  hard cap (15 modules / 30 capabilities / 50 flows) was designed for
  small-to-medium projects and silently truncated on larger codebases.
  New tiers: small ≤5/15/25, medium 15/40/70, large 50/120/200. Caps
  can still be exceeded if the codebase warrants it, with a
  `truncated: true` flag + note in the proposal.
- **Explicit multi-repo workspace guidance** in bootstrap prompt: one
  module per sibling repo / independent package, even if that exceeds
  a small-project cap. Cross-cutting concerns (auth, multi-tenancy,
  observability) get their own module node; `rule` nodes are added in
  a separate pass and explicitly NOT inferred during the initial
  bootstrap scan (prevents rule inflation from speculative scanning).

## [0.0.12] — 2026-04-23

### Added
- **`lore verify <id>` CLI + `/lore:verify <id>` slash command.**
  Convenience wrapper that updates `metadata.last_verified_at` to
  today. Closes the reconcile loop: after re-inspecting a node's
  referenced code, one command marks it fresh. Without this, staleness
  signal degraded over time as nobody bothered to construct the full
  `lore_update_node(metadata_patch=…)` call by hand.
- **`metadata.links` convention** for rich cross-references. Each
  node can carry a list of `{title, url, type}` pointers to PRDs,
  design docs, RFCs, incidents, tickets. Documented in `SKILL.md`.
  Aligns with the Lore vision of "node as central reference page".
- **`/lore:show` renders nodes as readable Markdown briefings**:
  Identity → Body (verbatim) → Links section (from `metadata.links`)
  → References section (source_ref, provenance, verification) →
  Relations (incoming/outgoing grouped by relation) → Raw metadata
  (leftovers). Dramatic improvement over the old "dump fields" view.
- **`SKILL.md` guidance on `source_ref`**: when adding or updating a
  node during a session that just touched code, the node MUST carry
  `source_ref` pointing at the edited/read path. Closes the
  auto-enrichment loop so reconcile has something to detect drift
  against without manual bookkeeping.

### Notes
- This release moves Lore closer to the stated vision: each node
  becomes a "landing page" for a concept — body explains it, links
  navigate outward to external material, references anchor it in
  code. `/lore:show` is now useful as a standalone briefing tool.

## [0.0.11] — 2026-04-23

### Changed
- **`lore reconcile` is now status-aware.** Nodes whose `status="draft"`
  point at files that do not (yet) exist are classified as `planned`
  (informational), not `dead_refs` (actionable drift). Rationale:
  Lore captures both implemented *and* planned architecture; a draft
  node describing an endpoint that hasn't been coded yet is not a
  broken reference, it is a forward-looking spec. Surfaced in a
  dedicated `planned` array in the JSON output and a separate section
  in the text output. Does not affect the exit code — the CLI still
  exits 0 on "no drift" even when there are planned items.

### Notes
- Observed in real-world testing (echo_lab_ws): after a Sonnet
  bootstrap, 9 flows had `source_ref` values that looked like
  hallucinations but turned out to be genuine forward-looking
  architecture planned but not yet implemented. Marking those
  nodes `status="draft"` now cleanly separates "plan vs code drift"
  from "graph vs code rot".

## [0.0.10] — 2026-04-23

### Changed
- **`/lore:bootstrap` now defaults to Sonnet**, not Haiku, for the
  discovery sub-agent. Bootstrap is infrequent and its output seeds
  every future Lore operation — precision matters more than cost.
  Observed Haiku runs on real projects (echo_lab_ws) fabricated
  `source_ref` values (plausible-looking Django paths that did not
  exist). Sonnet is more conservative. Haiku remains available as
  opt-in via `.lore/config.json → models.exploration: "haiku"`.
- **`lore stats` now shows an estimated token count** alongside the
  bytes exchanged for each tool and for the totals. Uses a 0.3
  bytes-per-token heuristic (honest proxy — the MCP server cannot
  measure true tokens from the model's side).

### Notes
- Model routing audit done for all slash commands. Read-only commands
  (`/lore:audit`, `/lore:reconcile`, `/lore:probe`, `/lore:recent`)
  continue on Haiku — they cannot produce bad data. Write-path
  commands (`/lore:init`, `/lore:bootstrap`) already ran on the
  caller's model (Sonnet by default); structural prompt fixes in
  v0.0.8 plus this model default address the reliability gap that
  surfaced during v0.0.5 testing.

## [0.0.9] — 2026-04-23

### Added
- **`SessionStart` plugin hook.** On every new Claude Code session with
  the Lore plugin loaded, runs `lore reconcile --quiet` against the
  local `.lore/lore.db`. Silent when there is no DB and when the graph
  is clean; one-line drift summary otherwise. No-op outside of projects
  with a Lore graph. This closes the loop where edits made between
  sessions went unnoticed.
- **`lore install-hooks --repo <path>` CLI.** Installs a git
  `post-commit` hook in the target repo that runs `lore reconcile
  --since HEAD~1 --quiet` after every commit. Non-blocking: a failing
  reconcile never aborts a commit. Workspace-aware: designed to be run
  once per repo in a multi-repo workspace, all pointing at the same
  `--db` path so a single graph sees drift from any repo.

### Notes
- The SessionStart hook is light (one `test -f` + one reconcile when
  the DB exists). Users who prefer not to run it can remove
  `plugins/lore/hooks/hooks.json` or disable the plugin per project.
- The git post-commit hook is opt-in (`lore install-hooks` is never run
  automatically). Reconcile is filtered by `--since HEAD~1` so only
  files changed in the commit itself are checked.

## [0.0.8] — 2026-04-23

### Added
- `lore reconcile` CLI command + `/lore:reconcile` slash command
  (model: haiku). Detects drift between code and graph without mutating
  anything: `dead_refs` (source_ref points at a file that no longer
  exists), `stale` (last_verified_at older than `--stale-days`, default
  90), `never_verified` (has source_ref but never marked verified).
  Supports `--since <git-rev>` to restrict the scan to files changed
  since that rev; falls back to a full scan with a warning when the
  project is not a git repo. Exits 0 on clean, 1 on drift — ready to
  be wired into hooks.
- `src/lore/lifecycle.py` module holding the reconcile engine (8 new
  tests).

### Fixed
- `/lore:init` and `/lore:bootstrap` now require a mandatory
  verification step before claiming success: Claude must call
  `lore_list` / `lore_audit` after persisting, compare the returned
  count to the number of items it intended to persist, and report
  FAILURE on mismatch instead of fabricating a success message. This
  closes the hallucination failure mode observed during v0.0.4/v0.0.7
  testing where `/lore:init` claimed to have seeded 7 modules without
  ever calling `lore_add_nodes`.

## [0.0.7] — 2026-04-22

### Fixed
- `tests/test_plugin_structure.py` updated to reflect the flattened
  `commands/` layout from v0.0.6. Also added `probe.md` to the expected
  files list so future renames don't silently break it.

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

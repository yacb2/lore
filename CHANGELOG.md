# Changelog

All notable changes to Lore are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] — 2026-04-29

### Changed
- CHANGELOG: removed internal project names from earlier release notes
  ahead of making the repository public. The technical lessons remain;
  only the proper nouns are gone.

## [0.1.1] — 2026-04-29

### Added
- GitHub Actions CI running ruff + pytest on Python 3.11 and 3.12 for
  every push and PR.
- README banner clarifying the pre-1.0, solo-maintained status of the
  project.

### Fixed
- Lint cleanup across `src/` and `tests/` so the new CI passes from day 1.

## [0.1.0] — 2026-04-29

First minor bump — driven by an audit of the plugin's real-world usage in
three real-world projects in active use. Targets the
classes of mistake LLMs were repeatedly making and adds the telemetry we
need to keep iterating.

### Added
- **`lore_schema` MCP tool** — read-only descriptor of node types,
  statuses, allowed relations per `(from_type, to_type)` pair, recommended
  metadata vocabulary, id format, and body minimums. The LLM can call it
  before a batch write instead of recovering from `SchemaError` rollbacks.
- **Soft validation warnings on writes** — `add_node` / `add_nodes` now
  return a `warnings` list per node. Triggers:
  - `body_thin`: `capability` / `flow` with body < 80 chars.
  - `missing_source`, `non_canonical_source`: `metadata.source` outside
    the canonical vocabulary (`user_stated | user_confirmed |
    inferred_from_code | inferred_from_conversation | code_change |
    scan | incident | manual`).
  - `missing_confidence`, `non_canonical_confidence`,
    `missing_source_ref`.
  - `orphan`: freshly created `rule` / `decision` with no outgoing edges.
  Warnings never block persistence.
- **Extended audit_log telemetry** — new columns: `node_type`,
  `latency_ms`, `warnings_count`, `client_id`. Aditive migration runs
  automatically on `open_db`. Opt-out via `LORE_TELEMETRY=0`.
- **`lore quality` CLI command** — content-quality snapshot:
  body/source/source_ref coverage by type, list of thin-body nodes,
  non-canonical sources, orphans by type, top schema errors, warnings
  distribution. Complements `lore audit` (structural integrity).
- **`lore stats --by-day --errors`** — temporal breakdown of calls /
  errors / warnings, plus top error messages with first/last seen.
  Supports `--json` for piping.

### Changed
- **`SchemaError` messages now include the relations valid for the exact
  `(from_type, to_type)` pair** instead of dumping all 9 relations. When
  no relation is valid for the pair, the message lists the reachability
  map for the source type ("From 'rule' you can reach: …").
- **Invalid id messages are actionable** — they list the bad characters
  detected and suggest a kebab-case fix (`Invalid id 'module.frontend.x'.
  Bad chars: ['.']. … Did you mean 'module-frontend-x'?`).
- **`lore_add_node(s)` minimal default response** — returns
  `{id, type, status, warnings}` by default; the full persisted node is
  available via `return_mode='full'`. Cuts NS-Backoffice-class write
  output ~3× without losing data the LLM can't re-derive.

### Notes for upgrades
- Existing `.lore/lore.db` files are upgraded in place on next open.
- The `metadata.source` enum is *advisory* in this release: non-canonical
  values still persist with a warning. A future release may tighten this
  if the warning channel proves effective.

## [0.0.20] — 2026-04-25

### Added
- **`/lore:sync` slash command** — closes the loop reconcile cannot:
  given a git revision (e.g. `HEAD~10`, `v2.24.0`, a sha), diff the
  code against `HEAD`, classify each changed file as either *mapped*
  (already pointed at by `metadata.source_ref` on some node) or
  *unmapped* (candidate for a new node), and walk both lists with
  the user before persisting. Boring files (lockfiles, CSS, images,
  docs) are filtered. Persistence requires per-batch confirmation;
  every new node carries `inferred_from_code` provenance with
  `confidence: medium` and a fresh `last_verified_at`.
- **`lore sync-plan` CLI subcommand** — read-only JSON dossier that
  the slash command consumes. Emits `{repos: [...], totals: {...}}`
  shape for any git revision, multi-repo workspaces included. Exits
  1 when there are unmapped files so it can be used in scripts.
- **`src/lore/sync.py` module** — extracts `find_git_repos`,
  `is_boring`, and `compute_sync_report` so the PostToolUse
  checkpoint hook and the sync command share one implementation.

### Changed
- **PostToolUse `git commit` hook now delegates to `lore.sync`** —
  same behavior, less duplication. Drops the inlined helpers
  introduced in v0.0.19.

### Why this release
- v0.0.19 made the model *aware* a commit had happened. v0.0.20 gives
  the user (and the model) the tooling to act on it, plus a way to
  catch up after a period of drift. NS Backoffice has 48h of
  unreflected commits; running `/lore:sync HEAD~15` should walk the
  whole gap in one session.

## [0.0.19] — 2026-04-25

### Changed
- **`lore-usage` skill description rewritten with explicit triggers** —
  the previous description leaned on abstract terms ("business
  knowledge, flows, capabilities") that the model rarely recognized
  during code-writing sessions, so the skill went un-invoked even when
  it should have fired. The new description names concrete code
  artifacts (endpoints, models, management commands, signals,
  serializers, validators, hooks, Vue pages) and uses the `ALWAYS use
  this skill when…` pattern that proven aidex skills rely on. Also
  enumerates skip conditions (pure refactors, dependency bumps,
  CSS-only changes) so the model has a clear off-switch.
- **SessionStart hook always injects an operating directive when the
  graph is populated** — previously the hook was silent unless
  reconcile detected drift, which meant a healthy graph received zero
  reinforcement turn after turn and the `lore-usage` skill drifted out
  of the model's working set. Now every session that has a Lore graph
  gets a short directive listing the read-first / write-on-decision
  rules, the provenance keys to set, and a pointer to the skill for
  full conventions. Drift summary, when present, is appended.

### Added
- **PostToolUse hook tracks `git commit` as a Lore checkpoint** — new
  `lore hook-post-tool-use` CLI command, registered under PostToolUse
  with matcher `Bash`. When the model runs `git commit`, the hook
  inspects the resulting HEAD commit across every git repo under the
  cwd, maps changed files against `metadata.source_ref` on graph
  nodes, and injects a structured nudge listing (a) files already
  mapped to nodes that may need updates and (b) unmapped files that
  could introduce new flows/rules/capabilities. Boring suffixes
  (lockfiles, CSS, images, docs) are filtered out. Stays silent when
  the tool isn't Bash, the command isn't `git commit`, or the graph
  doesn't exist yet — the hook never blocks a commit.

### Why this release
- Empirical observation across NS Backoffice (2026-04-23 → 2026-04-25):
  170-node graph received zero writes for ~48h despite 15+ commits
  introducing new commands, flows, and rules in code. The
  auto-invocation pathway through skill descriptions alone is too
  weak to keep the graph fresh during normal development. This
  release moves the load-bearing signal from probabilistic
  (description match) to deterministic (hook-injected context every
  session, plus a hard checkpoint at every commit).

## [0.0.18] — 2026-04-23

### Added
- **`/lore:stats` slash command** — wrapper over `lore stats` CLI with
  an optional `--since <iso>` arg. Was missing from the slash surface
  despite existing in the CLI since v0.0.2; users naturally tried
  `/lore:stats` and got "command not found". Oversight corrected.

## [0.0.17] — 2026-04-23

### Fixed
- **`part_of` now allows `module → module`** — the missing triple that
  blocked hierarchical workspace layouts. Observed during NS Backoffice
  testing: the new hierarchical `/lore:init` correctly proposed 2 repos
  + 40 inner modules, but when persisting the `part_of` edges the
  schema rejected them because only `flow/capability/form/event →
  module` was allowed. The Claude in the session fell back to
  `depends_on`, which has *completely different* semantics (functional
  dependency, not composition) and would produce wrong answers for
  any query like "what modules are inside backend?" or "what depends
  on backend?".

  The fix adds `("part_of", "module", "module")` to `ALLOWED_RELATIONS`.
  Other part_of triples remain unchanged. `module → flow` and
  `module → capability` are still disallowed (those are inverted).

### Migration
- Existing graphs that used `depends_on` as a workaround for
  hierarchy should relabel those edges. For NS Backoffice
  specifically, the 40 edges from inner modules to their repo
  module should become `part_of`. Procedure: in the session, delete
  and recreate each edge with the correct relation, or use SQL
  directly:
  ```sql
  UPDATE edges SET relation='part_of'
  WHERE relation='depends_on'
    AND from_id IN (SELECT id FROM nodes WHERE type='module')
    AND to_id IN ('backend', 'frontend');  -- adjust parent ids
  ```

## [0.0.16] — 2026-04-23

### Changed
- **`/lore:init` rewritten as the single smart setup command.** Merges
  what used to be `/lore:init` + `/lore:bootstrap` into one flow, asks
  the user how to discover modules, and handles both layouts:
  - **Workspace**: detects child repos (backend/, frontend/, packages),
    offers three paths: **hierarchical** (recommended — repos as
    top-level modules, inner modules per repo with `part_of` edges),
    **flat** (skip repo level), **manual** (user lists names).
  - **Single repo**: offers **auto-scan** (Sonnet) or **manual**.
  - No matter the path, mandatory verification step applies
    (`lore_audit` count comparison, report FAILURE on mismatch).
- **`/lore:bootstrap` repurposed as the re-scan command.** Explicitly
  requires `/lore:init` to have run first (checks for existing
  modules). Use it to extend the graph with additional
  capabilities/flows after initial setup.

### Added
- **`lore hook-session-start` CLI command**, invoked by the
  `SessionStart` plugin hook. Returns Claude Code-compatible JSON with
  `additionalContext` that nudges the user appropriately:
  - No DB and the cwd looks like a codebase (has `pyproject.toml`,
    `package.json`, `.git`, or children with manifests) → suggests
    running `/lore:init`.
  - DB exists but empty → suggests `/lore:init` to seed modules.
  - DB exists with nodes → runs reconcile; if drift, surfaces a
    summary so Claude can mention it when relevant in the session.
  - Nothing looks like a project → silent.
- **`hooks/hooks.json`** now delegates the SessionStart event to this
  CLI instead of the old inline shell test.

### Rationale
- User feedback: "why do I have to run two commands when init is
  always followed by bootstrap?" Fair — separation wasn't load-bearing
  outside of niche cases. One command, one decision.
- User feedback: "why do I have to create `.lore/` manually?" Already
  fixed in v0.0.15 (MCP auto-creates) — this release fixes the
  follow-up gap: after install, what do I do? The SessionStart
  context nudge answers that question automatically.
- User feedback: "in a multi-repo workspace the init should suggest
  hierarchy — repos as top-level, apps/features as children." The
  new init's hierarchical path does exactly this.

## [0.0.15] — 2026-04-23

### Changed
- **MCP server now always auto-creates the database.** Dropped the
  "refuse if `.lore/` doesn't exist" half-measure from v0.0.14. Forcing
  users to `mkdir .lore/` before first use was friction without real
  benefit: the plugin's job is to work out of the box, not to
  second-guess user intent.

  The original footgun (Claude Code launched from the wrong directory
  → graph materialized at the wrong path) is now prevented with
  signals instead of refusals:
  - Every MCP start logs `using database at <absolute path>` to
    stderr — unambiguous where writes are going.
  - First-time materialization prints a loud "creating new Lore graph"
    banner with the path, an explanation, and the exact command to
    delete the empty graph if it was a mistake. Banner only fires once
    (on the very first start for a path), so it remains a real signal
    and not noise.

  Net effect: open Claude Code anywhere → `/lore:init` → works. No
  `mkdir`, no `lore init` shell ceremony, no "Reconnect" dance.

## [0.0.14] — 2026-04-23

### Changed
- **MCP server now relaxes `refuse-to-start` when `.lore/` exists.** The
  v0.0.9 refuse protected against Claude Code launching from a parent
  directory and silently writing the graph to the wrong place. But
  refusing across the board created a poor first-run experience: a
  brand-new Lore project shows "MCP failed" in the plugin UI with no
  obvious next step, stderr hidden by Claude Code. The user has to run
  `lore init` in a terminal and click Reconnect.

  New behavior, which keeps the footgun guard and removes the friction:
  - DB exists → open it. (same as before)
  - DB missing but parent `.lore/` directory exists → auto-create the
    DB inside it. Creating the `.lore/` folder is an explicit opt-in
    to Lore for this project; auto-creating the DB there is safe.
  - Neither DB nor `.lore/` parent exist → refuse with a clear error
    message suggesting `mkdir .lore/` or `lore init`.

  Observed during dogfooding on a Django/Vue project: the first-run refuse
  behavior was the blocker.

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
- Observed in real-world testing on a media-pipeline project: after a Sonnet
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
  Observed Haiku runs on real projects fabricated
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

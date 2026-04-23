---
description: Auto-discover this project's modules, capabilities and flows by scanning the code with a cheap model, then propose a seed graph for the user to approve. Ideal for onboarding a large existing codebase.
allowed-tools: [Bash, Read, Glob, Grep, Agent]
---

Bootstrap Lore on a larger project using an economical scan. The project
may be a single repo **or** a workspace containing several repos/packages
— the scan handles both layouts.

1. **Ensure the DB exists.** If `.lore/lore.db` does not exist, run
   `lore init` first.

2. **Delegate discovery to a sub-agent.** Bootstrap is run infrequently
   and the result seeds every future Lore operation, so **precision
   matters more than cost**. Default to Sonnet. Haiku can be selected
   explicitly for cheap-but-noisier scans on small / well-documented
   codebases, or when the user is exploring. Resolution order:

   - If `.lore/config.json` has `models.exploration`, honour it verbatim.
   - Otherwise default to **`sonnet`**.

   Rationale: prior Haiku runs have been observed to fabricate
   `source_ref` values — file paths that look plausible given framework
   conventions but do not exist in the target repo. Sonnet's structural
   reasoning makes this failure mode rarer. Users who want Haiku can
   opt in with `{"models": {"exploration": "haiku"}}`.

   Invoke the `Agent` tool with:
   - `subagent_type`: `"general-purpose"`
   - `model`: configured exploration model (default `"sonnet"`)
   - `description`: `"Scan repo for Lore seed"`
   - `prompt`: (use the template below, adapted to the current project)

   ```
   Scan this directory and produce a compact proposal for a Lore seed
   graph. The directory may be a single repo OR a workspace that holds
   multiple repos/packages side by side. Handle both. Do NOT write to
   Lore — only return a JSON proposal for the caller to review.

   Steps:
   1. Detect layout:
      - **Single repo**: one `package.json` / `pyproject.toml` / `go.mod` /
        `Cargo.toml` at the root, a single `src/` or equivalent.
      - **Workspace**: no manifest at the root, or multiple child dirs that
        each contain their own manifest (`*/package.json`, `*/pyproject.toml`,
        `*/.git/`). Common markers: `*_ws/`, `apps/`, `packages/`,
        `services/`, or sibling folders like `backend/` + `frontend/`.
      When in doubt, treat sibling dirs with their own manifest as separate
      modules.
   2. Identify the app/workspace name from the top-level manifest or
      README. Capture the primary repository URL if present (may be
      one-per-module in a workspace).
   3. List the source directories that look like business modules:
      - Single repo: `src/*/`, `lib/*/`, `apps/*/`, `services/*/`.
      - Workspace: each child dir that has its own manifest or `.git/` is a
        module. Go one level deeper for their internal sub-modules only if
        they are clearly business-relevant (not `utils/`, `config/`).
      Ignore tests, scripts, build output, vendor dirs, `_shared/`,
      `_scratch/`.
   4. For each module, skim file names and a handful of file headers to
      guess 1-3 candidate capabilities (what the module does, not how).
   5. Identify obvious flows: CLI subcommands, HTTP route handlers, event
      consumers, queue workers. Capture entry-point file + function name.

   Return a single JSON object (no prose) with this shape:
   {
     "layout": "single_repo" | "workspace",
     "app_name": "...",
     "repository": "...",
     "language": "<primary natural language of docs/comments, e.g. 'en' or 'es'>",
     "modules": [{"id": "module-<slug>", "title": "...", "path": "...", "repo": "<repo-path-if-workspace>"}],
     "capabilities": [{"id": "capability-<slug>", "title": "...", "module_id": "module-<slug>"}],
     "flows": [{"id": "flow-<slug>", "title": "...", "module_id": "module-<slug>", "entry_point": "path:function"}],
     "truncated": false,
     "truncated_note": null
   }

   Caps (precision over recall — skip anything ambiguous):
   - Small project (≤5 modules visible): 5–10 modules, 15 capabilities,
     25 flows.
   - Medium project (5–15 modules): 15 modules, 40 capabilities, 70 flows.
   - Large project (15+ modules, multi-repo workspace): up to 50
     modules, 120 capabilities, 200 flows. Do NOT force-fit a large
     project into a small cap — better to cover real ground than to
     arbitrarily truncate. If the codebase is substantially larger than
     200 flows' worth, return the most prominent 200 plus a field
     `truncated: true` with a short note on what was skipped.

   In a multi-repo workspace, produce one `module` per sibling repo or
   per independent package, even if that exceeds the small-project
   cap. Cross-cutting concerns (auth, multi-tenancy, workspace
   isolation, observability) deserve their own `module` plus, where
   applicable, `rule` nodes — but rules are added in a separate pass,
   do NOT infer them during this scan.
   ```

3. **Show the proposal to the user** in a compact summary: count per type,
   sample of each, and the detected language. Ask for approval. If the
   user wants edits (drop some modules, rename), apply them in-memory.

4. **Persist in one transaction** using batch tools:
   - `lore_add_nodes([...])` for all modules, capabilities, flows.
   - `lore_add_edges([...])` for `part_of` (capability → module, flow → module) and `implements` (flow → capability).
   - Every node's `metadata` must include:
     - `source: "inferred_from_code"`
     - `confidence: "medium"` (bootstrap inferences are never `high`)
     - `source_context: "bootstrap scan <date>"`
     - `source_ref: "<path[:line]>"` when the node maps to a concrete file
     - `last_verified_at: "<today ISO>"`

   Remember the counts you asked `lore_add_nodes` / `lore_add_edges` to
   persist — call them `N_nodes` and `N_edges`.

5. **Mandatory verification — do NOT skip this.** Hallucinating a
   success message without verifying is the most common failure mode of
   this command.

   a. Call `lore_audit()`. The report includes `nodes_total` and
      `edges_total`.
   b. Compare `nodes_total` to `N_nodes` and `edges_total` to `N_edges`.
      They should match (or exceed, if the DB already had content).
   c. Report exactly one of two outcomes:
      - **Match**: "Sembrados N_nodes nodos y N_edges edges. Verificado
        con `lore_audit`." Then surface any audit findings.
      - **Mismatch**: "FAILURE: pedí sembrar N_nodes / N_edges pero la
        DB contiene <nodes_total> / <edges_total>. Las escrituras no
        persistieron." Stop — do not retry silently.

6. **Create `.lore/config.json`** if it doesn't exist, seeded with the
   detected language, app name and default model routing:
   ```json
   {
     "language": "es",
     "app_name": "...",
     "models": { "exploration": "haiku", "write": "sonnet" }
   }
   ```

Keep the final summary brief: how many nodes/edges were persisted, and a
reminder that the user should review `inferred_from_code` nodes with `lore
stats` and `lore audit --provenance` (planned) as they work on the project.

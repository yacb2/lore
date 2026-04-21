---
description: Auto-discover this project's modules, capabilities and flows by scanning the repo with a cheap model, then propose a seed graph for the user to approve. Ideal for onboarding a large existing codebase.
allowed-tools: [Bash, Read, Glob, Grep, Agent]
---

Bootstrap Lore on a larger project using an economical scan:

1. **Ensure the DB exists.** If `.lore/lore.db` does not exist, run
   `lore init` first.

2. **Delegate discovery to a Haiku sub-agent** to keep the cost low. Invoke
   the `Agent` tool with:
   - `subagent_type`: `"general-purpose"`
   - `model`: `"haiku"`
   - `description`: `"Scan repo for Lore seed"`
   - `prompt`: (use the template below, adapted to the current project)

   ```
   Scan this repository and produce a compact proposal for a Lore seed
   graph. Do NOT write to Lore — only return a JSON proposal for the
   caller to review.

   Steps:
   1. Identify the app name from package.json, pyproject.toml, Cargo.toml,
      go.mod, or README.md. Also capture the primary repository URL if
      present.
   2. List the top-level source directories that look like business
      modules (src/*/, lib/*/, apps/*/, services/*/). Ignore tests,
      scripts, build output, vendor dirs.
   3. For each module, skim file names and a handful of file headers to
      guess 1-3 candidate capabilities (what the module does, not how).
   4. Identify obvious flows: CLI subcommands, HTTP route handlers, event
      consumers, queue workers. Capture entry-point file + function name.

   Return a single JSON object (no prose) with this shape:
   {
     "app_name": "...",
     "repository": "...",
     "language": "<primary natural language of docs/comments, e.g. 'en' or 'es'>",
     "modules": [{"id": "module-<slug>", "title": "...", "path": "..."}],
     "capabilities": [{"id": "capability-<slug>", "title": "...", "module_id": "module-<slug>"}],
     "flows": [{"id": "flow-<slug>", "title": "...", "module_id": "module-<slug>", "entry_point": "path:function"}]
   }

   Keep it compact: max 15 modules, 30 capabilities, 50 flows. Prefer
   precision over recall — skip anything ambiguous.
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

5. **Run `lore_audit()`** and report any findings.

6. **Create `.lore/config.json`** if it doesn't exist, seeded with the
   detected language and app name:
   ```json
   { "language": "es", "app_name": "..." }
   ```

Keep the final summary brief: how many nodes/edges were persisted, and a
reminder that the user should review `inferred_from_code` nodes with `lore
stats` and `lore audit --provenance` (planned) as they work on the project.

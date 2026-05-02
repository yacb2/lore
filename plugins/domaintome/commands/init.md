---
description: Initialize DomainTome for this project — one smart command that handles single repos and multi-repo workspaces, with scan or manual seeding.
allowed-tools: [Bash, Read, Glob, Grep, Agent]
---

Set up DomainTome for this project in a single command. Replaces the old
`init` + `bootstrap` two-step flow. Works for both first-time setup on
a brand-new project and for re-running on a project that's already
been touched.

## Step 1 — Check state

Call `dt_list(type="module")` to see if modules already exist.

- **If >0 modules** → say "DomainTome already has N top-level modules for this
  project. Use `/dt:bootstrap` to scan the code and propose
  additional capabilities/flows, or `/dt:audit` to see current
  state." Do not re-seed. Stop.
- **If 0 modules** → continue.

Also ensure the DB file exists: run `dt init --db .dt/graph.db` once
(it is a no-op if the file is already there from auto-create).

## Step 2 — Detect layout

Inspect the current directory and its immediate children:

- **Multi-repo workspace**: no top-level manifest, but two or more
  child directories each have their own `package.json`,
  `pyproject.toml`, `Cargo.toml`, `go.mod`, or `.git/`. Also look for
  obvious workspace markers: `backend/` + `frontend/`, `*_ws/` naming,
  `apps/` with per-app manifests.
- **Single repo**: one manifest at the root.
- **Unclear**: ask the user to confirm.

## Step 3 — Decide granularity (ask the user)

### Multi-repo workspace

Report what you found and offer three options. Be concrete with the
names of the repos detected:

> "I see a workspace with N repos: `<list>`. How do you want DomainTome to
> map this project?
>
> **(a) Hierarchical (recommended).** One top-level module per repo.
> Then for each repo I'll propose its own inner modules (Django apps,
> Vue features, Go packages, whatever fits the stack), with `part_of`
> edges so the hierarchy is explicit. Good for large projects where
> you want to browse by repo first and by concern second.
>
> **(b) Flat.** Skip the repo level and go straight to apps/features
> as top-level modules. Good when you already think of the project
> as one flat set of domains.
>
> **(c) Manual.** You list 3–10 module names by hand. I persist them
> as-is. No scan, no hierarchy inferred. Good when you know exactly
> what you want."

Wait for the user's answer.

### Single repo

Offer two options:

> "I see a single repo. How do you want to start?
>
> **(a) Auto-scan (recommended).** I'll scan the codebase with a
> Sonnet sub-agent and propose modules, capabilities, and flows.
> You review and approve.
>
> **(b) Manual.** You list 3–10 module names. I persist them. No
> scan, no inference. Capabilities and flows come later as you work."

Wait for the user's answer.

## Step 4 — Execute the chosen path

### (a) Hierarchical — workspace

1. Propose the N repos as top-level modules. Kebab-case, derived from
   the repo directory names (`backend/` → `backend`, `frontend/` →
   `frontend`). Confirm names with the user.

2. For each repo, delegate to the Sonnet sub-agent (see template
   below) to identify inner modules. Cap per-repo: 20 inner modules,
   40 capabilities, 60 flows. Total budget across all repos: 50
   modules (repos + inner), 120 capabilities, 200 flows.

3. Collect one combined proposal. Show the user a hierarchical tree:

   ```
   backend
     ├── auth
     ├── billing
     ├── accounting
     └── ...
   frontend
     ├── billing-ui
     ├── dashboard
     └── ...
   ```

   Ask for edits before persisting.

4. Persist in one transaction:
   - `dt_add_nodes(...)` with every module (repos + inner).
   - `dt_add_edges(...)` with `part_of` from each inner module to
     its parent repo module.
   - All capability/flow nodes and their edges.
   - Every node's `metadata` must include the standard provenance
     keys (source, confidence, source_context,
     source_ref when applicable, last_verified_at).

### (b) Flat — workspace, or auto-scan — single repo

Invoke the Sonnet sub-agent with the full-project template, ignoring
the repo boundary. Persist with no repo-level parents.

### (c) Manual — either layout

Ask the user to list 3–10 kebab-case names. Persist via
`dt_add_nodes` batch. No capabilities/flows inferred. Every module
gets `source="user_stated"`, `confidence="high"`,
`last_verified_at="<today>"`.

## Step 5 — Mandatory verification (do NOT skip)

Hallucinating success without verifying was the v0.0.4 failure mode.
After the batch insert:

1. Call `dt_audit()`. Read `nodes_total` and `edges_total`.
2. Compare against the counts you asked to persist (`N_nodes`,
   `N_edges`).
3. Report exactly one outcome:
   - **Match** → "Persisted N_nodes modules and N_edges edges."
     Surface audit findings (orphans are expected on a fresh seed).
   - **Mismatch** → "FAILURE: asked to persist N_nodes / N_edges but
     the DB has <nodes_total> / <edges_total>. Writes did not land."
     Stop — do not retry silently.

## Step 6 — Next steps

Tell the user:
- Add capabilities and flows as you work (the `dt-usage` skill will
  prompt you).
- Run `/dt:audit` anytime for structural health.
- Run `/dt:reconcile` to see drift between graph and code.
- Run `/dt:bootstrap` later if you want a fresh Sonnet pass over
  the codebase to extend the graph.

---

## Sub-agent template (used by auto-scan paths)

Invoke the `Agent` tool with:

- `subagent_type`: `"general-purpose"`
- `model`: the configured exploration model (`.dt/config.json →
  models.exploration`), default **`sonnet`** (bootstrap precision
  matters, Haiku has been observed fabricating source_ref paths)
- `description`: `"Scan repo for DomainTome seed"`
- `prompt`: inline below, adapted to the current scope

```
Scan this directory and produce a compact proposal for a DomainTome seed
graph. Return JSON only, no prose.

Scope: <one-repo scope>|<workspace-inner-for-repo <name>>|<full-workspace>

Steps:
1. List top-level source directories (src/*, app/*, apps/*, lib/*,
   packages/*, services/*). Ignore tests, vendor, build output,
   node_modules, .venv, __pycache__, dist, _scratch.
2. Each business-meaningful dir is a candidate `module`. Cross-cutting
   concerns (auth, observability, infra) that clearly affect many
   modules deserve their own module.
3. For each module, skim entry-point files for 1-3 `capability` nodes
   (WHAT the module does, not how).
4. Identify obvious `flow` nodes: HTTP handlers, CLI subcommands,
   queue workers, cron jobs. Capture entry_point = "path:function".
5. Prefer precision over recall. Skip anything ambiguous.

Caps by scope:
- single repo / full workspace flat: up to 50 modules, 120 caps, 200 flows.
- workspace-inner for one repo: up to 20 modules, 40 caps, 60 flows.

Return one JSON object:
{
  "scope": "<as passed in>",
  "modules":      [{"id": "module-<slug>",   "title": "...", "path": "...", "parent_id": "<parent-module-id-or-null>"}],
  "capabilities": [{"id": "capability-<slug>", "title": "...", "module_id": "<module-id>"}],
  "flows":        [{"id": "flow-<slug>",       "title": "...", "module_id": "<module-id>", "entry_point": "path:function"}],
  "truncated": false,
  "truncated_note": null
}
```

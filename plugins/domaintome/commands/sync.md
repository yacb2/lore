---
description: Align the DomainTome graph with the code. One command, three auto-detected modes — init (no graph yet), extend (graph exists, broad re-scan), diff (changes since a git revision).
allowed-tools: [Bash, Read, Glob, Grep, Agent]
argument-hint: [git-rev]
---

`/dt:sync` is the single entry point for "make the graph reflect the
code". It replaces the old `/dt:init` + `/dt:bootstrap` + `/dt:sync`
trio. The mode is auto-detected from repo state and the presence of a
`$ARGUMENTS` git revision.

## Mode quick-reference

| Repo state                                  | Args             | Mode    | Section    |
|---|---|---|---|
| No `.dt/graph.db`, **or** DB with 0 modules | (any)            | INIT    | §INIT mode |
| DB has modules                              | no git rev       | EXTEND  | §EXTEND mode |
| DB has modules                              | git rev (`HEAD~10`, sha, tag) | DIFF | §DIFF mode |

`/dt:init` is a **permanent alias** that always lands here in INIT mode
(it predates `/dt:sync` and stays around because external docs and
muscle memory rely on it). `/dt:bootstrap` is a **deprecated alias**
that lands in EXTEND mode and emits a warning.

## Step 0 — Detect mode

1. Check if `.dt/graph.db` exists. If not → **INIT mode**.
2. Otherwise call `dt_list(type="module")`. If `items` is empty → **INIT mode**.
3. Otherwise, if `$ARGUMENTS` is non-empty (or contains `--since <rev>`) → **DIFF mode**.
4. Otherwise → **EXTEND mode**.

Announce the detected mode in one sentence before doing anything, so the
user can correct you if the heuristic misfires:

> "Detected mode: **EXTEND** (graph has 12 modules, no git rev passed).
> Continuing with a fresh sub-agent scan over the codebase."

---

## INIT mode

First-time setup. Replaces the legacy two-step `init` + `bootstrap` flow
with a single conversation.

### I.1 — Ensure the DB file

Run `dt init --db .dt/graph.db` (no-op if the file is already there from
auto-create).

### I.2 — Detect layout

Inspect the current directory and its immediate children:

- **Multi-repo workspace**: no top-level manifest, but two or more
  child directories each have their own `package.json`,
  `pyproject.toml`, `Cargo.toml`, `go.mod`, or `.git/`. Also look for
  obvious workspace markers: `backend/` + `frontend/`, `*_ws/` naming,
  `apps/` with per-app manifests.
- **Single repo**: one manifest at the root.
- **Unclear**: ask the user to confirm.

### I.3 — Decide granularity (ask the user)

#### Multi-repo workspace

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

#### Single repo

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

### I.4 — Execute the chosen path

#### (a) Hierarchical — workspace

1. Propose the N repos as top-level modules. Kebab-case, derived from
   the repo directory names (`backend/` → `backend`, `frontend/` →
   `frontend`). Confirm names with the user.

2. For each repo, delegate to the Sonnet sub-agent (see §Shared
   sub-agent template) with `scope = "workspace-inner-for-repo <name>"`.
   Cap per-repo: 20 inner modules, 40 capabilities, 60 flows. Total
   budget across all repos: 50 modules (repos + inner), 120 capabilities,
   200 flows.

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
   - `dt_add_node(nodes=[...])` with every module (repos + inner).
   - `dt_add_edge(edges=[...])` with `part_of` from each inner module to
     its parent repo module.
   - All capability/flow nodes and their edges.
   - Every node's `metadata` must include the standard provenance
     keys (`source`, `confidence`, `source_context`, `source_ref` when
     applicable, `last_verified_at`).

#### (b) Flat — workspace, or auto-scan — single repo

Invoke the sub-agent with `scope = "full-workspace"` (or
`"single-repo"`), ignoring the repo boundary. Persist with no repo-level
parents.

#### (c) Manual — either layout

Ask the user to list 3–10 kebab-case names. Persist via
`dt_add_node(nodes=[...])` batch. No capabilities/flows inferred. Every module
gets `source="user_stated"`, `confidence="high"`,
`last_verified_at="<today>"`.

### I.5 — Create `.dt/config.json`

If it doesn't exist, write it with the detected language, app name and
default model routing:

```json
{
  "language": "es",
  "app_name": "...",
  "models": { "exploration": "sonnet", "write": "sonnet" }
}
```

### I.6 — Mandatory verification (do NOT skip)

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

### I.7 — Next steps

Tell the user:
- Add capabilities and flows as you work (the `dt-usage` skill will
  prompt you).
- Run `/dt:audit` anytime for structural health.
- Run `/dt:reconcile` to see drift between graph and code.
- Run `/dt:sync` later — without args to re-scan broadly (EXTEND), or
  with a git revision to walk only what changed (DIFF).

---

## EXTEND mode

Graph is initialized; the codebase has grown or has empty placeholder
modules. Do a fresh broad scan and propose additional capabilities/flows.
This is what `/dt:bootstrap` used to do.

### E.1 — Confirm the graph is ready

`dt_list(type="module")` was already called in §Step 0; you know there
are modules. If, somehow, there are zero, fall through to INIT mode
instead.

### E.2 — Delegate discovery to a sub-agent

Extend mode runs infrequently and the result seeds future operations,
so precision matters more than cost. Default to **Sonnet**. Haiku can
be selected explicitly for cheap-but-noisier scans on small /
well-documented codebases. Resolution order:

- If `.dt/config.json` has `models.exploration`, honour it verbatim.
- Otherwise default to **`sonnet`**.

Rationale: prior Haiku runs have been observed to fabricate
`source_ref` values — file paths that look plausible given framework
conventions but do not exist in the target repo. Sonnet's structural
reasoning makes this failure mode rarer.

Invoke the sub-agent (see §Shared sub-agent template) with
`scope = "extend"`. Caps are tiered by visible project size:

- Small project (≤5 modules visible): 5–10 modules, 15 capabilities, 25 flows.
- Medium project (5–15 modules): 15 modules, 40 capabilities, 70 flows.
- Large project (15+ modules, multi-repo workspace): up to 50 modules,
  120 capabilities, 200 flows.

If the codebase is substantially larger than 200 flows' worth, return
the most prominent 200 plus `truncated: true` with a short note on
what was skipped.

### E.3 — Show the proposal

Compact summary: count per type, sample of each, detected language.
Ask for approval. If the user wants edits (drop some modules, rename),
apply them in-memory.

### E.4 — Persist in one transaction

- `dt_add_node(nodes=[...])` for all modules, capabilities, flows.
- `dt_add_edge(edges=[...])` for `part_of` (capability → module, flow →
  module) and `implements` (flow → capability).
- Every node's `metadata` must include:
  - `source: "inferred_from_code"`
  - `confidence: "medium"` (extend inferences are never `high`)
  - `source_context: "sync extend <date>"`
  - `source_ref: "<path[:line]>"` when the node maps to a concrete file
  - `last_verified_at: "<today ISO>"`

Remember the counts you asked to persist — `N_nodes` and `N_edges`.

### E.5 — Mandatory verification

Same contract as I.6: call `dt_audit()`, compare totals against
`N_nodes` / `N_edges`, report Match or FAILURE. Do not retry silently.

---

## DIFF mode

Graph and code already exist; the user is asking "what changed in code
since `<rev>` that the graph doesn't know about yet?" This is the
original `/dt:sync` flow.

This is the **only** mode that closes the loop in the opposite
direction from `/dt:reconcile`: reconcile detects rotten nodes, sync
detects code without a node.

### D.1 — Resolve scope

Parse `$ARGUMENTS` as a single git revision. If empty, default to
`HEAD~10`. Mention the chosen scope back to the user before continuing
so they can correct it.

### D.2 — Run `dt sync-plan`

```bash
dt sync-plan --since <rev>
```

The command exits 0 if everything is mapped, 1 if there are unmapped
files. Either way, parse the JSON from stdout:

```
{
  "scope": "<rev>..HEAD",
  "repos": [
    {"repo": ".", "label": "...",
     "mapped": [{"path": "...", "nodes": [{"id","type","title"}]}],
     "unmapped": ["path1", ...],
     "boring_skipped": int}
  ],
  "totals": {"mapped": N, "unmapped": M, "boring_skipped": K},
  "warnings": [...]
}
```

### D.3 — Summarize first

Before any review work, present a one-screen overview:

```
## DomainTome sync (<scope>)

<N> files mapped to existing nodes — review whether they need updates.
<M> files unmapped — candidates for new nodes.
<K> files skipped as boring (lockfiles, CSS, images, docs).

Repos: <list>
Warnings: <if any>
```

If both `mapped` and `unmapped` are empty, stop here and tell the user
the graph is in sync; no further action.

### D.4 — Walk unmapped files in batches

For each repo, group unmapped files by directory and present 5–10 at
a time. For each file:

- If the path is small (model, signal, command, view), Read it to
  decide its type. Aim for one of: `flow`, `capability`, `rule`,
  `event`, `form`, `decision`, or "boring after all — skip".
- If a file clearly maps onto an existing node by name overlap or
  subject, mention that and propose `dt_update_node` instead of a new
  node.
- Skip files that are pure tests, fixtures, migrations, or boilerplate
  the user has already said don't deserve nodes.

For each candidate, draft the node spec:

```
- {id: flow-..., type: flow, title: "...", source_ref: "<path>",
   proposed body: "<2-3 lines>"}
```

Show the user the batch and **wait for confirmation** before
persisting. Persist the confirmed batch with `dt_add_node(nodes=[...])`
in one transaction. Always set provenance:

- `source: "inferred_from_code"`
- `confidence: "medium"`
- `source_context: "sync diff <scope> on <today>"`
- `source_ref: "<path>"` or `"<path>:<symbol>"`
- `last_verified_at: "<today ISO>"`

Wire up edges in the same transaction:

- `flow → module` via `part_of`
- `flow → capability` via `implements`
- `rule → entity` via `enforces`
- etc.

### D.5 — Walk mapped files

For each, the JSON gives you the existing node ids that point at the
same `source_ref`. For each entry:

- Read the file and the node body.
- Decide: did the change update the node's behavior? If yes, propose a
  `dt_update_node` with `body=..., metadata_patch={"last_verified_at":
  "<today>"}`. If no behavior change, just `metadata_patch=
  {"last_verified_at": "<today>"}`.

Batch and confirm the same way as D.4.

### D.6 — Audit at the end

After all writes, run `dt_audit()` and surface any new warnings. Tell
the user the totals: `<X> nodes added, <Y> nodes updated, <Z> edges
added`.

### D.7 — Rules

- Never persist without explicit user confirmation per batch.
- Never invent `source_ref` paths — only use paths that the
  `sync-plan` JSON gave you.
- Never add a node for files that are tests, migrations, fixtures, or
  generated code unless the user explicitly opts in.
- If the diff is enormous (>200 unmapped files), suggest a smaller
  scope (`/dt:sync HEAD~3`) before drowning the conversation.
- Nodes inserted by sync inherit `confidence: "medium"`. The user
  upgrades to `high` once they verify by hand.

---

## Shared sub-agent template

Used by INIT (auto-scan paths) and EXTEND. Invoke the `Agent` tool
with:

- `subagent_type`: `"general-purpose"`
- `model`: the configured exploration model (`.dt/config.json →
  models.exploration`), default **`sonnet`** (bootstrap precision
  matters, Haiku has been observed fabricating `source_ref` paths)
- `description`: `"Scan repo for DomainTome seed"`
- `prompt`: inline below, adapted to the current scope

```
Scan this directory and produce a compact proposal for a DomainTome seed
graph. Return JSON only, no prose.

Scope: <single-repo>|<full-workspace>|<workspace-inner-for-repo <name>>|<extend>

Steps:
1. Detect layout (only relevant for INIT scopes):
   - **Single repo**: one `package.json` / `pyproject.toml` / `go.mod` /
     `Cargo.toml` at the root, a single `src/` or equivalent.
   - **Workspace**: no manifest at the root, or multiple child dirs that
     each contain their own manifest. Common markers: `*_ws/`, `apps/`,
     `packages/`, `services/`, or sibling folders like `backend/` +
     `frontend/`.
2. List top-level source directories (src/*, app/*, apps/*, lib/*,
   packages/*, services/*). Ignore tests, vendor, build output,
   node_modules, .venv, __pycache__, dist, _scratch.
3. Each business-meaningful dir is a candidate `module`. Cross-cutting
   concerns (auth, observability, infra) that clearly affect many
   modules deserve their own module.
4. For each module, skim entry-point files for 1–3 `capability` nodes
   (WHAT the module does, not how).
5. Identify obvious `flow` nodes: HTTP handlers, CLI subcommands,
   queue workers, cron jobs. Capture `entry_point = "path:function"`.
6. Prefer precision over recall. Skip anything ambiguous.

Caps by scope:
- single-repo / full-workspace: up to 50 modules, 120 caps, 200 flows.
- workspace-inner-for-repo <name>: up to 20 modules, 40 caps, 60 flows.
- extend (small ≤5 visible): 5–10 mod / 15 caps / 25 flows.
- extend (medium 5–15): 15 / 40 / 70.
- extend (large 15+): up to 50 / 120 / 200.

Return one JSON object:
{
  "scope": "<as passed in>",
  "layout": "single_repo" | "workspace",
  "app_name": "...",
  "repository": "...",
  "language": "<primary natural language of docs/comments, e.g. 'en' or 'es'>",
  "modules":      [{"id": "module-<slug>",     "title": "...", "path": "...", "parent_id": "<parent-module-id-or-null>"}],
  "capabilities": [{"id": "capability-<slug>", "title": "...", "module_id": "<module-id>"}],
  "flows":        [{"id": "flow-<slug>",       "title": "...", "module_id": "<module-id>", "entry_point": "path:function"}],
  "truncated": false,
  "truncated_note": null
}
```

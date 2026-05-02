---
name: dt-usage
description: Keep the DomainTome knowledge graph in sync with ongoing work. ALWAYS use this skill when the user adds, changes, or removes any of the following in code or in conversation — a new endpoint, a new model, a new management command, a new Django signal, a new event, a new validation rule, a new form, a new Vue page, a new module/app, a new architectural decision, a new flow that supersedes another, a new dependency between modules, a new feature flag, or a new entity. ALWAYS use it when the user asks "how does X work?", "what flows touch Y?", "which rules protect Z?", or any question whose answer should be in a project knowledge graph. ALWAYS use it after editing files that look like business logic (views, services, commands, signals, serializers, validators, hooks). Read the graph before answering, write nodes/edges after deciding. Skip only for pure refactors that change no behavior, dependency bumps, CSS/styling-only changes, and exploratory talk.
user-invocable: false
---

# DomainTome — read-first, write-on-decision

This project ships with the **DomainTome MCP server** (`dt_*` tools) that stores
business knowledge as a typed graph: modules, capabilities, flows, events,
rules, forms, entities and decisions. Treat DomainTome as the project's **living
memory**.

## Scope: where does "the project" live?

DomainTome has no opinion about whether a project is a single repo or a
workspace holding several repos/packages. The graph lives in
`.dt/graph.db` relative to whatever directory Claude Code was launched
from — that's the "root of analysis". Workspaces with multiple repos
(split-repo setups, monorepos of independent packages, `*_ws/`
scaffolding) typically keep `.dt/` at the workspace root so a single
graph captures cross-repo relations. Single-repo projects keep it at the
repo root. Both are valid; pick whichever matches the unit of knowledge
you want to capture. The MCP server logs the resolved DB path on startup
so you can always verify which one it is using.

## Read before acting

Before answering "how does X work?" or writing non-trivial code that touches
a known concept, consult the graph:

1. `dt_query(text_or_id, depth=1)` — **`text_or_id` is required**. Exact id / title substring / tag.
2. `dt_list(type=..., include_body=False)` — cheap summary scan; follow up with `dt_get_node` for detail.
3. `dt_get_node(id, include_edges=true)` — full detail of a hit.
4. `dt_find_variants(capability_id)` — "how many ways of doing X?"
5. `dt_traverse(from_id, relations, max_depth)` — blast radius.

If the graph has the answer, cite the node id(s). If it's silent, say so —
don't fabricate.

## Detect contradictions

If the user or the code says one thing and the graph says another, **stop
and surface the mismatch** before acting. Ask which is authoritative. Do
not silently reconcile.

## Write on decision

When the conversation produces one of these, persist it:

| Trigger | Action |
|---|---|
| New module / capability / flow named and agreed on | `dt_add_node(...)` |
| Many related nodes at once (bootstrap, discovery) | `dt_add_nodes([...])` — one transaction |
| Flow A now supersedes flow B | `dt_add_edge(from=A, to=B, relation="supersedes")`, mark `B.status="superseded"` |
| New event emitted by a flow | `dt_add_node(type="event")` + `triggers` edge |
| New rule or validation | `dt_add_node(type="rule")` + `enforces` edge to the entity |
| Architectural decision | `dt_add_node(type="decision")` + `references` edge from the flow/rule it motivated |

Batch related edits; after substantive writes, call `dt_audit()` and
surface new warnings.

## Provenance — always set metadata

Every node you create must carry provenance in `metadata` so the user can
later audit what was inferred vs. stated. Standard keys:

| Key | Values / format | When |
|---|---|---|
| `source` | `user_stated` \| `user_confirmed` \| `inferred_from_code` \| `inferred_from_conversation` \| `code_change` \| `scan` \| `incident` \| `manual` | Always |
| `confidence` | `high` \| `medium` \| `low` | Always |
| `source_context` | one-line free text, e.g. `"conversation 2026-04-22"` or `"read src/foo/bar.py:42"` | Always |
| `source_ref` | `path:line` of the code it represents | When tracking a concrete code artifact |
| `last_verified_at` | ISO date, e.g. `"2026-04-22"` | After a human "yes, still correct" |
| `deprecated_at` | ISO date | When marking a node deprecated |
| `deprecated_reason` | one-line free text | When marking a node deprecated |
| `replaced_by` | id of the successor node | When superseded |

`inferred_from_conversation` is allowed but **prefer asking first** before
persisting inferences.

## Rich references — making each node a reference page

DomainTome is designed to be the central entry point to everything known about
a concept. A node should answer "what is X, where does it live, and
where do I read more?" without a second hop. Use `metadata.links` for
outbound pointers:

```
metadata.links = [
  {"title": "PRD v2: billing overhaul", "url": "https://…/PRD.md", "type": "prd"},
  {"title": "Figma — cart flow", "url": "https://figma.com/…", "type": "design"},
  {"title": "Incident 2026-03-12 (Linear INC-431)", "url": "https://…", "type": "incident"},
  {"title": "RFC-007: idempotency keys", "url": "https://…", "type": "rfc"}
]
```

`type` is free-form but conventional values are `prd | design | rfc |
ticket | incident | external-doc | runbook`. Use them so future queries
can filter (`dt_list(tag=...)` does not yet filter on link type, but
the structure is ready).

Policy: **add a link whenever the user references external material
during a conversation that relates to a DomainTome node**. Pass the user-stated
title verbatim. Do not guess URLs — if the user mentions a document by
name but no URL, ask, or omit the link.

The body of a node should be rich enough to orient a new reader: what
the concept is, why it matters, and the top 1–2 gotchas. The node is
the landing page; the links are the onward navigation.

## Attaching code — source_ref

When adding or updating a node during a session where Claude just
edited or read code, the `source_ref` MUST be set to that path (with
line or symbol when known). Format: `path` or `path:line` or
`path:Class.method`.

Examples:
- After `Edit("src/billing/charge.py", ...)` → next `dt_add_node`
  describing the charge flow sets `source_ref = "src/billing/charge.py"`.
- After `Read("src/billing/charge.py:45")` of a specific function →
  `source_ref = "src/billing/charge.py:charge_customer"`.

This closes the auto-enrichment loop — reconcile can then detect drift
whenever that file moves, disappears, or ages out.

## Updating metadata without losing provenance

`dt_update_node(metadata=…)` **replaces** the whole dict (destroys
provenance). **Prefer `metadata_patch`**: it merges at the top level, and
passing `null` as a value removes a key.

```
dt_update_node(id="flow-x", metadata_patch={"confidence": "low",
                                              "last_verified_at": "2026-04-22"})
```

## Lifecycle & soft-delete

Valid statuses: `active | draft | deprecated | superseded | archived`.

| Situation | Do |
|---|---|
| In-progress, not yet real | `status="draft"` |
| Still exists in code, still correct | `status="active"` |
| No longer used, historical record kept | `status="deprecated"` + `metadata_patch.deprecated_at` + `deprecated_reason` |
| Replaced by another node | `status="superseded"` + `supersedes` edge from successor + `metadata_patch.replaced_by` |
| Frozen but worth remembering (old version, prior product) | `status="archived"` |
| Typo / mistake only | `dt_delete_node` — the only legitimate hard delete |

**Never call `dt_delete_node` for a concept that existed.** Hard delete
cascades and destroys edges; the MCP reply includes an `edges_lost`
warning. Soft-delete preserves the graph's history.

## Renaming / moving a node

The graph treats ids as permanent. To "rename" `flow-checkout` →
`flow-order-placement`:

1. `dt_add_node(id="flow-order-placement", ...)` with full provenance.
2. `dt_add_edge(from="flow-order-placement", to="flow-checkout", relation="supersedes")`.
3. `dt_update_node("flow-checkout", status="superseded",
                     metadata_patch={"deprecated_at": "<today>",
                                     "replaced_by": "flow-order-placement"})`.
4. Re-attach any `part_of` / `implements` edges from the old id to the new one.

## Inspecting history

`dt_history(id)` returns the append-only MCP event log for a node
(newest first). Use it to answer "when was this deprecated?" or "what
changed and when?".

## Language of the content

Infrastructure (tool descriptions, error messages) is English. Node
**titles and bodies** must be written in **the natural language the user
uses in this conversation** (Spanish, English, etc.). IDs remain in
English kebab-case regardless.

If `.dt/config.json` exists and has a `language` key, follow it.
Otherwise follow the conversation language.

## Model routing — delegate reads to Haiku

Use the caller's model for decisions and writes. Delegate broad read-only
exploration to the cheaper `dt-explorer` sub-agent (Haiku):

| Situation | How |
|---|---|
| Single node lookup, 1-2 tool calls | Stay in caller's model |
| Scanning >20 nodes, deep traversal, multi-hop audit | `Agent(subagent_type: "dt-explorer", prompt: "<question>")` |
| Bootstrap / repo scan | Already handled by `/dt:bootstrap` (Sonnet by default; Haiku opt-in via `.dt/config.json → models.exploration`) |
| Detecting contradictions, choosing relations, modelling new nodes | Caller's model — requires reasoning |
| Any write (`dt_add_*`, `dt_update_*`, `dt_delete_*`) | **Caller's model only.** Never let a Haiku sub-agent write |

If `.dt/config.json` has `models.exploration`, honor it when picking the
sub-agent model; otherwise default to `haiku`. Example config:

```json
{ "language": "es", "models": { "exploration": "haiku", "write": "sonnet" } }
```

Rule of thumb: **Haiku reads, Sonnet/Opus decides what to write.** When a
sub-agent's finding must become a node/edge, have it return JSON and
persist from the caller after review.

## Id conventions

- Kebab-case only: lowercase letters, digits, single hyphens (e.g. `payment-by-transfer`).
- No colons, underscores, or uppercase. No leading/trailing hyphens, no `--`.
- Prefix generic words: `overview` → `billing-overview`.
- Convention by type: `module-<name>`, `capability-<slug>`, `flow-<slug>`, etc.

## Valid relations (shortlist)

The schema rejects invalid type pairs. Most common:

- `part_of`: flow/capability/form/event → **module**; also **module → module** (for hierarchy — inner modules that are part of a parent module, e.g. Django apps inside a `backend` repo module).
- `implements`: flow → capability
- `depends_on`: module/flow → module/flow (**not** capability → capability)
- `triggers`: flow/event → event/flow
- `validates`: form → rule
- `enforces`: rule → entity
- `supersedes`: flow → flow or rule → rule
- `references`: any → decision
- `conflicts_with`: rule↔rule or flow↔flow

If an edge is rejected, re-model: capabilities don't depend on each other —
their implementing **modules** or **flows** do.

## When NOT to write

Skip persistence for:

- Exploratory talk ("what if we tried X").
- Pure code refactors that don't change business behavior.
- Details already captured — prefer `dt_update_node` over re-adding.

---
name: lore-usage
description: Keep the Lore knowledge graph in sync with ongoing work. Invoke automatically whenever the conversation touches the project's business knowledge — how flows work, which capabilities exist, what rules protect an entity, architectural decisions, module dependencies, or contradictions between the graph and the code being discussed.
user-invocable: false
---

# Lore — read-first, write-on-decision

This project ships with the **Lore MCP server** (`lore_*` tools) that stores
business knowledge as a typed graph: modules, capabilities, flows, events,
rules, forms, entities and decisions. Treat Lore as the project's **living
memory**.

## Read before acting

Before answering "how does X work?" or writing non-trivial code that touches
a known concept, consult the graph:

1. `lore_query(text_or_id, depth=1)` — **`text_or_id` is required**. Exact id / title substring / tag.
2. `lore_list(type=..., include_body=False)` — cheap summary scan; follow up with `lore_get_node` for detail.
3. `lore_get_node(id, include_edges=true)` — full detail of a hit.
4. `lore_find_variants(capability_id)` — "how many ways of doing X?"
5. `lore_traverse(from_id, relations, max_depth)` — blast radius.

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
| New module / capability / flow named and agreed on | `lore_add_node(...)` |
| Many related nodes at once (bootstrap, discovery) | `lore_add_nodes([...])` — one transaction |
| Flow A now supersedes flow B | `lore_add_edge(from=A, to=B, relation="supersedes")`, mark `B.status="superseded"` |
| New event emitted by a flow | `lore_add_node(type="event")` + `triggers` edge |
| New rule or validation | `lore_add_node(type="rule")` + `enforces` edge to the entity |
| Architectural decision | `lore_add_node(type="decision")` + `references` edge from the flow/rule it motivated |

Batch related edits; after substantive writes, call `lore_audit()` and
surface new warnings.

## Provenance — always set metadata

Every node and edge you create must carry provenance in `metadata` so the
user can later audit what was inferred vs. stated. Keys:

- `source` — one of:
  - `user_stated` — the user explicitly affirmed it in this conversation.
  - `user_confirmed` — you proposed it and the user said "yes, save that".
  - `inferred_from_code` — you deduced it by reading source files.
  - `inferred_from_conversation` — you deduced it from context without an
    explicit confirmation. **Use sparingly — prefer asking first.**
- `confidence` — `high` | `medium` | `low`.
- `source_context` — one-line free text: e.g. `"conversation 2026-04-21: capabilities discussion"` or `"read from src/foo/bar.py"`.

When `lore_update_node` replaces metadata, **preserve these keys** — copy
them from the existing node first, then merge.

## Language of the content

Infrastructure (tool descriptions, error messages) is English. Node
**titles and bodies** must be written in **the natural language the user
uses in this conversation** (Spanish, English, etc.). IDs remain in
English kebab-case regardless.

If `.lore/config.json` exists and has a `language` key, follow it.
Otherwise follow the conversation language.

## Id conventions

- Kebab-case only: lowercase letters, digits, single hyphens (e.g. `payment-by-transfer`).
- No colons, underscores, or uppercase. No leading/trailing hyphens, no `--`.
- Prefix generic words: `overview` → `billing-overview`.
- Convention by type: `module-<name>`, `capability-<slug>`, `flow-<slug>`, etc.

## Valid relations (shortlist)

The schema rejects invalid type pairs. Most common:

- `part_of`: flow/capability/form/event → **module**
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
- Details already captured — prefer `lore_update_node` over re-adding.

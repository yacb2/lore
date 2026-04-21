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

1. `lore_query(text, depth=1)` — exact id / title substring / tag. Good first call.
2. `lore_get_node(id, include_edges=true)` — full detail of a hit.
3. `lore_find_variants(capability_id)` — "how many ways of doing X?"
4. `lore_traverse(from_id, relations, max_depth)` — blast radius.

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
| Flow A now supersedes flow B | `lore_add_edge(from=A, to=B, relation="supersedes")`, mark `B.status="superseded"` |
| New event emitted by a flow | `lore_add_node(type="event")` + `triggers` edge |
| New rule or validation | `lore_add_node(type="rule")` + `enforces` edge to the entity |
| Architectural decision | `lore_add_node(type="decision")` + `references` edge from the flow/rule it motivated |

Batch related edits; after substantive writes, call `lore_audit()` and
surface new warnings.

## Id conventions

- kebab-case: `payment-by-transfer`, not `payment_by_transfer`.
- Prefix generic words: `overview` → `billing-overview`.
- Types live in separate namespaces; reuse ids across types only when they
  clearly refer to the same concept.

## When NOT to write

Skip persistence for:

- Exploratory talk ("what if we tried X").
- Pure code refactors that don't change business behavior.
- Details already captured — prefer `lore_update_node` over re-adding.

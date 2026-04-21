---
name: lore-capture
description: Keep the Lore knowledge graph in sync with ongoing work. Auto-invoke whenever the conversation produces or discusses architectural decisions, new flows, new rules, new integrations, or changes to existing ones — and whenever the user asks a question whose answer lives in the graph.
---

# lore-capture

This skill governs how to use the Lore MCP tools (`lore_*`) during a normal
coding session. Invoke silently; only mention Lore explicitly when it adds
value for the user.

## Read-first

Before answering a "how does X work?" question or writing non-trivial code
that touches a known concept, call in this order:

1. `lore_query(text, depth=1)` — resolves id / title / tag and returns a
   neighborhood.
2. If that hits, follow up with `lore_get_node(id)` for full detail, or
   `lore_find_variants(capability_id)` to enumerate alternatives.
3. If the graph is silent, say so; don't invent.

## Write-on-decision

When the conversation results in one of these, persist it:

| Trigger | Action |
|---|---|
| New module / capability / flow named and agreed on | `lore_add_node(...)` |
| Flow `A` now supersedes flow `B` | `lore_add_edge(from=A, to=B, relation="supersedes")`; mark `B.status="superseded"` |
| New event emitted by a flow | `lore_add_node(type="event")` + `lore_add_edge(..., relation="triggers")` |
| New rule or validation protecting an entity | `lore_add_node(type="rule")` + `lore_add_edge(..., relation="enforces")` |
| Architectural decision justifying a choice | `lore_add_node(type="decision")` + `lore_add_edge(flow, decision, "references")` |

Batch related edits, commit once logically. After substantive writes, run
`lore_audit()` and surface any new warnings.

## Contradiction check

If the user states something that contradicts the graph ("the refund flow
goes through Stripe") and the graph disagrees (`refund-flow.body` mentions
Adyen), **stop and ask** which is authoritative. Do not silently update
either side.

## Id conventions

- kebab-case (`payment-by-transfer`).
- Prefix generic words (`overview` → `billing-overview`).
- Types live in separate namespaces; reuse ids across types only when they
  clearly refer to the same concept.

## When NOT to write

Skip persistence for:

- Exploratory / throwaway conversation ("what if we tried X").
- Pure code refactors that don't change business behavior.
- Details already captured — prefer `lore_update_node` over re-adding.

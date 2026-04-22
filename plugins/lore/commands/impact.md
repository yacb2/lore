---
description: Blast-radius analysis — what nodes are affected if this one changes?
argument-hint: <node-id>
allowed-tools: [Bash]
model: haiku
---

Answer "what breaks if I touch `$ARGUMENTS`?" by:

1. `lore_traverse(from_id="$ARGUMENTS", relations=["depends_on", "triggers", "implements"], max_depth=3)`
   to walk downstream consumers.
2. `lore_get_node(id="$ARGUMENTS", include_edges=True)` to list incoming
   `enforces`, `validates`, `references` edges.

Summarize as two groups:

- **Downstream** (things that break): from step 1.
- **Upstream** (things that protect/reference it): from step 2's incoming.

Flag any node whose status is `deprecated`/`superseded` — those are stale.

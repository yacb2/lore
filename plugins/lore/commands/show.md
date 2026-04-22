---
description: Show full detail of a Lore node — fields, incoming and outgoing edges, neighborhood.
argument-hint: <node-id>
allowed-tools: [Bash]
model: haiku
---

Call `lore_get_node(id="$ARGUMENTS", include_edges=True)` and render:

1. **Identity**: id, type, title, status.
2. **Body** (if any).
3. **Metadata** (tags, etc., if any).
4. **Outgoing edges** grouped by relation.
5. **Incoming edges** grouped by relation.

If the node is not found, suggest `lore_query("$ARGUMENTS")` to search.

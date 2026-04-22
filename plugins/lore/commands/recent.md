---
description: Show Lore nodes updated most recently. Use after a session to see what the graph captured.
allowed-tools: [Bash]
model: haiku
---

Lore does not yet have a dedicated "recent" MCP tool. Fall back to the CLI:

```bash
lore list --json 2>/dev/null | jq -r 'sort_by(.updated_at) | reverse | .[:20] | .[] | "\(.updated_at)  \(.type)/\(.id)  \(.title)"'
```

If `jq` is not available, call `lore_list()` and sort by `updated_at`
descending in your answer. Show the top 20.

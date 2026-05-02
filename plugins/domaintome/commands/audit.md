---
description: Run DomainTome audit and report health (orphans, dangling edges, id hygiene, cycles).
allowed-tools: [Bash]
model: haiku
---

Run `dt_audit()` and summarize the findings:

- **orphans**: nodes with no edges. List them and suggest either linking or
  deleting each.
- **invalid_ids** / **generic_ids**: flag id hygiene problems and propose
  renames.
- **cycles_supersedes** / **cycles_depends_on** / **cycles_triggers**: any
  non-empty list is a real bug — explain what it breaks and suggest which
  edge to remove.

If everything is clean, just say so in one line.

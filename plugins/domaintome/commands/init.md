---
description: Initialize DomainTome for this project. Permanent alias for `/dt:sync` in INIT mode — both work, both are supported long-term.
allowed-tools: [Bash, Read, Glob, Grep, Agent]
---

`/dt:init` is a **permanent alias** for `/dt:sync` when no graph
exists yet. It is not deprecated — external docs, READMEs, and muscle
memory rely on it, so it stays as a stable first-time-setup entry
point.

## Behavior

Run `/dt:sync` and follow its **INIT mode** branch end to end. The
detection in §Step 0 of `sync.md` will land in INIT automatically
when `.dt/graph.db` does not exist or `dt_list(type="module")` returns
zero modules.

If you discover the graph already has modules (someone ran setup
elsewhere), do **not** re-seed silently. Stop and tell the user:

> "DomainTome already has N top-level modules for this project. Run
> `/dt:sync` without arguments to extend (EXTEND mode), or `/dt:audit`
> to see current state."

For the full INIT workflow — layout detection, granularity prompt,
manual vs auto-scan, sub-agent template, mandatory `dt_audit()`
verification — see `commands/sync.md` §INIT mode.

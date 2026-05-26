---
description: DEPRECATED — use `/dt:sync` without arguments instead. This alias runs `/dt:sync` in EXTEND mode and emits a deprecation notice. Will be removed in a future release.
allowed-tools: [Bash, Read, Glob, Grep, Agent]
---

> **`/dt:bootstrap` is deprecated.** Use `/dt:sync` without arguments
> instead — it auto-detects the EXTEND mode when the graph already has
> modules and no git revision was passed. Both produce identical
> behavior today; the alias will be removed in a future release of the
> consolidation plan.

## Behavior

1. As your first user-visible line, print:

   > "`/dt:bootstrap` is deprecated. From now on use `/dt:sync` (no
   > arguments) for a broad re-scan of the codebase. This invocation
   > will continue and behave identically."

2. Run `/dt:sync` with no arguments and follow its **EXTEND mode**
   branch end to end. The detection in §Step 0 of `sync.md` will land
   in EXTEND automatically when `.dt/graph.db` has modules and no git
   revision was passed.

3. If somehow the graph is empty, do not silently fall through to
   INIT — tell the user to run `/dt:init` (or `/dt:sync`) for
   first-time setup.

For the full EXTEND workflow — sub-agent invocation, tiered caps,
proposal review, transactional persist, mandatory `dt_audit()`
verification — see `commands/sync.md` §EXTEND mode.

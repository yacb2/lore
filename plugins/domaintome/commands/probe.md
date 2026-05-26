---
description: DEPRECATED — use `/dt:audit <path>` instead. This alias forwards to `/dt:audit` Mode B (external project audit) and emits a deprecation notice. Will be removed in a future release.
allowed-tools: [Bash]
argument-hint: <path-to-project>
model: haiku
---

> **`/dt:probe` is deprecated.** Use `/dt:audit <path>` instead — it
> auto-detects Mode B (external project audit via CLI subprocess) when
> a path argument is present. Both produce identical output today; the
> alias will be removed in a future release of the consolidation plan.

## Behavior

1. As your first user-visible line, print:

   > "`/dt:probe` is deprecated. From now on use `/dt:audit <path>`
   > for the same external-project audit. This invocation will
   > continue and behave identically."

2. Run `/dt:audit` with `$ARGUMENTS` (the path) and follow its
   **Mode B — external project** branch end to end.

For the full Mode B workflow — DB resolution, `dt audit --json` +
`dt stats` subprocess, markdown summary, verdict logic — see
`commands/audit.md` §Mode B.

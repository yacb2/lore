---
description: Show DomainTome MCP usage analytics — calls, tokens exchanged, breakdown by tool and op. Optional --since <ISO timestamp>.
argument-hint: [since-iso]
allowed-tools: [Bash]
model: haiku
---

Report DomainTome's own usage analytics: how many MCP calls have been made
against this graph, the byte volume exchanged (with a rough token
estimate), and a per-tool / per-op breakdown.

## Steps

1. Run `dt stats` against the current project's DB. If `$ARGUMENTS`
   contains an ISO timestamp, pass it as `--since`:

   ```bash
   dt stats [--since $ARGUMENTS]
   ```

2. Summarize the output in a tight block:

   ```
   ## DomainTome usage (<period>)

   - Calls: N   (errors: N)
   - Total exchanged: X KB  (~Y tokens)
   - Input: X KB (~Y tokens)
   - Output: X KB (~Y tokens)

   ### By tool
   - dt_add_nodes: N calls · X KB (~Y tokens)
   - dt_audit: N calls · X KB (~Y tokens)
   - ...

   ### By op
   - audit / read / create / update / delete counts.
   ```

3. Honest proxy note: the CLI does not measure true tokens; the column
   is `bytes × 0.3`, useful for relative comparisons between tools or
   time periods, not for billing-grade numbers. Mention this only if
   the user asks for precision.

## When to use

- After a `/dt:bootstrap` / `/dt:init` to see what it cost.
- Periodically to spot unusually hot tools.
- With `--since <yesterday>` to scope to a session.

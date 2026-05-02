---
name: dt-commit
description: Explicitly persist recent conversation decisions into the DomainTome graph. Use when the user asks to "save this to DomainTome", "record the decision", or after a design discussion that should be captured.
disable-model-invocation: true
---

# DomainTome — explicit commit

Scan the recent conversation for concrete, stable decisions about the
project's business behavior and persist them as graph nodes/edges via the
`dt_*` MCP tools.

## What to capture

- **Modules / capabilities / flows** named and agreed on.
- **Supersedes** relationships (A replaces B).
- **Events** emitted and the flows that trigger them.
- **Rules** and the entities they `enforce`.
- **Decisions** (ADR-style) and the flows/rules that `reference` them.

## What to skip

- Exploratory "what if" talk.
- Code refactors with no behavior change.
- Anything already in the graph — prefer `dt_update_node`.

## Procedure

1. List what you plan to add (ids, types, titles, edges) and ask the user
   to confirm.
2. On confirmation, call the MCP tools and report each write.
3. Run `dt_audit()` and flag any new warning.
4. Offer to `dt_export_markdown(".dt/export")` for PR review.

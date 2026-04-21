---
name: lore-commit
description: Explicitly persist recent conversation decisions into the Lore graph. Use when the user asks to "save this to Lore", "record the decision", or after a design discussion that should be captured.
disable-model-invocation: true
---

# Lore — explicit commit

Scan the recent conversation for concrete, stable decisions about the
project's business behavior and persist them as graph nodes/edges via the
`lore_*` MCP tools.

## What to capture

- **Modules / capabilities / flows** named and agreed on.
- **Supersedes** relationships (A replaces B).
- **Events** emitted and the flows that trigger them.
- **Rules** and the entities they `enforce`.
- **Decisions** (ADR-style) and the flows/rules that `reference` them.

## What to skip

- Exploratory "what if" talk.
- Code refactors with no behavior change.
- Anything already in the graph — prefer `lore_update_node`.

## Procedure

1. List what you plan to add (ids, types, titles, edges) and ask the user
   to confirm.
2. On confirmation, call the MCP tools and report each write.
3. Run `lore_audit()` and flag any new warning.
4. Offer to `lore_export_markdown(".lore/export")` for PR review.

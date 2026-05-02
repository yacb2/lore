---
description: Mark a DomainTome node as verified today — refreshes last_verified_at. Usage: /dt:verify <node-id>
argument-hint: <node-id>
allowed-tools: [Bash]
model: haiku
---

Refresh the `last_verified_at` timestamp on a node. Use this after you
have manually re-inspected the referenced code and confirmed the node
still describes it correctly.

## Steps

1. Run:

   ```bash
   dt verify $ARGUMENTS
   ```

2. Report the result in one line. If the command succeeds, say:
   "Verified <id> — last_verified_at=<today>."
   If it fails (node not found), say so and suggest `dt_query` or
   `/dt:show` to find the correct id.

## When to use

- After a manual inspection of the code a node describes.
- In response to a `reconcile` finding under `stale` or `never_verified`.
- Not as a way to "silence" reconcile without actually looking at the
  code. The verification flag carries meaning; don't spam it.

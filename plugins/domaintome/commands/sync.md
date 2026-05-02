---
description: Sync the DomainTome graph with code changes since a git revision. Detects new files that should become nodes and existing nodes whose source files changed. Confirms before persisting.
allowed-tools: [Bash, Read, Glob, Grep]
argument-hint: [git-rev]
---

Bring the DomainTome graph back in line with the code. Reads `git diff` from
`$ARGUMENTS` (a revision like `HEAD~10`, `v2.24.0`, a sha) up to
`HEAD`, splits the changed files into "already mapped to a graph node"
vs "unmapped", and walks both lists with the user before persisting
anything.

This is the **only** command that closes the loop in the other
direction from `/dt:reconcile`: reconcile detects rotten nodes,
sync detects code without a node.

## Steps

1. **Resolve scope.** Parse `$ARGUMENTS` as a single git revision. If
   empty, default to `HEAD~10`. Mention the chosen scope back to the
   user before continuing so they can correct it.

2. **Run `dt sync-plan`:**

   ```bash
   dt sync-plan --since <rev>
   ```

   The command exits 0 if everything is mapped, 1 if there are
   unmapped files. Either way, parse the JSON from stdout. The
   structure is:

   ```
   {
     "scope": "<rev>..HEAD",
     "repos": [
       {"repo": ".", "label": "...",
        "mapped": [{"path": "...", "nodes": [{"id","type","title"}]}],
        "unmapped": ["path1", ...],
        "boring_skipped": int}
     ],
     "totals": {"mapped": N, "unmapped": M, "boring_skipped": K},
     "warnings": [...]
   }
   ```

3. **Summarize first.** Before any review work, present a one-screen
   overview:

   ```
   ## DomainTome sync (<scope>)

   <N> files mapped to existing nodes — review whether they need updates.
   <M> files unmapped — candidates for new nodes.
   <K> files skipped as boring (lockfiles, CSS, images, docs).

   Repos: <list>
   Warnings: <if any>
   ```

   If both `mapped` and `unmapped` are empty, stop here and tell the
   user the graph is in sync; no further action.

4. **Walk unmapped files in batches.** For each repo, group unmapped
   files by directory and present 5–10 at a time. For each file:

   - If the path is small (model, signal, command, view), Read it to
     decide its type. Aim for one of: `flow`, `capability`, `rule`,
     `event`, `form`, `decision`, or "boring after all — skip".
   - If a file clearly maps onto an existing node by name overlap or
     subject, mention that and propose `dt_update_node` instead of
     a new node.
   - Skip files that are pure tests, fixtures, migrations, or
     boilerplate the user has already said don't deserve nodes.

   For each candidate, draft the node spec:

   ```
   - {id: flow-..., type: flow, title: "...", source_ref: "<path>",
      proposed body: "<2-3 lines>"}
   ```

   Show the user the batch and **wait for confirmation** before
   persisting. Persist the confirmed batch with `dt_add_nodes(...)`
   in one transaction. Always set provenance:

   - `source: "inferred_from_code"`
   - `confidence: "medium"`
   - `source_context: "sync <scope> on <today>"`
   - `source_ref: "<path>"` or `"<path>:<symbol>"`
   - `last_verified_at: "<today ISO>"`

   Wire up edges in the same transaction:

   - `flow → module` via `part_of`
   - `flow → capability` via `implements`
   - `rule → entity` via `enforces`
   - etc.

5. **Walk mapped files.** For each, the JSON gives you the existing
   node ids that point at the same `source_ref`. For each entry:

   - Read the file and the node body.
   - Decide: did the change update the node's behavior? If yes,
     propose a `dt_update_node` with `body=...,
     metadata_patch={"last_verified_at": "<today>"}`. If no behavior
     change, just `metadata_patch={"last_verified_at": "<today>"}`.

   Batch and confirm the same way as step 4.

6. **Audit at the end.** After all writes, run `dt_audit()` and
   surface any new warnings. Tell the user the totals: `<X> nodes
   added, <Y> nodes updated, <Z> edges added`.

## Rules

- Never persist without explicit user confirmation per batch.
- Never invent `source_ref` paths — only use paths that the
  `sync-plan` JSON gave you.
- Never add a node for files that are tests, migrations, fixtures,
  or generated code unless the user explicitly opts in.
- If the diff is enormous (>200 unmapped files), suggest a smaller
  scope (`/dt:sync HEAD~3`) before drowning the conversation.
- Nodes inserted by sync inherit `confidence: "medium"`. The user
  upgrades to `high` once they verify by hand.

---
description: Detect drift between code and DomainTome — dead source_refs, stale nodes, never-verified nodes. Read-only.
allowed-tools: [Bash]
model: haiku
argument-hint: [git-rev]
---

Run `dt reconcile` to surface drift between the graph and the current
state of the code. Read-only — never fixes anything automatically. The
user decides what to apply afterwards via targeted `dt_update_node`
calls.

## Steps

1. **Determine scope.** If `$ARGUMENTS` contains a git revision (e.g.
   `HEAD~5`, `main`, a sha), pass it as `--since`; otherwise do a full
   scan.

2. **Run:**

   ```bash
   dt reconcile --json [--since <rev>]
   ```

   The command exits with code 1 if there is drift, 0 if clean. Either
   way, parse the JSON from stdout.

3. **Summarize** in this shape:

   ```
   ## DomainTome reconcile (<scope>)

   Scanned: N nodes with source_ref.
   Warnings: <if any, one per line>

   **dead_refs** (N): source_ref points at a file that no longer exists.
     - node-id-1 → path:line
     - node-id-2 → path:line
     ...

   **stale** (N): last_verified_at older than <threshold> days.
     - node-id  (last verified D days ago)

   **never_verified** (N): has source_ref but never marked verified.
     - node-id

   Verdict: <one sentence>
   ```

4. **Suggest concrete next actions** for each finding:
   - `dead_refs`: "Decide per node — either delete (`status='archived'`),
     update `source_ref` to the new path, or confirm the concept still
     exists even though the file moved."
   - `stale`: "Re-verify by inspecting the referenced code, then
     `dt_update_node(id, metadata_patch={'last_verified_at': '<today>'})`."
   - `never_verified`: "After a bootstrap, mark each node verified once
     you've checked it corresponds to the code."

5. **Do not write to the graph.** If the user asks for fixes, then write —
   but each write requires an explicit user decision per node.

## Rules

- Never fabricate counts. If reconcile says 0 dead_refs, that is the
  number. Do not invent findings to look helpful.
- `never_verified` is lower priority than `stale`. If both lists are
  large, lead with `dead_refs` and `stale`.
- If the report includes warnings (e.g. not a git repo), surface them
  verbatim.

---
description: Audit a DomainTome graph in another project. Usage: /dt:probe <path-to-project>
argument-hint: <path-to-project>
allowed-tools: [Bash]
model: haiku
---

Audit the DomainTome graph of an external project without switching working
directory. The user passes a path as `$ARGUMENTS`.

## Steps

1. **Resolve the DB path**: `<path>/.dt/graph.db`. If the path does not
   exist, stop and report it clearly — do not create anything.

2. **Run two read-only CLI calls**:

   ```bash
   dt audit --db <path>/.dt/graph.db --json
   dt stats --db <path>/.dt/graph.db
   ```

   The `--json` flag on `audit` gives you structured counts and findings
   in one shot: `nodes_total`, `edges_total`, `nodes_by_type`,
   `nodes_by_status`, `edges_by_relation`, `last_mutation_at`, plus the
   finding lists (`orphans`, `dangling_edges`, `invalid_ids`,
   `generic_ids`, `unknown_types`, `cycles_*`).

3. **Summarize as a single markdown block** with this shape:

   ```
   ## DomainTome probe — <project-name>

   **Graph**
   - nodes: <nodes_total>   edges: <edges_total>
   - last mutation: <last_mutation_at>
   - by type:     <nodes_by_type as k=v, ...>
   - by status:   <nodes_by_status as k=v, ...>
   - by relation: <edges_by_relation as k=v, ...>

   **Health**
   - orphans: N
   - dangling_edges: N
   - invalid_ids / generic_ids / unknown_types: N / N / N
   - cycles: supersedes=N, depends_on=N, triggers=N

   **Usage (MCP)**
   - calls: N   errors: N
   - total bytes exchanged: X  (≈ X*0.3 tokens, honest proxy)
   - top tools: <tool> (N calls), ...
   ```

4. **Verdict**: one sentence.
   - **Green** if every finding list is empty.
   - **Yellow** if only `orphans`, `generic_ids`, or `invalid_ids` are non-empty.
   - **Red** if any `dangling_edges`, `unknown_types`, or `cycles_*` are non-empty.

## Rules

- Never write to the external DB. No `update_node`, no `add_node`, nothing.
- Do not read individual node bodies — this is a structural probe, not an
  exploration. If the user wants detail, they can open that project and
  use `/dt:show`.
- If `dt stats` reports no calls, say "no MCP activity recorded" — don't
  treat it as an error.
- If the user passes a relative path, resolve it against the current
  working directory.

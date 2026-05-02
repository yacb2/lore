# DomainTome

> The living knowledge graph for your software project.

> **Status: pre-1.0, solo-maintained.** DomainTome is functional and used in
> production projects, but the API, the schema and the MCP surface may
> still break between minor versions. Bug reports are welcome; feature
> PRs may not be merged while the design stabilizes. The repository will
> open up to broader collaboration once the API is stable (target: 1.0).

**DomainTome** captures the business logic of a project — modules, capabilities, flows, events, rules, forms, entities and decisions — as a typed graph backed by SQLite, and exposes it over **MCP** so AI coding assistants (Claude Code, Claude Desktop) can query and maintain it as part of normal work.

It answers questions like *"how many ways of registering a payment exist?"*, *"what breaks if I touch `flow-checkout`?"* or *"which rules protect this entity?"* in a single tool call, with provenance, without re-exploring the codebase each time.

## Why

- **Persistent memory** across sessions — the graph survives context resets.
- **Zero documentation overhead** — the assistant writes as concepts get decided, not as a separate chore.
- **Auditable** — every node carries `source`, `confidence`, `source_context`. Every MCP call is logged.
- **Token-efficient** — summary-only listings, batch ops, cheap sub-agents for exploration, WAL-mode SQLite.

## Token economics (measured)

Bytes-on-the-wire to the model when answering structural questions, with vs. without DomainTome. Reproduce on your machine via `examples/booking-api/` (full protocol in `examples/booking-api/README.md`).

| Project                | Files | Question                                            | Without | With   | Ratio   |
|------------------------|------:|-----------------------------------------------------|--------:|-------:|--------:|
| `booking-api`          |     5 | How many ways can a Reservation be cancelled?       | 6,213 B | 1,485 B|  4.2×   |
| `booking-api`          |     5 | What rules apply to a Reservation?                  | 4,032 B |   291 B| 13.9×   |
| `booking-api`          |     5 | What does deactivating a Resource affect?           | 4,654 B |   543 B|  8.6×   |
| `domaintome` (this repo)|   62 | What capabilities does DomainTome expose?           |49,726 B |   729 B| 68.2×   |
| `domaintome` (this repo)|   62 | Where do graph writes happen?                       |14,566 B |   314 B| 46.4×   |

**Median 13.9×, range 4–68×.** The "without" column is a *floor* — minimum file set, no `Grep`/`Glob` overhead. Real sessions read more. The pattern is clear: ratios grow with project size and how scattered the answer is across the codebase.

**Maintenance cost** (what Claude pays to keep the graph in sync): a typical "new flow + 3 edges" write costs **~720 B** total. Break-even is <1 query per new feature. Reads dominate writes by orders of magnitude.

Caveats: input-payload only (output answer not measured); does not include the one-time `/dt:bootstrap` cost; ratios are descriptive of the questions tested, not a guarantee for arbitrary questions.

## Install (Claude Code plugin — recommended)

```
/plugin marketplace add YACB2/domaintome
/plugin install domaintome@domaintome
```

Reload, then from the project you want to model run `dt init` (or `/dt:bootstrap` for a guided onboarding that scans the code with Haiku). "Project" can be a single repo *or* a workspace that contains several repos — DomainTome has no opinion, `.dt/graph.db` is created relative to whatever directory you launched Claude Code from.

The plugin bundles:

- **MCP server** exposing `dt_add_node`, `dt_add_nodes`, `dt_update_node`, `dt_delete_node`, `dt_get_node`, `dt_add_edge`, `dt_add_edges`, `dt_remove_edge`, `dt_query`, `dt_traverse`, `dt_list`, `dt_find_variants`, `dt_audit`, `dt_history`, `dt_stats`, `dt_export_markdown`.
- **Auto-invoked skill** (`dt-usage`) that tells Claude to read before acting and write on decision, with provenance rules and lifecycle conventions.
- **Sub-agent `dt-explorer`** (Haiku, read-only) for broad exploration without burning expensive tokens.
- **Slash commands**: `/dt:init`, `/dt:bootstrap`, `/dt:audit`, `/dt:show <id>`, `/dt:recent`, `/dt:impact <id>`, `/dt:probe <path>` (audit another project's graph without switching directory).

## Install (standalone CLI / other MCP hosts)

```bash
pipx install domaintome   # or: uv tool install domaintome
dt init
```

For Claude Desktop / other MCP hosts:

```json
{
  "mcpServers": {
    "dt": {
      "command": "dt",
      "args": ["mcp", "--db", ".dt/graph.db"]
    }
  }
}
```

## CLI reference

```bash
dt init                      # create .dt/graph.db
dt list [--type flow]        # summary listing (id, type, title, status)
dt show <id>                 # full detail + edges
dt query "payment"           # exact id → title substring → tag fallback
dt variants <capability-id>  # flows implementing a capability
dt audit                     # orphans, cycles, id hygiene
dt stats [--since ISO]       # token/usage analytics from the audit log
dt export --out .dt/export   # one markdown file per node
```

## Schema

**Eight node types** (stack-agnostic): `module`, `capability`, `flow`, `event`, `rule`, `form`, `entity`, `decision`.

**Nine relations**: `part_of`, `implements`, `depends_on`, `triggers`, `validates`, `enforces`, `supersedes`, `references`, `conflicts_with`. Type pairs are restricted (see `schema.py`).

**Statuses**: `active | draft | deprecated | superseded | archived`. Soft-delete is the default; `dt_delete_node` is reserved for typos and warns about edge loss.

The central abstraction is **`capability`** — a thing the system knows how to do, independent of how. Multiple `flow` nodes can `implements` the same capability, surfacing UX/logic divergences.

## Model routing

Operations are split by cost:

- **Reads** (broad scans, traversals, audits): delegated to Haiku via the `dt-explorer` sub-agent or `model: haiku` frontmatter on slash commands.
- **Writes & modeling decisions**: caller's model (Sonnet/Opus). A sub-agent proposes JSON; the caller reviews and persists.

Override per-project in `.dt/config.json`:

```json
{
  "language": "es",
  "app_name": "my-app",
  "models": { "exploration": "haiku", "write": "sonnet" }
}
```

## Provenance & history

Every node carries `metadata.{source, confidence, source_context}` and, when relevant, `source_ref` (`path:line`), `last_verified_at`, `deprecated_at`, `deprecated_reason`, `replaced_by`.

`dt_update_node(metadata_patch=…)` merges without destroying provenance; `metadata` still exists for rare full replacements.

`dt_history(id)` returns every MCP event for a node (newest first) from the append-only audit log. `dt_stats` aggregates by tool/op and reports input/output bytes.

## Status

Pre-MVP, alpha. Schema and MCP tool surface may change before 0.1.0.

## Development

```bash
uv sync --all-groups
uv run pytest -q
uv run ruff check src tests
```

Tests live in `tests/`. The plugin layout is validated by `test_plugin_structure.py`.

## License

MIT.

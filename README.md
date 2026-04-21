# Lore

> The living knowledge graph for your software project.

**Lore** is a programmatic knowledge graph that captures the business logic of a software project — flows, events, rules, capabilities and their relationships — as a typed graph backed by SQLite. It exposes an MCP server so AI coding assistants (Claude Code, Cursor, etc.) can query and maintain the graph without re-exploring the codebase on every question.

## Why Lore

In large projects, answering questions like *"how many ways are there to register a payment?"*, *"what flow runs after event X?"*, or *"which rules protect this entity?"* requires either tribal knowledge or grepping through the code from scratch every time.

Lore stores that knowledge as a graph your AI assistant can query with a single call, and — crucially — update during normal coding sessions, so the graph stays in sync without manual documentation work.

## Install

```bash
pipx install projectlore
```

Requires Python 3.11+.

## Quickstart

```bash
# Create an empty graph in the current project
lore init

# (Your LLM agent starts adding nodes via the MCP server.)

# Inspect the graph
lore list
lore list --type flow
lore show payment-by-transfer
lore query "payment"
lore variants payment-registration
lore audit

# Export as markdown for PR review
lore export --out .lore/export/
```

## MCP integration (Claude Code)

Two steps. First, add Lore to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "lore": {
      "command": "lore",
      "args": ["mcp", "--db", ".lore/lore.db"]
    }
  }
}
```

Second, install the bundled slash commands, skill and `CLAUDE.md` snippet
so Claude reads and updates the graph automatically during normal chat:

```bash
lore install-claude
```

See [`docs/claude-integration.md`](docs/claude-integration.md) for the full
surface.

## Schema

Eight node types (stack-agnostic): `module`, `capability`, `flow`, `event`, `rule`, `form`, `entity`, `decision`. Nine relations: `part_of`, `implements`, `depends_on`, `triggers`, `validates`, `enforces`, `supersedes`, `references`, `conflicts_with`.

The central abstraction is **`capability`** — a thing the system knows how to do, independent of how. Multiple `flow` nodes can `implements` the same capability, exposing UX/logic divergences (the answer to "how many ways of X?").

## Status

Pre-MVP (alpha). Schema and MCP tool surface may change.

## Development

```bash
uv sync --all-groups
uv run pytest
uv run ruff check src tests
```

## License

MIT.

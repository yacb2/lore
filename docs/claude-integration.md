# Claude Code integration

Lore ships in two pieces that work together:

1. **`projectlore`** on PyPI — the MCP server binary and Python CLI.
2. **The `lore` plugin** — a Claude Code plugin (this repository's
   `plugins/lore/` directory) that registers the MCP server, two skills and
   five slash commands as a single installable unit.

Claude Code's plugin system is what makes the *automatic behavior* possible.
An MCP server by itself can only expose tools — it cannot tell Claude *when*
to use them. The plugin adds skills and commands that are namespaced under
the plugin and get loaded when the plugin is enabled.

## Install

### 1. Install the MCP binary

```bash
pipx install projectlore
# or: uv tool install projectlore
```

### 2. Add the marketplace and install the plugin

Inside any project where you use Claude Code:

```
/plugin marketplace add YACB2/lore
/plugin install lore@lore
```

Claude Code will:

- Register the `lore` MCP server from `plugins/lore/.mcp.json` (auto-starts
  when the plugin is enabled).
- Load the `lore-usage` skill (auto-invoked during conversation).
- Load the `lore-commit` skill (user-invocable only, via `/lore:lore-commit`).
- Register the five slash commands under `/lore:*`.

Then bootstrap the graph:

```bash
lore init          # creates .lore/lore.db in the current project
```

## What gets installed

| File | Purpose |
|---|---|
| `plugins/lore/.mcp.json` | Declares the `lore` MCP server. Auto-started. |
| `plugins/lore/skills/lore-usage/SKILL.md` | **Auto-invoked.** Read-first, write-on-decision, contradiction-check. |
| `plugins/lore/skills/lore-commit/SKILL.md` | **User-invocable only.** Explicit bulk persist after a design discussion. |
| `plugins/lore/commands/lore/init.md` | `/lore:init` — bootstrap modules interactively. |
| `plugins/lore/commands/lore/audit.md` | `/lore:audit` — run structural checks. |
| `plugins/lore/commands/lore/show.md` | `/lore:show <id>` — full node detail. |
| `plugins/lore/commands/lore/recent.md` | `/lore:recent` — top 20 by updated_at. |
| `plugins/lore/commands/lore/impact.md` | `/lore:impact <id>` — blast-radius analysis. |

## Updating / removing

```
/plugin marketplace update lore
/plugin uninstall lore@lore
```

Disabling the plugin stops the MCP server and hides the skills/commands
atomically — no file cleanup needed.

## Using Lore outside Claude Code

The MCP server itself is host-agnostic (Cursor, Claude Desktop, any MCP
client). The skills and slash commands are Claude-Code-specific. For other
hosts, register the MCP server using that host's config mechanism:

```json
{
  "mcpServers": {
    "lore": {
      "command": "uvx",
      "args": ["projectlore", "mcp", "--db", ".lore/lore.db"]
    }
  }
}
```

Those hosts won't get the auto-invocation behavior — you'll need to prompt
the assistant to read/write Lore explicitly, or paste the contents of
`plugins/lore/skills/lore-usage/SKILL.md` into that host's system-prompt equivalent.

## Sanity check

```bash
# The MCP server starts and waits on stdin:
uvx projectlore mcp --db .lore/lore.db

# The CLI works standalone:
lore init
lore list
lore audit
```

Inside Claude Code, a plain question like *"what modules does this project
have?"* should cause the assistant to call `lore_list()` automatically —
that's the `lore-usage` skill doing its job.

# Claude Code integration

DomainTome ships in two pieces that work together:

1. **`domaintome`** on PyPI — the MCP server binary and Python CLI.
2. **The `dt` plugin** — a Claude Code plugin (this repository's
   `plugins/domaintome/` directory) that registers the MCP server, two skills and
   five slash commands as a single installable unit.

Claude Code's plugin system is what makes the *automatic behavior* possible.
An MCP server by itself can only expose tools — it cannot tell Claude *when*
to use them. The plugin adds skills and commands that are namespaced under
the plugin and get loaded when the plugin is enabled.

## Install

### 1. Install the MCP binary

```bash
pipx install domaintome
# or: uv tool install domaintome
```

### 2. Add the marketplace and install the plugin

Inside any project where you use Claude Code:

```
/plugin marketplace add YACB2/domaintome
/plugin install domaintome@domaintome
```

Claude Code will:

- Register the `dt` MCP server from `plugins/domaintome/.mcp.json` (auto-starts
  when the plugin is enabled).
- Load the `dt-usage` skill (auto-invoked during conversation).
- Load the `dt-commit` skill (user-invocable only, via `/dt:dt-commit`).
- Register the five slash commands under `/dt:*`.

Then bootstrap the graph:

```bash
dt init          # creates .dt/graph.db in the current project
```

## What gets installed

| File | Purpose |
|---|---|
| `plugins/domaintome/.mcp.json` | Declares the `dt` MCP server. Auto-started. |
| `plugins/domaintome/skills/dt-usage/SKILL.md` | **Auto-invoked.** Read-first, write-on-decision, contradiction-check. |
| `plugins/domaintome/skills/dt-commit/SKILL.md` | **User-invocable only.** Explicit bulk persist after a design discussion. |
| `plugins/domaintome/commands/dt/init.md` | `/dt:init` — bootstrap modules interactively. |
| `plugins/domaintome/commands/dt/audit.md` | `/dt:audit` — run structural checks. |
| `plugins/domaintome/commands/dt/show.md` | `/dt:show <id>` — full node detail. |
| `plugins/domaintome/commands/dt/recent.md` | `/dt:recent` — top 20 by updated_at. |
| `plugins/domaintome/commands/dt/impact.md` | `/dt:impact <id>` — blast-radius analysis. |

## Updating / removing

```
/plugin marketplace update domaintome
/plugin uninstall domaintome@domaintome
```

Disabling the plugin stops the MCP server and hides the skills/commands
atomically — no file cleanup needed.

## Using DomainTome outside Claude Code

The MCP server itself is host-agnostic (Cursor, Claude Desktop, any MCP
client). The skills and slash commands are Claude-Code-specific. For other
hosts, register the MCP server using that host's config mechanism:

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

This assumes you ran `uv tool install domaintome` (or `pipx install
domaintome`) in step 1 so the `dt` binary is on your `$PATH`. When
`domaintome` ships on PyPI, you can alternatively use `"command": "uvx"`
with `"args": ["domaintome", "mcp", "--db", ".dt/graph.db"]` to skip the
install step — but that only works after the package is public.

Those hosts won't get the auto-invocation behavior — you'll need to prompt
the assistant to read/write DomainTome explicitly, or paste the contents of
`plugins/domaintome/skills/dt-usage/SKILL.md` into that host's system-prompt equivalent.

## Sanity check

```bash
# The MCP server starts and waits on stdin:
uvx domaintome mcp --db .dt/graph.db

# The CLI works standalone:
dt init
dt list
dt audit
```

Inside Claude Code, a plain question like *"what modules does this project
have?"* should cause the assistant to call `dt_list()` automatically —
that's the `dt-usage` skill doing its job.

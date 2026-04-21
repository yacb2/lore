# Claude Code integration

Lore ships two things for Claude Code users:

1. **The MCP server** — exposes graph tools (`lore_query`, `lore_add_node`, …)
   that Claude can call during any conversation.
2. **A distribution bundle** — slash commands, a skill, and a `CLAUDE.md`
   snippet that teach Claude *when* to use those tools automatically.

## One-shot install

From the root of any project that uses Claude Code:

```bash
lore init                   # creates .lore/lore.db
lore install-claude         # writes .claude/commands, .claude/skills, CLAUDE.md
```

Then add the MCP server to your Claude Code config (`~/.claude/config.json`
or the project-local equivalent):

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

Restart Claude Code. You should now see:

- 5 slash commands under `/lore-*`.
- A `lore-capture` skill loaded automatically.
- A Lore section inside `CLAUDE.md` that tells Claude to read the graph
  before answering and to update it when architectural decisions are made.

## What each file does

### `CLAUDE.md` snippet

Appended (or inlined between `<!-- BEGIN LORE INTEGRATION -->` markers) to
your project's `CLAUDE.md`. Instructs Claude to:

- Query the graph *before* answering questions that map to known nodes.
- Update the graph *when* the conversation produces architectural decisions.
- Flag contradictions rather than silently resolving them.

Running `lore install-claude` a second time is a no-op unless you pass
`--force`, which re-writes the snippet in place.

### Slash commands (`.claude/commands/lore/`)

| Command | Purpose |
|---|---|
| `/lore-init` | Bootstrap a new graph by asking the user for top-level modules. |
| `/lore-audit` | Run `lore_audit()` and summarize findings. |
| `/lore-show <id>` | Full detail of a node + incoming/outgoing edges. |
| `/lore-recent` | 20 most recently updated nodes. |
| `/lore-impact <id>` | Blast-radius analysis: what breaks if this node changes. |

### Skill (`.claude/skills/lore-capture.md`)

Auto-invoked during normal conversation. Guides Claude on *when* to read
and *when* to write, so the graph stays fresh without explicit prompting.

## Uninstall

Delete `.claude/commands/lore/`, `.claude/skills/lore-capture.md`, and
remove the block between `<!-- BEGIN LORE INTEGRATION -->` and
`<!-- END LORE INTEGRATION -->` in `CLAUDE.md`. The MCP entry in Claude's
config is independent and can be dropped separately.

## Testing the integration

A smoke check end-to-end:

```bash
lore init
lore install-claude
# In Claude Code, ask: "/lore-init" and follow the prompts.
# Then ask a plain question like: "what modules does this project have?"
# Claude should call lore_list() automatically and cite module ids.
```

If Claude fails to invoke the MCP tools, verify:

1. The `lore mcp` command works standalone: `lore mcp --db .lore/lore.db`
   should start and wait on stdin.
2. The MCP entry in Claude Code's config points to the correct `db` path.
3. Claude Code has been restarted since the install.

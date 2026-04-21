# Plugin development loop

This doc covers how to iterate on the Lore Claude Code plugin locally, how to
validate it before publishing, and what the repo structure must look like.

The plugin itself lives under `plugins/lore/`. The marketplace manifest that
points at it lives at `.claude-plugin/marketplace.json` in the repo root.

## Repo layout

```
lore/                                   # repo root
├── .claude-plugin/
│   └── marketplace.json                # marketplace manifest (one per repo)
└── plugins/
    └── lore/                           # one plugin dir per plugin in the marketplace
        ├── .claude-plugin/
        │   └── plugin.json             # plugin manifest (name, version, description)
        ├── .mcp.json                   # MCP servers shipped by this plugin
        ├── skills/
        │   ├── lore-usage/SKILL.md     # auto-invoked (user-invocable: false)
        │   └── lore-commit/SKILL.md    # user-only (disable-model-invocation: true)
        └── commands/lore/              # slash commands, namespaced under /lore:
            ├── init.md
            ├── audit.md
            ├── show.md
            ├── recent.md
            └── impact.md
```

Two rules that are easy to get wrong:

- **Components live at the plugin root**, not inside `.claude-plugin/`. Only
  `plugin.json` goes in `.claude-plugin/`. `skills/`, `commands/`, `.mcp.json`
  sit next to it.
- **Marketplace `source` is relative to the repo root** (the directory
  containing `.claude-plugin/marketplace.json`). We use
  `source: "./plugins/lore"`. `metadata.pluginRoot` is documented in some
  references but is **not** honored by the installer as of the current
  Claude Code version — always use an explicit full path in `source`.

`tests/test_plugin_structure.py` enforces both rules in CI.

## Local dev loop

From the repo root:

```bash
# Load the plugin without installing it to the user profile.
claude --plugin-dir ./plugins/lore
```

Inside the Claude Code session:

- Edit `SKILL.md`, command files, `.mcp.json`, or `plugin.json`.
- Run `/reload-plugins` to pick up the changes. This restarts any MCP server
  the plugin defines, so in-flight MCP state is lost — that's expected.
- Run `/help` to confirm `/lore:*` commands show up.
- Ask Claude a question that should trigger the `lore-usage` skill (e.g.
  *"what modules does this project have?"*) to confirm auto-invocation works.

## Structural validation

We rely on two layers:

1. **`claude plugin validate .`** — the official CLI check. Run it from the
   repo root. It reads `.claude-plugin/marketplace.json` and walks each
   referenced plugin. Use this before opening a PR.

2. **`uv run pytest tests/test_plugin_structure.py`** — runs in normal
   Python CI, no Claude Code binary needed. It asserts:
   - `marketplace.json` has required fields and the owner/plugin shape.
   - `plugin.json` has `name`, `version`, `description`.
   - `.mcp.json` declares the `lore` server with a `command`.
   - Components are **not** misfiled inside `.claude-plugin/`.
   - `metadata.pluginRoot + source` actually resolves to the plugin dir.
   - Every skill and command has a non-empty frontmatter `description`.

Both should pass on every commit to `main`.

## Publishing

Once validation passes and the repo is pushed to GitHub:

```
/plugin marketplace add YACB2/lore
/plugin install lore@lore
```

The first argument is `<github-owner>/<repo>` (Claude Code reads
`.claude-plugin/marketplace.json` at that repo root). The second is
`<plugin-name>@<marketplace-name>` — both named `lore` here.

To ship a new version:

1. Bump `plugins/lore/.claude-plugin/plugin.json` `version` **and** the
   matching `version` in `marketplace.json`.
2. Bump the Python package `version` in `pyproject.toml` if the MCP server
   behavior changed.
3. Tag and push. Users run `/plugin marketplace update lore` to pull it.

## Common failure modes

| Symptom | Likely cause |
|---|---|
| `/lore:*` commands missing after install | `commands/` placed inside `.claude-plugin/` |
| MCP tools not appearing | `.mcp.json` at wrong path, or `command` binary not on PATH |
| Skill never auto-invokes | `user-invocable: false` missing, or description doesn't describe a trigger |
| `plugin validate` says source not found | `source` is absolute or missing `./`, or `pluginRoot` wrong |
| Marketplace install fails | `owner.url` present (not in schema), or `plugins[]` empty |

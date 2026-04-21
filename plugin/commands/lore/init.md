---
description: Bootstrap the Lore graph for this project. Creates .lore/lore.db and seeds the top-level modules by asking the user.
allowed-tools: [Bash, Read]
---

Bootstrap Lore in the current project:

1. Run `lore init` to create `.lore/lore.db` if it does not exist.
2. Ask the user for the top-level **modules** of this project (3–10
   short kebab-case names — e.g. `auth`, `billing`, `notifications`).
3. For each module, call `lore_add_node(type="module", id=<name>, title=<Title Case>)`.
4. Run `lore_audit()` and report the result.

Keep it brief — this is a seed, not a full reconstruction. Subsequent work
will flesh out capabilities, flows and rules as they come up.

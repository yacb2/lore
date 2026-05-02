---
description: Show full detail of a DomainTome node — fields, links, provenance, incoming and outgoing edges.
argument-hint: <node-id>
allowed-tools: [Bash]
model: haiku
---

Call `dt_get_node(id="$ARGUMENTS", include_edges=True)` and render the
node as a readable Markdown briefing. Treat each node as a "reference
page" — DomainTome is meant to be the central entry point to everything known
about a concept.

## Render shape

```
# <title>  [<type> · <status>]

<body — render as Markdown verbatim, do not summarize>

## Links
<if metadata.links is a non-empty array, render each as a bullet:
`- [<title>](<url>)  _<type if set>_`. If empty, skip this section.>

## References
<if metadata.source_ref is set, render as inline code.
if metadata.source is set, render as `Source: <source> (confidence: <confidence>)`.
if metadata.last_verified_at is set, render as `Last verified: <date>`.
if metadata.deprecated_at is set, render with reason.>

## Relations
### Outgoing
<grouped by relation: e.g. `- implements → capability-foo`>

### Incoming
<grouped by relation: e.g. `- flow-bar --implements-->`>

## Raw metadata
<remaining keys from metadata that weren't already rendered above,
compact JSON.>
```

## Rules

- Do not summarize or paraphrase `body`. Print it verbatim as Markdown.
- If a metadata key was rendered in "Links" / "References" sections, do
  not repeat it in "Raw metadata".
- If a key is not set, skip the section entirely — no "N/A" or "none".
- If the node is not found, suggest `dt_query("$ARGUMENTS")` to search
  by title or id fragment.

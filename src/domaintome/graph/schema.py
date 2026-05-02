"""Schema definitions for the DomainTome graph.

Node types and relations are hardcoded in v1 (per PRD §3 non-goals) to validate
the schema before considering configurability.
"""

from __future__ import annotations

from typing import Any

NODE_TYPES: frozenset[str] = frozenset(
    {
        "module",
        "capability",
        "flow",
        "event",
        "rule",
        "form",
        "entity",
        "decision",
    }
)

RELATIONS: frozenset[str] = frozenset(
    {
        "part_of",
        "implements",
        "depends_on",
        "triggers",
        "validates",
        "enforces",
        "supersedes",
        "references",
        "conflicts_with",
    }
)

# Allowed (relation, from_type, to_type) triples per PRD §4.4.
# A relation may appear multiple times with different type pairs.
ALLOWED_RELATIONS: frozenset[tuple[str, str, str]] = frozenset(
    {
        # part_of: flow/capability/form/event → module,
        # plus module → module for hierarchical layouts (e.g. multi-repo
        # workspaces where inner apps are part_of the parent repo).
        ("part_of", "flow", "module"),
        ("part_of", "capability", "module"),
        ("part_of", "form", "module"),
        ("part_of", "event", "module"),
        ("part_of", "module", "module"),
        # implements: flow → capability
        ("implements", "flow", "capability"),
        # depends_on: module/flow → module/flow
        ("depends_on", "module", "module"),
        ("depends_on", "module", "flow"),
        ("depends_on", "flow", "module"),
        ("depends_on", "flow", "flow"),
        # triggers: flow/event → event/flow
        ("triggers", "flow", "event"),
        ("triggers", "flow", "flow"),
        ("triggers", "event", "event"),
        ("triggers", "event", "flow"),
        # validates: form → rule
        ("validates", "form", "rule"),
        # enforces: rule → entity
        ("enforces", "rule", "entity"),
        # supersedes: flow/rule → flow/rule (same type only — semantic)
        ("supersedes", "flow", "flow"),
        ("supersedes", "rule", "rule"),
        # references: any → decision
        *(("references", t, "decision") for t in NODE_TYPES if t != "decision"),
        # conflicts_with: rule ↔ rule, flow ↔ flow (declared manually in v1)
        ("conflicts_with", "rule", "rule"),
        ("conflicts_with", "flow", "flow"),
    }
)

# IDs too generic to live unprefixed (audit warning only, not enforced).
GENERIC_ID_WORDS: frozenset[str] = frozenset(
    {
        "overview",
        "create",
        "update",
        "delete",
        "list",
        "show",
        "index",
        "detail",
        "form",
        "main",
        "default",
    }
)

NODE_STATUSES: frozenset[str] = frozenset(
    {"active", "draft", "deprecated", "superseded", "archived"}
)

# Canonical metadata.source values. Non-canonical values are persisted
# but emit a soft warning so the vocabulary can be tightened over time.
CANONICAL_SOURCES: frozenset[str] = frozenset(
    {
        "user_stated",
        "user_confirmed",
        "inferred_from_code",
        "inferred_from_conversation",
        "code_change",
        "scan",
        "incident",
        "manual",
    }
)

CANONICAL_CONFIDENCES: frozenset[str] = frozenset({"high", "medium", "low"})

# Tipos para los que el cuerpo (body) debería tener contenido descriptivo.
# Usado por el lint suave: persistimos igual, pero emitimos un warning.
BODY_REQUIRED_TYPES: frozenset[str] = frozenset({"capability", "flow"})
BODY_MIN_CHARS: int = 80


class SchemaError(ValueError):
    """Raised when a node or edge violates the schema."""


def validate_node_type(node_type: str) -> None:
    if node_type not in NODE_TYPES:
        raise SchemaError(
            f"Unknown node type {node_type!r}. Allowed: {sorted(NODE_TYPES)}"
        )


def validate_status(status: str) -> None:
    if status not in NODE_STATUSES:
        raise SchemaError(
            f"Unknown status {status!r}. Allowed: {sorted(NODE_STATUSES)}"
        )


def relations_allowed_for_pair(from_type: str, to_type: str) -> list[str]:
    """Return the sorted list of relations valid between these node types."""
    return sorted(
        {rel for (rel, ft, tt) in ALLOWED_RELATIONS if ft == from_type and tt == to_type}
    )


def relations_allowed_from(from_type: str) -> dict[str, list[str]]:
    """Return {to_type: [relations]} for everything reachable from from_type."""
    out: dict[str, set[str]] = {}
    for rel, ft, tt in ALLOWED_RELATIONS:
        if ft == from_type:
            out.setdefault(tt, set()).add(rel)
    return {k: sorted(v) for k, v in sorted(out.items())}


def validate_metadata_vocabulary(metadata: dict[str, Any] | None) -> None:
    """Reject metadata with `source` or `confidence` outside the canonical
    vocabulary. Missing keys remain a soft warning — only invalid values
    fail. Catching invalid values at write time stops vocabulary drift at
    the source instead of accumulating in `quality_report`."""
    if not metadata:
        return
    src = metadata.get("source")
    if src is not None and src not in CANONICAL_SOURCES:
        raise SchemaError(
            f"metadata.source={src!r} is not in the canonical vocabulary. "
            f"Use one of: {sorted(CANONICAL_SOURCES)}."
        )
    conf = metadata.get("confidence")
    if conf is not None and conf not in CANONICAL_CONFIDENCES:
        raise SchemaError(
            f"metadata.confidence={conf!r} is not canonical. "
            f"Use one of: {sorted(CANONICAL_CONFIDENCES)}."
        )


def validate_relation(relation: str) -> None:
    if relation not in RELATIONS:
        raise SchemaError(
            f"Unknown relation {relation!r}. "
            f"Allowed relations: {sorted(RELATIONS)}. "
            f"Tip: call dt_schema to see which relations apply to a type pair."
        )


def is_relation_allowed(relation: str, from_type: str, to_type: str) -> bool:
    """Return True if this relation is allowed between these node types."""
    return (relation, from_type, to_type) in ALLOWED_RELATIONS


def validate_edge_types(relation: str, from_type: str, to_type: str) -> None:
    validate_relation(relation)
    validate_node_type(from_type)
    validate_node_type(to_type)
    if not is_relation_allowed(relation, from_type, to_type):
        valid_for_pair = relations_allowed_for_pair(from_type, to_type)
        if valid_for_pair:
            hint = (
                f"Allowed for {from_type}→{to_type}: {valid_for_pair}."
            )
        else:
            # No relation is valid for this exact pair. Show what would be
            # valid from the same source type so the LLM can fix the to_id.
            from_targets = relations_allowed_from(from_type)
            if from_targets:
                hint = (
                    f"No relation is valid for {from_type}→{to_type}. "
                    f"From {from_type!r} you can reach: {from_targets}."
                )
            else:
                hint = f"No outgoing relations defined for {from_type!r}."
        raise SchemaError(
            f"Relation {relation!r} is not allowed from {from_type!r} to "
            f"{to_type!r}. {hint}"
        )


def _suggest_kebab(node_id: str) -> str:
    """Best-effort fix for common id mistakes (dots, colons, spaces, _,
    uppercase). Not a guarantee of validity — the caller still re-validates."""
    out = []
    last_was_sep = False
    for ch in node_id.strip():
        if ch.isalnum():
            out.append(ch.lower())
            last_was_sep = False
        else:
            if not last_was_sep and out:
                out.append("-")
                last_was_sep = True
    return "".join(out).strip("-")


def is_valid_id(node_id: str) -> bool:
    """DomainTome IDs are kebab-case: lowercase letters, digits, and hyphens; no
    leading/trailing hyphen; no double hyphens."""
    if not node_id:
        return False
    if node_id.startswith("-") or node_id.endswith("-"):
        return False
    if "--" in node_id:
        return False
    return all(c.islower() or c.isdigit() or c == "-" for c in node_id)


def _id_bad_chars(node_id: str) -> list[str]:
    seen: list[str] = []
    for ch in node_id:
        if ch.islower() or ch.isdigit() or ch == "-":
            continue
        if ch not in seen:
            seen.append(ch)
    return seen


def validate_id(node_id: str) -> None:
    if is_valid_id(node_id):
        return
    if not node_id:
        raise SchemaError("Invalid id: empty string. Use kebab-case.")
    bad = _id_bad_chars(node_id)
    suggestion = _suggest_kebab(node_id)
    parts: list[str] = [f"Invalid id {node_id!r}."]
    if bad:
        parts.append(f"Bad chars: {bad}.")
    if node_id.startswith("-") or node_id.endswith("-"):
        parts.append("Cannot start or end with '-'.")
    if "--" in node_id:
        parts.append("No double hyphens.")
    parts.append("Use kebab-case: lowercase letters, digits, single hyphens.")
    if suggestion and suggestion != node_id and is_valid_id(suggestion):
        parts.append(f"Did you mean {suggestion!r}?")
    raise SchemaError(" ".join(parts))


def schema_descriptor() -> dict[str, object]:
    """Machine-readable summary of the schema, exposed via the dt_schema
    MCP tool so an LLM can self-check before writing."""
    by_pair: dict[str, list[str]] = {}
    for rel, ft, tt in ALLOWED_RELATIONS:
        by_pair.setdefault(f"{ft}->{tt}", []).append(rel)
    return {
        "node_types": sorted(NODE_TYPES),
        "node_statuses": sorted(NODE_STATUSES),
        "relations": sorted(RELATIONS),
        "allowed_pairs": {k: sorted(v) for k, v in sorted(by_pair.items())},
        "metadata": {
            "source_canonical": sorted(CANONICAL_SOURCES),
            "confidence_canonical": sorted(CANONICAL_CONFIDENCES),
            "required_keys_recommended": ["source", "confidence", "source_ref"],
        },
        "id_format": (
            "kebab-case: lowercase letters, digits, single hyphens; "
            "no leading/trailing hyphen, no double hyphens"
        ),
        "body_min_chars_for": {
            t: BODY_MIN_CHARS for t in sorted(BODY_REQUIRED_TYPES)
        },
    }

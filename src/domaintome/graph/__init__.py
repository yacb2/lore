"""DomainTome graph engine — SQLite-backed typed graph of nodes and edges."""

from domaintome.graph.audit_log import history, log_call, stats
from domaintome.graph.db import connect, init_db, open_db
from domaintome.graph.edges import add_edge, add_edges_batch, list_edges, remove_edge
from domaintome.graph.nodes import (
    add_node,
    add_nodes_batch,
    delete_node,
    get_node,
    update_node,
)
from domaintome.graph.queries import audit, find_variants, list_nodes, query, traverse
from domaintome.graph.schema import (
    ALLOWED_RELATIONS,
    GENERIC_ID_WORDS,
    NODE_TYPES,
    RELATIONS,
    is_relation_allowed,
)

__all__ = [
    "ALLOWED_RELATIONS",
    "GENERIC_ID_WORDS",
    "NODE_TYPES",
    "RELATIONS",
    "add_edge",
    "add_edges_batch",
    "add_node",
    "add_nodes_batch",
    "audit",
    "connect",
    "delete_node",
    "find_variants",
    "get_node",
    "history",
    "init_db",
    "is_relation_allowed",
    "list_edges",
    "list_nodes",
    "log_call",
    "open_db",
    "query",
    "remove_edge",
    "stats",
    "traverse",
    "update_node",
]

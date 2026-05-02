"""SQLite connection and schema initialization for DomainTome."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS edges (
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    relation TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (from_id, to_id, relation),
    FOREIGN KEY (from_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (to_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_edges_from ON edges(from_id);
CREATE INDEX IF NOT EXISTS idx_edges_to ON edges(to_id);
CREATE INDEX IF NOT EXISTS idx_edges_relation ON edges(relation);
CREATE INDEX IF NOT EXISTS idx_nodes_type ON nodes(type);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tool TEXT NOT NULL,
    op TEXT NOT NULL,
    node_id TEXT,
    node_type TEXT,
    input_bytes INTEGER NOT NULL DEFAULT 0,
    output_bytes INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    warnings_count INTEGER NOT NULL DEFAULT 0,
    client_id TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_log(tool);
"""

# Aditivo: para DBs preexistentes (v0.0.x) extendemos audit_log con columnas
# nuevas sin romper compatibilidad. SQLite no soporta IF NOT EXISTS en
# ADD COLUMN, así que detectamos y aplicamos.
_AUDIT_LOG_COLUMNS_v01: tuple[tuple[str, str], ...] = (
    ("node_type", "TEXT"),
    ("latency_ms", "INTEGER"),
    ("warnings_count", "INTEGER NOT NULL DEFAULT 0"),
    ("client_id", "TEXT"),
)


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign keys enabled and Row factory set."""
    path = str(db_path)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def _migrate_audit_log(conn: sqlite3.Connection) -> None:
    """Add v0.1.0 columns to audit_log if running on a pre-existing DB."""
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(audit_log)").fetchall()
    }
    for name, decl in _AUDIT_LOG_COLUMNS_v01:
        if name not in cols:
            conn.execute(f"ALTER TABLE audit_log ADD COLUMN {name} {decl}")
    conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    """Create tables and indexes if they don't exist."""
    conn.executescript(SCHEMA_SQL)
    _migrate_audit_log(conn)
    conn.commit()


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open and initialize a database in one call."""
    conn = connect(db_path)
    init_db(conn)
    return conn

"""Shared helpers used across graph modules."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from typing import Any


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    meta = d.pop("metadata_json", None)
    d["metadata"] = json.loads(meta) if meta else {}
    return d


def placeholders(n: int) -> str:
    return ",".join("?" * n)

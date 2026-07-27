"""Sent-item ledger — **write path only** (FR-9).

Every item included in a delivered digest is durably recorded with its beat, timestamp,
rendered text, and source observation. SQLite at ``data/ledger.db``, gitignored.

## Why this is write-only, and what must not be added here

FR-9 states plainly that nothing reads the ledger to make decisions in v1, and PRD §9
**Q3 — what makes two items "the same story" (URL, entity+date, or a model judgment) —
is unresolved.** FR-9b (dedup / "what's new" framing) is `[Later]` and blocked on it.

So this module deliberately has:

- **no** identity, fingerprint, or "same story" column,
- **no** content hash,
- **no** similarity check,
- **no** `SELECT` used to filter what goes into a digest.

A surrogate autoincrement `id` plus `run_id` is fine — those identify *a row*, not *a
story*. If the schema ever seems to want a semantic identity column, that is the blocker:
surface it, don't decide it.

The read helpers below exist for tests and for a human inspecting the file. Nothing in
the pipeline calls them, and nothing should until Q3 is answered.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "ledger.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sent_items (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                TEXT    NOT NULL,
    beat                  TEXT    NOT NULL,
    sent_at               TEXT    NOT NULL,
    rendered_text         TEXT    NOT NULL,
    source_observation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_sent_items_run_id ON sent_items(run_id);
"""


@dataclass(frozen=True)
class SentItem:
    """One delivered line, as stored."""

    id: int
    run_id: str
    beat: str
    sent_at: str
    rendered_text: str
    source_observation_id: str | None


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and create, idempotently) the ledger database."""
    db_path = Path(path) if path is not None else DEFAULT_LEDGER_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    return connection


def create_schema(connection: sqlite3.Connection) -> None:
    """Idempotent. Running it on an existing database is a no-op."""
    connection.executescript(SCHEMA)
    connection.commit()


def _first_observation_id(item: Any) -> str | None:
    observations = getattr(item, "observations", None) or []
    for ref in observations:
        observation_id = getattr(ref, "observation_id", None)
        if isinstance(observation_id, str) and observation_id:
            return observation_id
    return None


def record_delivered_items(
    digest: Any,
    run_id: str,
    *,
    path: str | Path | None = None,
    connection: sqlite3.Connection | None = None,
    sent_at: datetime | None = None,
) -> int:
    """Append one row per delivered item. Called **after a successful delivery**.

    Returns the number of rows written. Appending only — no upsert, no dedup, no
    conflict resolution, because there is no identity to resolve against.
    """
    stamp = (sent_at or datetime.now(timezone.utc)).isoformat()
    rows = [
        (
            run_id,
            getattr(entry, "beat", "") or getattr(getattr(entry, "item", None), "beat", ""),
            stamp,
            getattr(getattr(entry, "item", entry), "text", str(entry)),
            _first_observation_id(getattr(entry, "item", entry)),
        )
        for entry in getattr(digest, "ordered", digest).items
    ]

    owned = connection is None
    conn = connection if connection is not None else connect(path)
    try:
        conn.executemany(
            "INSERT INTO sent_items (run_id, beat, sent_at, rendered_text, "
            "source_observation_id) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    finally:
        if owned:
            conn.close()
    return len(rows)


# --------------------------------------------------------------------------- #
# Inspection helpers — for tests and for a human, never for a pipeline decision
# --------------------------------------------------------------------------- #


def rows_for_run(
    run_id: str, *, path: str | Path | None = None, connection: sqlite3.Connection | None = None
) -> list[SentItem]:
    owned = connection is None
    conn = connection if connection is not None else connect(path)
    try:
        cursor = conn.execute(
            "SELECT * FROM sent_items WHERE run_id = ? ORDER BY id", (run_id,)
        )
        return [SentItem(**dict(row)) for row in cursor.fetchall()]
    finally:
        if owned:
            conn.close()


def all_rows(
    *, path: str | Path | None = None, connection: sqlite3.Connection | None = None
) -> list[SentItem]:
    owned = connection is None
    conn = connection if connection is not None else connect(path)
    try:
        cursor = conn.execute("SELECT * FROM sent_items ORDER BY id")
        return [SentItem(**dict(row)) for row in cursor.fetchall()]
    finally:
        if owned:
            conn.close()


__all__ = [
    "DEFAULT_LEDGER_PATH",
    "SCHEMA",
    "SentItem",
    "all_rows",
    "connect",
    "create_schema",
    "record_delivered_items",
    "rows_for_run",
]

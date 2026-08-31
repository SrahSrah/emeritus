"""Sent-item ledger — the write path, and the index FR-9b reads (FR-9).

Every item included in a delivered digest is durably recorded with its beat, timestamp,
rendered text, source observation, and the checkable values it stated. SQLite at
``data/ledger.db``, gitignored.

## PRD §9 Q3 is answered — here is what that did and did not change

Through the v1 build this module was **write-only**, because §9 Q3 — *what makes two items
"the same story"* — was open, and FR-9b was blocked on it. Sarah answered it on
2026-08-02:

> **Item identity is not a property of an item. It is a relation computed at read time
> between a candidate and what has already been sent.**

That answer is why this schema still has **no identity column, no fingerprint, no content
hash, and no dedup key** — stamping a row with "this is story #47" at write time would
freeze a judgment that only makes sense in context, and it is exactly the shortcut the
original guard was protecting against. The surrogate `id` identifies *a row*, not *a
story*, and still does.

What is new:

- **`checkable_fields`** — the observed values the line stated, as JSON. Not an identity.
  FR-9b's load-bearing safety rule ("a differing checkable value can never be suppressed")
  is impossible without the neighbour's actual values to compare against. Since
  2026-08-31 the column holds the item's `fields` merged with the beat's declared
  checkable facts: FR-19's disjoint-key clause treats a key absent from every stored
  neighbour as "the reader was never told this", so omitting the beat-level facts here
  would make every night's counts look new forever.
- **A vector index** (`vec_sent_items`, in `retrieval.py`) — a read-time *accelerator* for
  the similarity search. It stores no verdict.

Reads now happen, and are confined to `forecaster.memory.retrieval`. Nothing else queries
this table to make a decision.
"""

from __future__ import annotations

import json
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
    source_observation_id TEXT,
    checkable_fields      TEXT
);
CREATE INDEX IF NOT EXISTS idx_sent_items_run_id ON sent_items(run_id);
CREATE INDEX IF NOT EXISTS idx_sent_items_beat_sent_at ON sent_items(beat, sent_at);
"""

# Columns added after the first ledgers were written. SQLite has no "ADD COLUMN IF NOT
# EXISTS", so migration is explicit rather than a silent CREATE-only schema.
_MIGRATIONS = (("checkable_fields", "ALTER TABLE sent_items ADD COLUMN checkable_fields TEXT"),)


@dataclass(frozen=True)
class SentItem:
    """One delivered line, as stored."""

    id: int
    run_id: str
    beat: str
    sent_at: str
    rendered_text: str
    source_observation_id: str | None
    checkable_fields: str | None = None

    @property
    def fields(self) -> dict[str, Any]:
        try:
            parsed = json.loads(self.checkable_fields or "{}")
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


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
    existing = {row[1] for row in connection.execute("PRAGMA table_info(sent_items)")}
    for column, statement in _MIGRATIONS:
        if column not in existing:
            connection.execute(statement)
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
    embedder: Any = None,
) -> int:
    """Append one row per delivered item. Called **after a successful delivery**.

    Returns the number of rows written. Appending only — no upsert, no conflict
    resolution, because there is still no stored identity to resolve against. Two rows
    with identical text are two deliveries, and that is a fact worth keeping.

    When an `embedder` is supplied, each row's rendered text is also indexed into
    `vec_sent_items` so tomorrow night's FR-9b retrieval can find it. Indexing failures
    are swallowed on purpose: a broken vector index must not lose the ledger row or fail
    a run that has *already delivered*.
    """
    stamp = (sent_at or datetime.now(timezone.utc)).isoformat()
    entries = list(getattr(digest, "ordered", digest).items)
    # The stored `checkable_fields` is the item's `fields` merged with the beat's
    # declared checkable facts (`Digest.checkable_by_beat`) — a wsb ticker count is a
    # value the line stated, and a row that omits it reads as "never told this fact"
    # to FR-19's disjoint-key clause forever after (measured 2026-08-31). Beat-level
    # granularity means a multi-item beat's rows each carry the whole declared dict;
    # the over-approximation errs toward reframe, never toward silence.
    checkable_by_beat = dict(getattr(digest, "checkable_by_beat", None) or {})
    rows = []
    for entry in entries:
        beat = getattr(entry, "beat", "") or getattr(getattr(entry, "item", None), "beat", "")
        declared = dict(checkable_by_beat.get(beat) or {})
        fields = dict(getattr(getattr(entry, "item", entry), "fields", None) or {})
        rows.append(
            (
                run_id,
                beat,
                stamp,
                getattr(getattr(entry, "item", entry), "text", str(entry)),
                _first_observation_id(getattr(entry, "item", entry)),
                json.dumps({**declared, **fields}, default=str),
            )
        )

    owned = connection is None
    conn = connection if connection is not None else connect(path)
    try:
        first_id = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM sent_items"
        ).fetchone()[0]
        conn.executemany(
            "INSERT INTO sent_items (run_id, beat, sent_at, rendered_text, "
            "source_observation_id, checkable_fields) VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()

        if embedder is not None and rows:
            try:
                from forecaster.memory import retrieval

                retrieval.create_vector_schema(conn, embedder.dimensions)
                vectors = embedder.encode([row[3] for row in rows])
                for offset, vector in enumerate(vectors):
                    retrieval.index_item(conn, int(first_id) + offset + 1, vector)
            except Exception:  # noqa: BLE001 - the ledger row is the durable part
                pass
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

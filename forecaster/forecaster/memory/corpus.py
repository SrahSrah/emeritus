"""Article chunks: the corpus, and the chunking that fills it (FR-22, FR-23, FR-24).

This is the first place in the project where retrieval runs over documents Sarah did not
write. FR-9b's corpus is the sent-item ledger, whose records are single delivered
sentences — one line is one atomic record, so it needed no chunking at all, and
Checkpoint 3 said as much ("How did I chunk it? I didn't"). Articles are different, and
this module is the difference.

## The three parts

1. **Chunking** (FR-22) — pure functions, no I/O. Paragraph-aware, with overlap, and a
   headline prefix on every chunk.
2. **The corpus** (FR-23) — a **separate** SQLite file from `ledger.db`, with its own
   lifecycle.
3. **Topic retrieval** (FR-24) — a query goes in, passages come out.

## Why the corpus is a separate file

The two corpora have opposite lifecycles. `sent_items` is the permanent record of what
was actually delivered and **cannot be rebuilt** if it is lost. Article chunks are
disposable and reconstructible from the feeds in a single run. At roughly 40 articles a
night times 5 chunks times a 7-day TTL, the chunk corpus is ~1,400 vectors against the
ledger's ~35 a week — sharing the file would have the disposable corpus dwarfing the
durable one. A corpus you can delete without losing anything does not belong in the file
holding the record you cannot rebuild.

Both use the **same `Embedder` instance**, passed in, so the model loads once per run.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from forecaster.memory.retrieval import (
    Embedder,
    create_vector_schema,
    index_item,
)

DEFAULT_CORPUS_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "corpus.db"

VEC_TABLE = "vec_chunks"
VEC_KEY = "chunk_id"

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    url          TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    headline     TEXT NOT NULL,
    published    TEXT NOT NULL,
    fetched_at   TEXT NOT NULL,
    text_source  TEXT NOT NULL,
    body_chars   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    url         TEXT NOT NULL REFERENCES articles(url),
    ordinal     INTEGER NOT NULL,
    text        TEXT NOT NULL,
    char_start  INTEGER NOT NULL,
    char_end    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_url ON chunks(url);
CREATE INDEX IF NOT EXISTS idx_articles_published ON articles(published);
CREATE INDEX IF NOT EXISTS idx_articles_fetched_at ON articles(fetched_at);
"""

#: Sentence-ish boundaries, used only when a single paragraph exceeds `max_chars`.
_SENTENCE_END = re.compile(r"[.!?][\"')\]]?\s")


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage of an article.

    ``body_text`` is the raw slice of the article body; ``char_start`` and ``char_end``
    index into that body and **exclude** the headline prefix. Keeping the two apart is
    what makes the round-trip assertion in the tests possible — an off-by-one in the
    overlap arithmetic is otherwise invisible until retrieval quality quietly degrades.

    ``text`` is what gets embedded and stored: the headline on its own line, then the
    body slice. The prefix matters because a mid-article chunk carries no subject on its
    own, and the shipped embedder is close to a bag of words — the parent build measured
    cosine 0.9859 between two different Astros scores, so it is not a model that infers
    much from context.
    """

    ordinal: int
    body_text: str
    char_start: int
    char_end: int
    headline: str = ""

    @property
    def text(self) -> str:
        if not self.headline:
            return self.body_text
        return f"{self.headline}\n{self.body_text}"


def _paragraph_spans(body: str) -> list[tuple[int, int]]:
    """Contiguous ``(start, end)`` spans, one per paragraph.

    Contiguous on purpose: the separator between two paragraphs belongs to the one before
    it, so the spans tile the body with no gaps and
    ``"".join(body[s:e] for s, e in spans) == body``. Reconstruction depends on that.
    """
    if not body:
        return []
    boundaries = [match.end() for match in re.finditer(r"\n\s*\n", body)]
    spans: list[tuple[int, int]] = []
    cursor = 0
    for boundary in boundaries:
        spans.append((cursor, boundary))
        cursor = boundary
    spans.append((cursor, len(body)))
    return [(start, end) for start, end in spans if end > start]


def _split_long_paragraph(body: str, start: int, limit: int) -> int:
    """Where to cut a single paragraph that is longer than ``max_chars`` on its own.

    Prefers a sentence boundary, falls back to whitespace, and hard-cuts only when the
    text offers neither. A hard cut is ugly but honest — it never drops or reorders a
    character, which is what the reconstruction assertion checks.
    """
    ceiling = min(start + limit, len(body))
    window = body[start:ceiling]

    sentence_ends = [match.end() for match in _SENTENCE_END.finditer(window)]
    if sentence_ends:
        return start + sentence_ends[-1]

    space = window.rfind(" ")
    if space > 0:
        return start + space + 1

    return ceiling


def chunk_article(
    headline: str,
    body: str,
    *,
    target_chars: int,
    max_chars: int,
    overlap_chars: int,
) -> list[Chunk]:
    """Split an article body into overlapping, paragraph-aligned chunks.

    A body at or under ``target_chars`` comes back as exactly one chunk — which is the
    normal case for an entry that fell back to its feed summary, and the reason the
    summary path needs no special handling downstream.
    """
    if not body:
        return []
    if max_chars < target_chars:
        raise ValueError("max_chars must be at least target_chars")
    if overlap_chars >= target_chars:
        raise ValueError(
            "overlap_chars must be less than target_chars, or chunking never advances"
        )

    spans = _paragraph_spans(body)
    chunks: list[Chunk] = []
    cursor = 0
    ordinal = 0

    while cursor < len(body):
        end = cursor
        for span_start, span_end in spans:
            if span_end <= cursor:
                continue
            candidate = span_end
            if candidate - cursor > max_chars:
                break
            end = candidate
            if end - cursor >= target_chars:
                break

        if end <= cursor:
            # One paragraph is longer than max_chars all by itself.
            end = _split_long_paragraph(body, cursor, max_chars)

        chunks.append(
            Chunk(
                ordinal=ordinal,
                body_text=body[cursor:end],
                char_start=cursor,
                char_end=end,
                headline=headline,
            )
        )
        ordinal += 1

        if end >= len(body):
            break
        cursor = max(end - overlap_chars, cursor + 1)

    return chunks


def reconstruct(body: str, chunks: Sequence[Chunk]) -> str:
    """Rebuild the source body from chunk offsets, counting overlaps once.

    Lives here rather than only in the tests because it *is* the definition of a correct
    chunking: whatever the overlap arithmetic does, no character may be lost, duplicated
    into the wrong place, or reordered.
    """
    parts: list[str] = []
    covered_to = 0
    for chunk in sorted(chunks, key=lambda c: c.ordinal):
        if chunk.char_end <= covered_to:
            continue
        parts.append(body[max(chunk.char_start, covered_to) : chunk.char_end])
        covered_to = chunk.char_end
    return "".join(parts)


# --------------------------------------------------------------------------- #
# FR-23 — the store. A separate file from ledger.db, with its own lifecycle.
# --------------------------------------------------------------------------- #


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    """Open (and create, idempotently) the article corpus.

    Deliberately **not** `ledger.connect`. Nothing in this module opens `ledger.db`, and
    a test asserts that: the durable record of what was delivered and a disposable cache
    of what publishers said this week have no business sharing a file.
    """
    db_path = Path(path) if path is not None else DEFAULT_CORPUS_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    connection.commit()
    return connection


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def index_article(
    connection: sqlite3.Connection,
    entry: Any,
    chunks: Sequence[Chunk],
    embedder: Embedder,
    *,
    fetched_at: datetime | None = None,
) -> int:
    """Store one article and its chunks. Returns the number of chunks written.

    Re-indexing a url **replaces** its chunks rather than appending: an article fetched
    on two consecutive nights is one article, and duplicate chunks would let a single
    story crowd out every other result for a topic.
    """
    create_vector_schema(connection, embedder.dimensions, table=VEC_TABLE, key=VEC_KEY)
    stamp = (fetched_at or datetime.now(timezone.utc)).isoformat()
    body_chars = len(getattr(entry, "body", "") or "")

    _delete_chunks_for(connection, [entry.url])

    connection.execute(
        "INSERT OR REPLACE INTO articles "
        "(url, source, headline, published, fetched_at, text_source, body_chars) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            entry.url,
            entry.source,
            entry.headline,
            _iso(entry.published),
            stamp,
            getattr(entry, "text_source", "unfetched"),
            body_chars,
        ),
    )

    if not chunks:
        connection.commit()
        return 0

    vectors = embedder.encode([chunk.text for chunk in chunks])
    for chunk, vector in zip(chunks, vectors):
        cursor = connection.execute(
            "INSERT INTO chunks (url, ordinal, text, char_start, char_end) "
            "VALUES (?, ?, ?, ?, ?)",
            (entry.url, chunk.ordinal, chunk.text, chunk.char_start, chunk.char_end),
        )
        index_item(
            connection,
            int(cursor.lastrowid),
            vector,
            table=VEC_TABLE,
            key=VEC_KEY,
        )
    connection.commit()
    return len(chunks)


def _delete_chunks_for(connection: sqlite3.Connection, urls: Sequence[str]) -> None:
    """Drop chunks and their vectors together, so the index never outlives its rows."""
    if not urls:
        return
    placeholders = ",".join("?" for _ in urls)
    ids = [
        int(row[0])
        for row in connection.execute(
            f"SELECT id FROM chunks WHERE url IN ({placeholders})", tuple(urls)
        )
    ]
    if ids:
        id_placeholders = ",".join("?" for _ in ids)
        try:
            connection.execute(
                f"DELETE FROM {VEC_TABLE} WHERE {VEC_KEY} IN ({id_placeholders})",
                tuple(ids),
            )
        except sqlite3.Error:
            # The vec table may not exist yet on a first index. The chunk rows are the
            # durable part; an orphaned vector cannot be returned without its row.
            pass
    connection.execute(
        f"DELETE FROM chunks WHERE url IN ({placeholders})", tuple(urls)
    )


def purge_expired(
    connection: sqlite3.Connection, *, ttl_days: int, now: datetime | None = None
) -> int:
    """Delete articles fetched longer ago than the TTL. Returns the article count removed.

    Called at run start, **before** indexing, so a night's fetch never competes with
    last week's. The corpus is meant to be small and disposable; the ledger is not, and
    nothing here can touch it.
    """
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=ttl_days)).isoformat()
    urls = [
        str(row[0])
        for row in connection.execute(
            "SELECT url FROM articles WHERE fetched_at < ?", (cutoff,)
        )
    ]
    if not urls:
        return 0
    _delete_chunks_for(connection, urls)
    placeholders = ",".join("?" for _ in urls)
    connection.execute(
        f"DELETE FROM articles WHERE url IN ({placeholders})", tuple(urls)
    )
    connection.commit()
    return len(urls)


def article_count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM articles").fetchone()[0])


def chunk_count(connection: sqlite3.Connection) -> int:
    return int(connection.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])


def vector_count(connection: sqlite3.Connection) -> int:
    try:
        return int(connection.execute(f"SELECT COUNT(*) FROM {VEC_TABLE}").fetchone()[0])
    except sqlite3.Error:
        return 0


__all__ = [
    "DEFAULT_CORPUS_PATH",
    "SCHEMA",
    "VEC_KEY",
    "VEC_TABLE",
    "Chunk",
    "article_count",
    "chunk_article",
    "chunk_count",
    "connect",
    "index_article",
    "purge_expired",
    "reconstruct",
    "vector_count",
]

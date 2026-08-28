"""Semantic retrieval over the sent-item ledger (FR-9b, first half).

This module is the *retrieval* layer: it turns a candidate line into a vector, searches
the vectors of everything already delivered, and hands back the nearest prior items with
their similarity scores. It makes **no decision** — deciding whether a near-neighbour
means "you already know this" is `forecaster.memory.dedup`'s job, and it is a judgment,
not a threshold.

## What this answers, and what it deliberately does not add

PRD §9 **Q3 — what makes two items "the same story"** — was open through the whole v1
build, which is why FR-9 shipped write-only. Sarah answered it on 2026-08-02, and the
answer is a design position worth stating plainly:

> **Item identity is not a property of an item. It is a relation computed at read time
> between a candidate and what has already been sent.**

So there is still **no identity column, no fingerprint, no content hash, no dedup key** in
`sent_items`. Nothing is stamped with "this is story #47" at write time, because that
would freeze a judgment we can only make in context. What gets added is a vector *index* —
an accelerator for a read-time comparison, not a stored identity.

## Why the embedder is injected

The test suite forbids network access, and every real embedding model has to fetch weights
the first time it runs. So `Embedder` is a `Protocol`, the pipeline gets
:class:`StaticEmbedder` (model2vec, local, no torch), and the tests get
:class:`HashingEmbedder`, which is deterministic, offline, and — importantly — reproduces
the *same* near-duplicate collision the real model has. Same pattern as `FakeAgentClient`.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, Sequence, runtime_checkable

import numpy as np

# The model the nightly run uses. Static embeddings: no torch, no GPU, ~512 dims,
# fetched once to the HF cache and then read from disk.
DEFAULT_MODEL = "minishlab/potion-retrieval-32M"

# Retrieval defaults. Overridable from `config.toml`'s [retrieval] section.
DEFAULT_K = 5
DEFAULT_SIMILARITY_FLOOR = 0.60
DEFAULT_WINDOW_DAYS = 14


class RetrievalError(RuntimeError):
    """Retrieval could not run. Callers degrade to 'include'; they never guess."""


# --------------------------------------------------------------------------- #
# Embedder interface
# --------------------------------------------------------------------------- #


@runtime_checkable
class Embedder(Protocol):
    """Text in, unit-norm vectors out."""

    dimensions: int

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return an ``(len(texts), dimensions)`` float32 array of unit vectors."""
        ...


def _l2_normalize(matrix: np.ndarray) -> np.ndarray:
    """Unit-norm each row so a dot product *is* cosine similarity.

    A zero row (empty string) would divide by zero; it stays zero, which scores 0.0
    against everything. That is the honest answer for a line with no content.
    """
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (matrix / norms).astype(np.float32)


class StaticEmbedder:
    """model2vec static embeddings. What the real nightly run uses.

    Chosen over `sentence-transformers` because it needs no torch — the whole project's
    dependency list was four packages, and a multi-gigabyte install for a nightly job that
    embeds a handful of one-line items is not a trade worth making.
    """

    def __init__(self, model_name: str = DEFAULT_MODEL, *, model: Any = None) -> None:
        if model is None:
            try:
                from model2vec import StaticModel
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise RetrievalError(
                    "model2vec is not installed; retrieval cannot run"
                ) from exc
            model = StaticModel.from_pretrained(model_name)
        self._model = model
        self.model_name = model_name
        probe = _l2_normalize(np.asarray(self._model.encode(["dimension probe"])))
        self.dimensions = int(probe.shape[1])

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimensions), dtype=np.float32)
        return _l2_normalize(np.asarray(self._model.encode(list(texts))))


_TOKEN = re.compile(r"[a-z0-9]+")


class HashingEmbedder:
    """Deterministic, offline, dependency-free. **Tests only.**

    A hashed bag of words. It is not a good semantic model and is not pretending to be —
    its job is to be reproducible with no network. It does share the property that
    matters for the tests: two lines differing only in a numeral land almost on top of
    each other, which is the FR-9b failure mode we have to prove is handled.
    """

    def __init__(self, dimensions: int = 512) -> None:
        self.dimensions = dimensions

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dimensions), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in _TOKEN.findall((text or "").lower()):
                # Stable across processes: Python's str hash is salted, zlib's is not.
                import zlib

                out[row, zlib.crc32(token.encode()) % self.dimensions] += 1.0
        return _l2_normalize(out)


# --------------------------------------------------------------------------- #
# Vector store — a sqlite-vec index living inside the ledger database
# --------------------------------------------------------------------------- #


#: How a same-run neighbour (FR-37) identifies itself in the trace. Real ledger ids
#: start at 1, so 0 can never collide with a stored row.
SAME_RUN_SENT_ITEM_ID = 0
SAME_RUN_SENT_AT = "tonight, earlier in this digest"


@dataclass(frozen=True)
class Neighbour:
    """A previously delivered item that came back from the index."""

    sent_item_id: int
    beat: str
    sent_at: str
    rendered_text: str
    checkable_fields: dict[str, Any]
    similarity: float

    def as_record(self) -> dict[str, Any]:
        """The shape written into the run trace."""
        return {
            "sent_item_id": self.sent_item_id,
            "beat": self.beat,
            "sent_at": self.sent_at,
            "text": self.rendered_text,
            "similarity": round(self.similarity, 4),
        }


def load_vec(connection: sqlite3.Connection) -> None:
    """Load the sqlite-vec extension into an open connection."""
    try:
        import sqlite_vec

        connection.enable_load_extension(True)
        sqlite_vec.load(connection)
        connection.enable_load_extension(False)
    except Exception as exc:  # noqa: BLE001 - surfaces as a clean RetrievalError
        raise RetrievalError(f"could not load sqlite-vec: {exc}") from exc


#: The vec0 table name and key column for the sent-item index. FR-23's article corpus
#: passes its own; the defaults keep every pre-existing caller unchanged.
SENT_ITEM_VEC_TABLE = "vec_sent_items"
SENT_ITEM_VEC_KEY = "sent_item_id"


def create_vector_schema(
    connection: sqlite3.Connection,
    dimensions: int,
    *,
    table: str = SENT_ITEM_VEC_TABLE,
    key: str = SENT_ITEM_VEC_KEY,
) -> None:
    """Idempotent. The vec0 virtual table is keyed by the owning row's id.

    Parameterized by table name so FR-23's article corpus can reuse it. It is the *same*
    accelerator over a different corpus, not a second implementation — a second one would
    be a second place for the distance-to-similarity conversion to be got backwards.
    """
    load_vec(connection)
    connection.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING vec0("
        f"  {key} INTEGER PRIMARY KEY,"
        f"  embedding FLOAT[{dimensions}]"
        f")"
    )
    connection.commit()


def index_item(
    connection: sqlite3.Connection,
    sent_item_id: int,
    vector: np.ndarray,
    *,
    table: str = SENT_ITEM_VEC_TABLE,
    key: str = SENT_ITEM_VEC_KEY,
) -> None:
    """Store one row's vector against its owning id."""
    payload = np.asarray(vector, dtype=np.float32).reshape(-1).tobytes()
    connection.execute(
        f"INSERT OR REPLACE INTO {table} ({key}, embedding) VALUES (?, ?)",
        (sent_item_id, payload),
    )
    connection.commit()


def similarity_from_distance(distance: float) -> float:
    """sqlite-vec's KNN returns L2 distance; over unit vectors cosine is 1 - d²/2.

    Extracted so there is exactly one of these in the codebase. Getting it backwards
    means everything scores as a match, which looks like working software right up until
    it silently suppresses a real fact.
    """
    return 1.0 - (distance * distance) / 2.0


def retrieve_neighbours(
    connection: sqlite3.Connection,
    vector: np.ndarray,
    *,
    beat: str,
    k: int = DEFAULT_K,
    similarity_floor: float = DEFAULT_SIMILARITY_FLOOR,
    window_days: int = DEFAULT_WINDOW_DAYS,
    now: datetime | None = None,
) -> list[Neighbour]:
    """The k nearest previously-sent items, same beat, inside the time window.

    Scoping to one beat is not an optimisation — it is a correctness guard. A weather line
    and a score line have no business being compared, and letting them collide would make
    a suppression explainable only by an embedding artefact.

    Returns `[]` when the ledger is empty (the cold-start case), which callers must treat
    as "nothing known", never as "nothing new".
    """
    if k <= 0:
        return []

    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(days=window_days)).isoformat()
    payload = np.asarray(vector, dtype=np.float32).reshape(-1).tobytes()

    # sqlite-vec's KNN gives distance; over unit vectors cosine similarity is
    # 1 - (L2^2 / 2). Over-fetch, then filter by beat and window in SQL so a busy
    # neighbouring beat cannot crowd out this beat's real matches.
    try:
        cursor = connection.execute(
            """
            SELECT s.id, s.beat, s.sent_at, s.rendered_text, s.checkable_fields, v.distance
            FROM (
                SELECT sent_item_id, distance
                FROM vec_sent_items
                WHERE embedding MATCH ? AND k = ?
            ) AS v
            JOIN sent_items AS s ON s.id = v.sent_item_id
            WHERE s.beat = ? AND s.sent_at >= ?
            ORDER BY v.distance ASC
            """,
            (payload, max(k * 8, 40), beat, cutoff),
        )
        rows = cursor.fetchall()
    except sqlite3.Error as exc:
        raise RetrievalError(f"vector search failed: {exc}") from exc

    neighbours: list[Neighbour] = []
    for row in rows:
        similarity = similarity_from_distance(float(row[5]))
        if similarity < similarity_floor:
            continue
        try:
            fields = json.loads(row[4]) if row[4] else {}
        except (TypeError, ValueError):
            fields = {}
        neighbours.append(
            Neighbour(
                sent_item_id=int(row[0]),
                beat=str(row[1]),
                sent_at=str(row[2]),
                rendered_text=str(row[3]),
                checkable_fields=fields if isinstance(fields, dict) else {},
                similarity=similarity,
            )
        )
        if len(neighbours) >= k:
            break
    return neighbours


def same_run_neighbours(
    embedder: Embedder,
    text: str,
    prior: Sequence[tuple[str, dict[str, Any]]],
    *,
    beat: str,
    similarity_floor: float = DEFAULT_SIMILARITY_FLOOR,
) -> list[Neighbour]:
    """Items already kept in tonight's run, scored the way stored ones are (FR-37).

    Two items in one run can cover the same story — observed live 2026-08-13, when the
    `claude` and `agents` topics both wrote up one Anthropic finding — and the stored
    index cannot see them because nothing is written until after delivery. So the kept
    items are scored here, in memory, against the same floor, and handed to the decision
    layer as ordinary neighbours. Nothing is stored: identity stays a read-time relation,
    exactly as §9 Q3's answer prescribes.

    `prior` must already be scoped to one beat by the caller — same-beat comparison is a
    correctness guard (see :func:`retrieve_neighbours`), not this function's job to redo.
    """
    if not prior:
        return []
    vectors = embedder.encode([text, *[prior_text for prior_text, _ in prior]])
    similarities = vectors[1:] @ vectors[0]
    neighbours = [
        Neighbour(
            sent_item_id=SAME_RUN_SENT_ITEM_ID,
            beat=beat,
            sent_at=SAME_RUN_SENT_AT,
            rendered_text=prior_text,
            checkable_fields=dict(fields or {}),
            similarity=float(similarity),
        )
        for (prior_text, fields), similarity in zip(prior, similarities)
        if float(similarity) >= similarity_floor
    ]
    neighbours.sort(key=lambda neighbour: neighbour.similarity, reverse=True)
    return neighbours


# --------------------------------------------------------------------------- #
# The bundle the synthesizer is handed — connection + embedder + settings
# --------------------------------------------------------------------------- #


@dataclass
class LedgerRetriever:
    """Everything FR-9b needs to look something up, in one injectable object.

    The synthesizer receives this or `None`. `None` means retrieval is off and every item
    is included — which is exactly the v1 behaviour, so the seam is backwards compatible.
    """

    connection: sqlite3.Connection
    embedder: Embedder
    k: int = DEFAULT_K
    similarity_floor: float = DEFAULT_SIMILARITY_FLOOR
    window_days: int = DEFAULT_WINDOW_DAYS

    def __post_init__(self) -> None:
        create_vector_schema(self.connection, self.embedder.dimensions)

    def neighbours_for(
        self, text: str, *, beat: str, now: datetime | None = None
    ) -> list[Neighbour]:
        vector = self.embedder.encode([text])[0]
        return retrieve_neighbours(
            self.connection,
            vector,
            beat=beat,
            k=self.k,
            similarity_floor=self.similarity_floor,
            window_days=self.window_days,
            now=now,
        )

    def same_run_neighbours(
        self, text: str, prior: Sequence[tuple[str, dict[str, Any]]], *, beat: str
    ) -> list[Neighbour]:
        """FR-37 — score tonight's already-kept items with this retriever's own floor."""
        return same_run_neighbours(
            self.embedder, text, prior, beat=beat, similarity_floor=self.similarity_floor
        )


__all__ = [
    "DEFAULT_K",
    "DEFAULT_MODEL",
    "LedgerRetriever",
    "DEFAULT_SIMILARITY_FLOOR",
    "DEFAULT_WINDOW_DAYS",
    "SAME_RUN_SENT_AT",
    "SAME_RUN_SENT_ITEM_ID",
    "SENT_ITEM_VEC_KEY",
    "SENT_ITEM_VEC_TABLE",
    "Embedder",
    "HashingEmbedder",
    "Neighbour",
    "RetrievalError",
    "StaticEmbedder",
    "create_vector_schema",
    "index_item",
    "load_vec",
    "retrieve_neighbours",
    "same_run_neighbours",
    "similarity_from_distance",
]

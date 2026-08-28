"""FR-9b, retrieval half — the vector index over the sent-item ledger.

No network and no model call: the embedder is `HashingEmbedder`, which is deterministic
and offline. Every assertion here is about *finding candidates*; deciding what to do with
them is `test_dedup.py`.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from forecaster.memory.ledger import connect
from forecaster.memory.retrieval import (
    HashingEmbedder,
    LedgerRetriever,
    Neighbour,
    RetrievalError,
    create_vector_schema,
    index_item,
    retrieve_neighbours,
)

NOW = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)


def _seed(connection: sqlite3.Connection, embedder, rows) -> None:
    """Insert (beat, text, fields, days_ago) rows and index their vectors."""
    create_vector_schema(connection, embedder.dimensions)
    for beat, text, fields, days_ago in rows:
        import json

        sent_at = (NOW - timedelta(days=days_ago)).isoformat()
        cursor = connection.execute(
            "INSERT INTO sent_items (run_id, beat, sent_at, rendered_text, "
            "source_observation_id, checkable_fields) VALUES (?, ?, ?, ?, ?, ?)",
            ("seed", beat, sent_at, text, "obs-1", json.dumps(fields)),
        )
        index_item(connection, int(cursor.lastrowid), embedder.encode([text])[0])
    connection.commit()


# --------------------------------------------------------------------------- #
# The embedder contract
# --------------------------------------------------------------------------- #


def test_vectors_are_unit_norm_so_a_dot_product_is_cosine() -> None:
    vectors = HashingEmbedder().encode(["one line", "a rather different line"])
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)


def test_an_empty_string_scores_zero_against_everything() -> None:
    """A zero vector must not divide by zero, and must not look similar to anything."""
    vectors = HashingEmbedder().encode(["", "Astros beat the Rangers 4-2."])
    assert float(vectors[0] @ vectors[1]) == pytest.approx(0.0)


def test_the_hashing_embedder_is_stable_across_calls() -> None:
    first = HashingEmbedder().encode(["Astros beat the Rangers 4-2."])
    second = HashingEmbedder().encode(["Astros beat the Rangers 4-2."])
    assert np.allclose(first, second)


def test_the_test_embedder_reproduces_the_numeral_collision() -> None:
    """The failure mode FR-9b is built around, present in the offline double.

    Measured on the shipped model (`potion-retrieval-32M`, 2026-08-02) the same pair
    scores **0.9746** against **0.0037** for a score-vs-weather pair. The hashing double
    is cruder — it lands near 0.83, because one of six tokens changed — but the property
    the tests depend on is the same: two different games look like near-duplicates, and
    both sit far above the 0.60 retrieval floor.
    """
    vectors = HashingEmbedder().encode(
        [
            "Astros beat the Rangers 4-2.",
            "Astros beat the Rangers 5-2.",
            "Tomorrow 5-8 am: low 41F, 10% chance of rain.",
        ]
    )
    same_shape = float(vectors[0] @ vectors[1])
    different_beat = float(vectors[0] @ vectors[2])

    assert same_shape > 0.80, "two different games must look near-identical, or the "
    assert different_beat < 0.3


# --------------------------------------------------------------------------- #
# The index
# --------------------------------------------------------------------------- #


def test_a_seeded_item_is_retrievable_and_an_empty_ledger_returns_nothing(
    tmp_path: Path,
) -> None:
    embedder = HashingEmbedder()
    with connect(tmp_path / "ledger.db") as connection:
        create_vector_schema(connection, embedder.dimensions)

        cold = retrieve_neighbours(
            connection,
            embedder.encode(["Astros beat the Rangers 4-2."])[0],
            beat="astros",
            now=NOW,
        )
        assert cold == [], "cold start must return nothing, not something"

        _seed(connection, embedder, [("astros", "Astros beat the Rangers 4-2.", {"score": "4-2"}, 1)])

        found = retrieve_neighbours(
            connection,
            embedder.encode(["Astros beat the Rangers 5-2."])[0],
            beat="astros",
            now=NOW,
        )

    assert len(found) == 1
    assert found[0].rendered_text == "Astros beat the Rangers 4-2."
    assert found[0].checkable_fields == {"score": "4-2"}
    assert found[0].similarity > 0.80


def test_retrieval_is_scoped_to_one_beat(tmp_path: Path) -> None:
    """A weather line and a score line have no business being compared."""
    embedder = HashingEmbedder()
    with connect(tmp_path / "ledger.db") as connection:
        _seed(
            connection,
            embedder,
            [
                ("weather", "Astros beat the Rangers 4-2.", {}, 1),  # deliberately mislabelled
                ("astros", "Astros beat the Rangers 4-2.", {}, 1),
            ],
        )
        found = retrieve_neighbours(
            connection,
            embedder.encode(["Astros beat the Rangers 4-2."])[0],
            beat="astros",
            now=NOW,
        )

    assert len(found) == 1
    assert all(neighbour.beat == "astros" for neighbour in found)


def test_items_outside_the_window_are_not_retrieved(tmp_path: Path) -> None:
    embedder = HashingEmbedder()
    with connect(tmp_path / "ledger.db") as connection:
        _seed(connection, embedder, [("astros", "Astros beat the Rangers 4-2.", {}, 40)])
        found = retrieve_neighbours(
            connection,
            embedder.encode(["Astros beat the Rangers 4-2."])[0],
            beat="astros",
            window_days=14,
            now=NOW,
        )
    assert found == []


def test_the_similarity_floor_excludes_a_distant_item(tmp_path: Path) -> None:
    embedder = HashingEmbedder()
    with connect(tmp_path / "ledger.db") as connection:
        _seed(connection, embedder, [("astros", "Completely unrelated wording here.", {}, 1)])
        found = retrieve_neighbours(
            connection,
            embedder.encode(["Astros beat the Rangers 4-2."])[0],
            beat="astros",
            similarity_floor=0.60,
            now=NOW,
        )
    assert found == []


def test_k_caps_the_number_returned_and_the_nearest_comes_first(tmp_path: Path) -> None:
    embedder = HashingEmbedder()
    with connect(tmp_path / "ledger.db") as connection:
        _seed(
            connection,
            embedder,
            [
                ("astros", "Astros beat the Rangers 4-2.", {}, 1),
                ("astros", "Astros beat the Rangers 6-1.", {}, 2),
                ("astros", "Astros beat the Rangers 9-0.", {}, 3),
                ("astros", "Astros lost to the Rangers 1-2.", {}, 4),
            ],
        )
        found = retrieve_neighbours(
            connection,
            embedder.encode(["Astros beat the Rangers 5-2."])[0],
            beat="astros",
            k=2,
            now=NOW,
        )

    assert len(found) == 2
    assert found[0].similarity >= found[1].similarity


def test_similarity_is_derived_from_distance_and_stays_in_range(tmp_path: Path) -> None:
    """An identical line must score ~1.0, not 0.0 — the distance conversion is easy to
    get backwards, and backwards would mean nothing is ever a duplicate."""
    embedder = HashingEmbedder()
    text = "Astros beat the Rangers 4-2."
    with connect(tmp_path / "ledger.db") as connection:
        _seed(connection, embedder, [("astros", text, {}, 1)])
        found = retrieve_neighbours(
            connection, embedder.encode([text])[0], beat="astros", now=NOW
        )

    assert found[0].similarity == pytest.approx(1.0, abs=1e-3)


# --------------------------------------------------------------------------- #
# The injectable bundle
# --------------------------------------------------------------------------- #


def test_ledger_retriever_creates_its_schema_and_finds_neighbours(tmp_path: Path) -> None:
    embedder = HashingEmbedder()
    connection = connect(tmp_path / "ledger.db")
    retriever = LedgerRetriever(connection=connection, embedder=embedder)
    _seed(connection, embedder, [("astros", "Astros beat the Rangers 4-2.", {}, 1)])

    found = retriever.neighbours_for(
        "Astros beat the Rangers 5-2.", beat="astros", now=NOW
    )
    connection.close()

    assert len(found) == 1


def test_a_neighbour_renders_a_trace_record() -> None:
    """The trace has to be able to show *what* was retrieved and how close it was."""
    record = Neighbour(
        sent_item_id=7,
        beat="astros",
        sent_at="2026-07-26T19:00:00",
        rendered_text="Astros beat the Rangers 4-2.",
        checkable_fields={"score": "4-2"},
        similarity=0.974612,
    ).as_record()

    assert record["sent_item_id"] == 7
    assert record["similarity"] == 0.9746
    assert record["text"] == "Astros beat the Rangers 4-2."


def test_a_broken_index_raises_rather_than_returning_a_wrong_answer(tmp_path: Path) -> None:
    embedder = HashingEmbedder()
    connection = connect(tmp_path / "ledger.db")
    # No vector schema created — the query has nothing to match against.
    with pytest.raises(RetrievalError):
        retrieve_neighbours(
            connection, embedder.encode(["anything"])[0], beat="astros", now=NOW
        )
    connection.close()

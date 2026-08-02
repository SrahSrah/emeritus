"""FR-9b's acceptance criterion, and the demonstration Checkpoint 3 cites.

> *Done when a fixture pair representing the same story on consecutive nights produces a
> suppression or a reframe, with the decision and its reason in the run trace.*

The shape of every test here is the same: run the **same night twice** — once against an
empty ledger, once against a ledger already holding last night's item — and compare the
two rendered digests. Retrieval is the only thing that differs between the runs, so any
difference in output is attributable to it.

No network, no model call: `HashingEmbedder` for vectors, a scripted client for verdicts.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecaster.agent import AgentResponse
from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.memory.ledger import connect
from forecaster.memory.retrieval import HashingEmbedder, LedgerRetriever, create_vector_schema, index_item
from forecaster.synthesizer import synthesize
from forecaster.trace import Trace, read_trace, records_of
from tests.helpers import make_config, make_preferences, trace_in

CONFIG = make_config()
NOW = datetime(2026, 7, 27, 19, 0, tzinfo=timezone.utc)

LAST_NIGHT = "Final: Houston Astros 4, Texas Rangers 2."
TONIGHT_SAME_GAME = "Final: Houston Astros 4, Texas Rangers 2."
TONIGHT_NEW_GAME = "Final: Houston Astros 5, Texas Rangers 2."


class ScriptedClient:
    """Composes by concatenating lines (like `FakeAgentClient`), but answers dedup
    prompts with a fixed verdict. Never calls a model."""

    auth_mode = "subscription_oauth"

    def __init__(self, verdict: str = "SUPPRESS you were told this last night") -> None:
        self.verdict = verdict
        self.dedup_calls = 0

    def complete(self, prompt: str, *, structured=None, system=None, effort="low"):
        if structured and "candidate" in structured:
            self.dedup_calls += 1
            return AgentResponse(text=self.verdict, input_tokens=0, output_tokens=0)
        lines = list((structured or {}).get("lines", [])) + list(
            (structured or {}).get("unavailable", [])
        )
        return AgentResponse(text="\n".join(lines), input_tokens=0, output_tokens=0)


def _astros_result(trace: Trace, text: str, score: str) -> BeatResult:
    obs = trace.tool_call(beat="astros", adapter="mlb.fetch_schedule", arguments={})
    trace.observation(obs, payload=[{"final": score}])
    return BeatResult(
        beat="astros",
        items=[
            BeatItem(
                beat="astros",
                text=text,
                fields={"final_score": score},
                observations=[ObservationRef(obs, "mlb.fetch_schedule")],
            )
        ],
        checkable_fields={"final_score": score},
        observations=[ObservationRef(obs, "mlb.fetch_schedule")],
    )


def _retriever(tmp_path: Path, seeded: list[tuple[str, str]]):
    """A retriever over a ledger pre-loaded with `(text, score)` from previous nights."""
    embedder = HashingEmbedder()
    connection = connect(tmp_path / "ledger.db")
    create_vector_schema(connection, embedder.dimensions)
    for offset, (text, score) in enumerate(seeded):
        sent_at = (NOW - timedelta(days=offset + 1)).isoformat()
        cursor = connection.execute(
            "INSERT INTO sent_items (run_id, beat, sent_at, rendered_text, "
            "source_observation_id, checkable_fields) VALUES (?, ?, ?, ?, ?, ?)",
            ("night-0", "astros", sent_at, text, "obs-0", json.dumps({"final_score": score})),
        )
        index_item(connection, int(cursor.lastrowid), embedder.encode([text])[0])
    connection.commit()
    return LedgerRetriever(connection=connection, embedder=embedder)


def _run(tmp_path: Path, run_id: str, text: str, score: str, retriever):
    trace = trace_in(tmp_path, run_id)
    result = _astros_result(trace, text, score)
    client = ScriptedClient()
    digest = synthesize(
        [result],
        CONFIG,
        make_preferences(),
        trace,
        agent_client=client,
        retriever=retriever,
        now=NOW,
    )
    trace.close()
    return digest, trace.path, client


# --------------------------------------------------------------------------- #
# The acceptance criterion
# --------------------------------------------------------------------------- #


def test_the_same_story_two_nights_running_is_suppressed_the_second_time(
    tmp_path: Path,
) -> None:
    """The before/after. Same beat output, same config, different ledger."""
    cold = _retriever(tmp_path / "cold", [])
    warm = _retriever(tmp_path / "warm", [(LAST_NIGHT, "Houston Astros 4, Texas Rangers 2")])

    first, _, _ = _run(tmp_path, "night-1", TONIGHT_SAME_GAME, "Houston Astros 4, Texas Rangers 2", cold)
    second, _, client = _run(
        tmp_path, "night-2", TONIGHT_SAME_GAME, "Houston Astros 4, Texas Rangers 2", warm
    )

    cold.connection.close()
    warm.connection.close()

    assert TONIGHT_SAME_GAME in first.text, "an empty ledger must include the item"
    assert TONIGHT_SAME_GAME not in second.text, "a repeat must not survive the ledger check"
    assert [action for _, action in [(b, d.action) for b, d in second.dedup]] == ["suppress"]
    assert client.dedup_calls == 1


def test_a_different_game_survives_despite_near_identical_wording(tmp_path: Path) -> None:
    """Invariant 1, end to end. This is the failure mode the design exists to survive."""
    warm = _retriever(tmp_path / "warm", [(LAST_NIGHT, "Houston Astros 4, Texas Rangers 2")])
    similarity = warm.neighbours_for(TONIGHT_NEW_GAME, beat="astros", now=NOW)[0].similarity

    digest, _, client = _run(
        tmp_path, "night-3", TONIGHT_NEW_GAME, "Houston Astros 5, Texas Rangers 2", warm
    )
    warm.connection.close()

    assert similarity > 0.85, "the two lines must genuinely look alike, or this proves nothing"
    assert TONIGHT_NEW_GAME in digest.text
    assert digest.dedup[0][1].action == "reframe"
    assert digest.dedup[0][1].forced is True
    assert client.dedup_calls == 0, "the model must not get a say when a score moved"


def test_the_decision_and_its_reason_land_in_the_trace(tmp_path: Path) -> None:
    """'with the decision and its reason in the run trace' — the criterion, literally."""
    warm = _retriever(tmp_path / "warm", [(LAST_NIGHT, "Houston Astros 4, Texas Rangers 2")])
    _, trace_path, _ = _run(
        tmp_path, "night-4", TONIGHT_SAME_GAME, "Houston Astros 4, Texas Rangers 2", warm
    )
    warm.connection.close()

    decisions = [
        record
        for record in records_of(read_trace(trace_path), "decision")
        if str(record.get("decision", "")).startswith("dedup_")
    ]

    assert len(decisions) == 1
    record = decisions[0]
    assert record["decision"] == "dedup_suppress"
    assert record["reason"]
    assert record["neighbours"][0]["text"] == LAST_NIGHT
    assert record["top_similarity"] > 0.85


def test_retrieval_disabled_reproduces_the_v1_digest_exactly(tmp_path: Path) -> None:
    """`retriever=None` is the v1 pipeline. The seam has to be reversible."""
    warm = _retriever(tmp_path / "warm", [(LAST_NIGHT, "Houston Astros 4, Texas Rangers 2")])

    with_retrieval, _, _ = _run(
        tmp_path, "night-5", TONIGHT_SAME_GAME, "Houston Astros 4, Texas Rangers 2", warm
    )
    without, _, _ = _run(
        tmp_path, "night-6", TONIGHT_SAME_GAME, "Houston Astros 4, Texas Rangers 2", None
    )
    warm.connection.close()

    assert TONIGHT_SAME_GAME not in with_retrieval.text
    assert TONIGHT_SAME_GAME in without.text
    assert without.dedup == []


def test_a_broken_retriever_still_delivers_the_digest(tmp_path: Path) -> None:
    """Invariant 4, end to end: a dead index must not silence the night."""

    class BrokenRetriever:
        def neighbours_for(self, *args, **kwargs):
            raise RuntimeError("index corrupt")

    digest, trace_path, _ = _run(
        tmp_path, "night-7", TONIGHT_SAME_GAME, "Houston Astros 4, Texas Rangers 2",
        BrokenRetriever(),
    )

    failures = [
        record
        for record in records_of(read_trace(trace_path), "decision")
        if record.get("decision") == "retrieval_failed"
    ]

    assert TONIGHT_SAME_GAME in digest.text
    assert len(failures) == 1
    assert "index corrupt" in failures[0]["reason"]


def test_a_suppressed_run_still_passes_the_provenance_check(tmp_path: Path) -> None:
    """FR-11 is unchanged by FR-9b. Removing a line must not orphan a claim."""
    warm = _retriever(tmp_path / "warm", [(LAST_NIGHT, "Houston Astros 4, Texas Rangers 2")])
    digest, _, _ = _run(
        tmp_path, "night-8", TONIGHT_SAME_GAME, "Houston Astros 4, Texas Rangers 2", warm
    )
    warm.connection.close()

    assert digest.provenance is not None
    assert digest.provenance.ok, digest.provenance.summary()

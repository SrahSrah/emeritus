"""FR-9b, judgment half — the five safety invariants, one test each.

These are not tuning parameters. Each one is a rule that must hold whatever the embedding
scores and whatever the model says, which is why they are enforced *around* the model
rather than requested of it — the same reasoning as FR-11's provenance check.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from forecaster.agent import AgentResponse, FakeAgentClient
from forecaster.beats.base import BeatItem
from forecaster.memory.dedup import DedupDecision, assess_item
from forecaster.memory.retrieval import Neighbour


class VerdictClient:
    """An agent double that returns a fixed verdict. Never calls a model."""

    auth_mode = "subscription_oauth"

    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[Mapping[str, Any] | None] = []

    def complete(self, prompt: str, *, structured=None, system=None, effort="low"):
        self.calls.append(structured)
        return AgentResponse(text=self.verdict, input_tokens=0, output_tokens=0)


class ExplodingClient:
    auth_mode = "subscription_oauth"

    def complete(self, *args: Any, **kwargs: Any):
        raise RuntimeError("model unavailable")


def _neighbour(text: str, fields: dict[str, Any], similarity: float = 0.97) -> Neighbour:
    return Neighbour(
        sent_item_id=1,
        beat="astros",
        sent_at="2026-07-26T19:00:00",
        rendered_text=text,
        checkable_fields=fields,
        similarity=similarity,
    )


def _item(text: str, fields: dict[str, Any]) -> BeatItem:
    return BeatItem(beat="astros", text=text, fields=fields)


# --------------------------------------------------------------------------- #
# Invariant 1 — a differing checkable value can never be suppressed
# --------------------------------------------------------------------------- #


def test_a_changed_score_is_never_suppressed_however_similar_the_wording() -> None:
    """The load-bearing test. Cosine 0.9746 on the real model; the scores differ."""
    decision = assess_item(
        _item("Astros beat the Rangers 5-2.", {"score": "5-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"}, 0.9746)],
        agent_client=VerdictClient("SUPPRESS it adds nothing"),
        beat="astros",
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert "4-2" in decision.reason and "5-2" in decision.reason


def test_the_model_is_not_even_asked_when_a_checkable_value_moved() -> None:
    """An invariant that can be talked out of is not an invariant."""
    client = VerdictClient("SUPPRESS")
    assess_item(
        _item("Astros beat the Rangers 5-2.", {"score": "5-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=client,
        beat="astros",
    )
    assert client.calls == []


def test_a_value_that_only_changed_type_is_not_treated_as_news() -> None:
    """4 and 4.0 and "4" are the same observation. A type change is not information."""
    client = VerdictClient("SUPPRESS same game, nothing new")
    decision = assess_item(
        _item("Run-window low 41F.", {"run_window_low_f": 41}),
        [_neighbour("Run-window low 41F.", {"run_window_low_f": "41.0"})],
        agent_client=client,
        beat="astros",
    )
    assert decision.action == "suppress"


def test_a_newly_declared_field_is_always_included() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2; Alvarez left in the 3rd.", {"score": "4-2", "injury": "Alvarez"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=VerdictClient("SUPPRESS"),
        beat="astros",
    )
    assert decision.action == "include"
    assert decision.forced is True
    assert "injury" in decision.reason


# --------------------------------------------------------------------------- #
# Invariant 2 — an escalation candidate can never be suppressed
# --------------------------------------------------------------------------- #


def test_an_escalated_item_survives_even_a_perfect_duplicate() -> None:
    """A freeze alert is not less urgent for resembling last night's freeze alert."""
    decision = assess_item(
        _item("Freeze alert: 28F at 6 am.", {"run_window_low_f": "28"}),
        [_neighbour("Freeze alert: 28F at 6 am.", {"run_window_low_f": "28"}, 1.0)],
        agent_client=VerdictClient("SUPPRESS identical"),
        beat="weather",
        escalation_candidate=True,
    )
    assert decision.action == "include"
    assert decision.forced is True


# --------------------------------------------------------------------------- #
# Invariant 3 — cold start means "nothing known", not "nothing new"
# --------------------------------------------------------------------------- #


def test_an_empty_neighbour_set_includes_without_asking_the_model() -> None:
    client = VerdictClient("SUPPRESS")
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [],
        agent_client=client,
        beat="astros",
    )
    assert decision.action == "include"
    assert client.calls == []


# --------------------------------------------------------------------------- #
# Invariant 4 — a failure degrades to include, never to silence
# --------------------------------------------------------------------------- #


def test_a_model_failure_includes_the_item() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=ExplodingClient(),
        beat="astros",
    )
    assert decision.action == "include"
    assert "unavailable" in decision.reason


def test_an_unparseable_verdict_includes_the_item() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=VerdictClient("I'm not sure, could go either way"),
        beat="astros",
    )
    assert decision.action == "include"


def test_disabling_retrieval_includes_everything() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=VerdictClient("SUPPRESS"),
        beat="astros",
        enabled=False,
    )
    assert decision.action == "include"


# --------------------------------------------------------------------------- #
# Invariant 5 — every decision is auditable
# --------------------------------------------------------------------------- #


def test_a_suppression_names_the_item_it_duplicated_and_the_score() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"}, 0.99)],
        agent_client=VerdictClient("SUPPRESS you were told this last night"),
        beat="astros",
    )

    assert decision.action == "suppress"
    assert "#1" in decision.reason
    assert "0.99" in decision.reason
    record = decision.as_record()
    assert record["action"] == "suppress"
    assert record["neighbours"][0]["sent_item_id"] == 1


def test_the_model_only_ever_sees_text_already_delivered() -> None:
    """The dedup call must not become a second place a value can be invented."""
    client = VerdictClient("INCLUDE")
    assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=client,
        beat="astros",
    )
    payload = client.calls[0]
    assert set(payload) == {"candidate", "candidate_fields", "previously_sent"}
    assert payload["previously_sent"][0]["text"] == "Astros beat the Rangers 4-2."


# --------------------------------------------------------------------------- #
# The reframe path
# --------------------------------------------------------------------------- #


def test_a_reframe_verdict_carries_the_replacement_text() -> None:
    decision = assess_item(
        _item("The Astros are 4 games up in the West.", {"lead": "4"}),
        [_neighbour("The Astros are 4 games up in the West.", {"lead": "4"})],
        agent_client=VerdictClient(
            "REFRAME same standings story, the lead is what moved\n"
            "TEXT: Still 4 games up in the West — unchanged since last night."
        ),
        beat="astros",
    )

    assert decision.action == "reframe"
    assert decision.reframed_text == (
        "Still 4 games up in the West — unchanged since last night."
    )


def test_a_reframe_with_no_replacement_text_keeps_the_original() -> None:
    decision = assess_item(
        _item("The Astros are 4 games up.", {"lead": "4"}),
        [_neighbour("The Astros are 4 games up.", {"lead": "4"})],
        agent_client=VerdictClient("REFRAME but I forgot the text line"),
        beat="astros",
    )
    assert decision.action == "reframe"
    assert decision.reframed_text is None

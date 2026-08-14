"""FR-37 — within-run dedup: two items in ONE run covering one story.

FR-9b compares a candidate against the sent-item ledger, which only knows previous
nights. Observed live 2026-08-13: the `claude` and `agents` topics both wrote up the
same Anthropic finding, and the model appended a prose note about the duplication — a
guard's job done in prose, which this project is explicitly against. FR-37 feeds the
items already kept in the current run to `assess_item` as additional neighbours, same
beat only, with every FR-19 invariant unchanged.

Every test here runs against an **empty** ledger, so any dedup effect is attributable
to the same-run comparison alone. No network, no model call: `HashingEmbedder` for
vectors, a scripted client for verdicts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from forecaster.agent import AgentResponse
from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.memory.retrieval import (
    HashingEmbedder,
    SAME_RUN_SENT_AT,
    SAME_RUN_SENT_ITEM_ID,
    same_run_neighbours,
)
from forecaster.synthesizer import synthesize
from forecaster.trace import SYNTHESIZED, read_trace, records_of
from tests.helpers import make_config, make_preferences, make_retriever, trace_in

CONFIG = make_config()
NOW = datetime(2026, 8, 13, 19, 0, tzinfo=timezone.utc)

# One story, two topics. No digits and no quoted spans on purpose: FR-26's grounded-text
# check is exercised elsewhere; here the texts stay provenance-neutral so the only thing
# under test is the same-run comparison.
CLAUDE_TOPIC_LINE = "Anthropic and OpenAI are locked in a turf war over agent frameworks."
AGENTS_TOPIC_LINE = "Anthropic is locked in a turf war with OpenAI over agent frameworks."
NEW_ENTITY_LINE = (
    "Anthropic and OpenAI are locked in a turf war over agent frameworks, "
    "with Cognition joining."
)

CHUNK = "Anthropic and OpenAI are fighting a turf war over agent frameworks."


class ScriptedClient:
    """Concatenates lines like `FakeAgentClient`, but answers dedup prompts with a
    fixed verdict. Never calls a model."""

    auth_mode = "subscription_oauth"

    def __init__(self, verdict: str = "SUPPRESS the reader was already told this") -> None:
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


def _news_result(trace, beat: str, *texts_and_topics: tuple[str, str]) -> BeatResult:
    """A news-shaped BeatResult whose items each point at one chunk observation."""
    observation_id = trace.tool_call(
        beat=beat, adapter="corpus.retrieve_for_topic", arguments={"topic": "t"}
    )
    trace.observation(observation_id, payload=CHUNK)
    ref = ObservationRef(observation_id, "corpus.retrieve_for_topic")
    return BeatResult(
        beat=beat,
        items=[
            BeatItem(
                beat=beat,
                text=text,
                fields={"topic": topic, "text_origin": SYNTHESIZED},
                observations=[ref],
            )
            for text, topic in texts_and_topics
        ],
        checkable_fields={},
        observations=[ref],
    )


def _synthesize(tmp_path: Path, trace, results, client=None):
    client = client or ScriptedClient()
    for result in results:
        trace.beat_result(result)
    digest = synthesize(
        results,
        CONFIG,
        make_preferences(topics={"astros": 1.0, "weather": 1.0, "news": 1.0}),
        trace,
        agent_client=client,
        retriever=make_retriever(tmp_path),
        now=NOW,
    )
    trace.close()
    return digest, client


# --------------------------------------------------------------------------- #
# The acceptance criterion: the observed 2026-08-13 duplication, fixed
# --------------------------------------------------------------------------- #


def test_two_topics_covering_one_story_in_one_run_lose_the_second(tmp_path: Path) -> None:
    """Empty ledger, one run, two topics, one story. The second line must not survive."""
    trace = trace_in(tmp_path, "one-run")
    result = _news_result(
        trace, "news", (CLAUDE_TOPIC_LINE, "claude"), (AGENTS_TOPIC_LINE, "agents")
    )

    digest, client = _synthesize(tmp_path, trace, [result])

    assert CLAUDE_TOPIC_LINE in digest.text
    assert AGENTS_TOPIC_LINE not in digest.text
    assert [decision.action for _, decision in digest.dedup] == ["include", "suppress"]
    assert client.dedup_calls == 1, "same story, no new grounded value: the model judges"


def test_the_same_run_neighbour_is_identifiable_in_the_trace(tmp_path: Path) -> None:
    """Invariant 5: the decision must be auditable, and auditable as *same-run*."""
    trace = trace_in(tmp_path, "audited-run")
    result = _news_result(
        trace, "news", (CLAUDE_TOPIC_LINE, "claude"), (AGENTS_TOPIC_LINE, "agents")
    )
    _, _ = _synthesize(tmp_path, trace, [result])

    suppressions = [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record.get("decision") == "dedup_suppress"
    ]
    assert len(suppressions) == 1
    neighbour = suppressions[0]["neighbours"][0]
    assert neighbour["sent_item_id"] == SAME_RUN_SENT_ITEM_ID
    assert neighbour["sent_at"] == SAME_RUN_SENT_AT
    assert neighbour["text"] == CLAUDE_TOPIC_LINE


# --------------------------------------------------------------------------- #
# The FR-19 invariants hold against a same-run neighbour, unchanged
# --------------------------------------------------------------------------- #


def test_a_new_grounded_value_vetoes_within_run_suppression(tmp_path: Path) -> None:
    """FR-27 against a same-run sibling: a new entity survives, model not consulted."""
    trace = trace_in(tmp_path, "veto-run")
    result = _news_result(
        trace, "news", (CLAUDE_TOPIC_LINE, "claude"), (NEW_ENTITY_LINE, "agents")
    )

    digest, client = _synthesize(tmp_path, trace, [result])

    assert NEW_ENTITY_LINE in digest.text
    second = digest.dedup[1][1]
    assert second.action == "reframe"
    assert second.forced is True
    assert "Cognition" in second.reason
    assert client.dedup_calls == 0, "the model must not get a say over a new entity"


def test_a_differing_checkable_value_is_never_suppressed_within_run(tmp_path: Path) -> None:
    """Invariant 1, typed form: a doubleheader is two games, not one story twice."""
    trace = trace_in(tmp_path, "doubleheader-run")
    game_one = "Final: Houston Astros 4, Texas Rangers 2."
    game_two = "Final: Houston Astros 5, Texas Rangers 2."
    items = []
    for text, score in (
        (game_one, "Houston Astros 4, Texas Rangers 2"),
        (game_two, "Houston Astros 5, Texas Rangers 2"),
    ):
        observation_id = trace.tool_call(
            beat="astros", adapter="mlb.fetch_schedule", arguments={}
        )
        trace.observation(observation_id, payload=[{"final": score}])
        items.append(
            BeatItem(
                beat="astros",
                text=text,
                fields={"final_score": score},
                observations=[ObservationRef(observation_id, "mlb.fetch_schedule")],
            )
        )
    result = BeatResult(
        beat="astros", items=items, checkable_fields={}, observations=items[0].observations
    )

    client = ScriptedClient()
    digest = synthesize(
        [result],
        CONFIG,
        make_preferences(),
        trace,
        agent_client=client,
        retriever=make_retriever(tmp_path),
        now=NOW,
    )
    trace.close()

    assert game_one in digest.text
    assert game_two in digest.text
    second = digest.dedup[1][1]
    assert second.action == "reframe"
    assert second.forced is True
    assert client.dedup_calls == 0, "the model must not get a say when a score moved"


def test_an_escalation_candidate_is_never_suppressed_within_run(tmp_path: Path) -> None:
    """Invariant 2: escalation outranks tidiness, same-run neighbours included."""
    trace = trace_in(tmp_path, "escalated-run")
    result = _news_result(
        trace, "news", (CLAUDE_TOPIC_LINE, "claude"), (AGENTS_TOPIC_LINE, "agents")
    )
    result.escalation_candidate = True

    digest, client = _synthesize(tmp_path, trace, [result])

    assert AGENTS_TOPIC_LINE in digest.text
    second = digest.dedup[1][1]
    assert second.action == "include"
    assert second.forced is True
    assert client.dedup_calls == 0


# --------------------------------------------------------------------------- #
# Scope: same beat only, by design
# --------------------------------------------------------------------------- #


def test_within_run_neighbours_stay_inside_their_beat(tmp_path: Path) -> None:
    """FR-9b retrieval is same-beat by design; FR-37 adds no cross-beat semantics."""
    trace = trace_in(tmp_path, "two-beat-run")
    first = _news_result(trace, "news", (CLAUDE_TOPIC_LINE, "claude"))
    second = _news_result(trace, "other_news", (CLAUDE_TOPIC_LINE, "claude"))

    digest, client = _synthesize(tmp_path, trace, [first, second])

    assert digest.text.count(CLAUDE_TOPIC_LINE) == 2
    assert [decision.action for _, decision in digest.dedup] == ["include", "include"]
    assert client.dedup_calls == 0, "an identical line in another beat is not a neighbour"


# --------------------------------------------------------------------------- #
# The scoring helper itself
# --------------------------------------------------------------------------- #


def test_same_run_neighbours_apply_the_floor_and_sort_by_similarity() -> None:
    embedder = HashingEmbedder()
    prior = [
        ("Rain likely on the morning run window.", {}),
        (AGENTS_TOPIC_LINE, {"topic": "agents"}),
        (CLAUDE_TOPIC_LINE, {"topic": "claude"}),
    ]
    neighbours = same_run_neighbours(
        embedder, CLAUDE_TOPIC_LINE, prior, beat="news", similarity_floor=0.60
    )

    assert [n.rendered_text for n in neighbours] == [CLAUDE_TOPIC_LINE, AGENTS_TOPIC_LINE]
    assert neighbours[0].similarity >= neighbours[1].similarity >= 0.60
    assert all(n.sent_item_id == SAME_RUN_SENT_ITEM_ID for n in neighbours)
    assert same_run_neighbours(embedder, CLAUDE_TOPIC_LINE, [], beat="news") == []

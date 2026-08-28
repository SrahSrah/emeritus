"""Step 49 — FR-40: need-to-know defers, one way, with the cover named.

Every test runs against an empty ledger, so any effect is attributable to the same-run
cross-beat comparison alone. The FR-27 veto must survive intact: a candidate carrying a
figure the covering item lacks is not covered, and reframes through.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from forecaster.agent import AgentResponse
from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.synthesizer import synthesize
from forecaster.trace import SYNTHESIZED, read_trace, records_of
from tests.helpers import make_config, make_preferences, make_retriever, trace_in

CONFIG = make_config()
NOW = datetime(2026, 8, 24, 19, 0, tzinfo=timezone.utc)

NEWS_LINE = "Anthropic and OpenAI are locked in a turf war over agent frameworks."
NTK_RESTATED = "Anthropic is locked in a turf war with OpenAI over agent frameworks."
NTK_NEW_FIGURE = (
    "Anthropic and OpenAI are locked in a turf war over agent frameworks, "
    "with 12 startups caught in the middle."
)
CHUNK = "Anthropic and OpenAI are fighting a turf war over agent frameworks."


class ScriptedClient:
    auth_mode = "subscription_oauth"

    def __init__(self, verdict: str = "SUPPRESS the reader was already told this") -> None:
        self.verdict = verdict
        self.dedup_calls = 0

    def complete(self, prompt, *, structured=None, system=None, effort="low"):
        if structured and "candidate" in structured:
            self.dedup_calls += 1
            return AgentResponse(text=self.verdict, input_tokens=0, output_tokens=0)
        lines = list((structured or {}).get("lines", [])) + list(
            (structured or {}).get("unavailable", [])
        )
        return AgentResponse(text="\n".join(lines), input_tokens=0, output_tokens=0)


def _synthesized_result(trace, beat: str, text: str, chunk: str = CHUNK) -> BeatResult:
    observation_id = trace.tool_call(
        beat=beat, adapter="corpus.retrieve_for_topic", arguments={"q": "t"}
    )
    trace.observation(observation_id, payload=chunk)
    ref = ObservationRef(observation_id, "corpus.retrieve_for_topic")
    return BeatResult(
        beat=beat,
        items=[
            BeatItem(
                beat=beat,
                text=text,
                fields={"text_origin": SYNTHESIZED, "via": "bar"}
                if beat == "need_to_know"
                else {"topic": "claude", "text_origin": SYNTHESIZED},
                observations=[ref],
            )
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
        make_preferences(topics={"news": 1.0, "need_to_know": 1.0}),
        trace,
        agent_client=client,
        retriever=make_retriever(tmp_path),
        now=NOW,
    )
    trace.close()
    return digest, client


def _decisions(trace, kind: str):
    return [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record.get("decision") == kind
    ]


def test_a_restated_story_defers_to_the_news_beat_by_name(tmp_path: Path) -> None:
    trace = trace_in(tmp_path, "defer")
    news = _synthesized_result(trace, "news", NEWS_LINE)
    ntk = _synthesized_result(trace, "need_to_know", NTK_RESTATED)

    digest, client = _synthesize(tmp_path, trace, [news, ntk])

    assert NEWS_LINE in digest.text
    assert NTK_RESTATED not in digest.text
    (deferred,) = _decisions(trace, "ntk_deferred")
    assert deferred["covering_beat"] == "news"
    assert "already covered by the news beat" in deferred["reason"]
    assert _decisions(trace, "dedup_suppress") == [], (
        "the deferral record replaces the plain suppression record"
    )


def test_a_new_figure_is_not_covered_and_reframes_through(tmp_path: Path) -> None:
    """FR-27's veto survives: uncovered facts mean the story is not covered."""
    trace = trace_in(tmp_path, "veto")
    news = _synthesized_result(trace, "news", NEWS_LINE)
    # The figure must be grounded in the item's own chunk, or FR-30 rightly
    # quarantines it — the first draft of this test learned that the hard way.
    ntk = _synthesized_result(
        trace,
        "need_to_know",
        NTK_NEW_FIGURE,
        chunk=CHUNK + " Reports say 12 startups are caught in the middle.",
    )

    digest, client = _synthesize(tmp_path, trace, [news, ntk])

    assert "12" in digest.text, "the new figure must reach the reader"
    assert _decisions(trace, "ntk_deferred") == []
    reframes = _decisions(trace, "dedup_reframe")
    assert any(record["beat"] == "need_to_know" for record in reframes)


def test_with_the_news_beat_absent_the_candidate_delivers(tmp_path: Path) -> None:
    """One-way coupling is optional at runtime: nothing to defer to means deliver."""
    trace = trace_in(tmp_path, "alone")
    ntk = _synthesized_result(trace, "need_to_know", NTK_RESTATED)

    digest, _ = _synthesize(tmp_path, trace, [ntk])

    assert NTK_RESTATED in digest.text
    assert _decisions(trace, "ntk_deferred") == []


def test_deferral_is_one_way(tmp_path: Path) -> None:
    """Processed first, the ntk item must never become the news beat's neighbour."""
    trace = trace_in(tmp_path, "one-way")
    ntk = _synthesized_result(trace, "need_to_know", NTK_RESTATED)
    news = _synthesized_result(trace, "news", NEWS_LINE)

    digest, _ = _synthesize(tmp_path, trace, [ntk, news])

    assert NEWS_LINE in digest.text, "news never defers to need-to-know"
    assert NTK_RESTATED in digest.text, (
        "processed first, the ntk item had nothing to defer to"
    )


def test_a_watchlist_night_is_never_deferred(tmp_path: Path) -> None:
    """Invariant 2 outranks deferral: escalated results skip the judgment entirely."""
    trace = trace_in(tmp_path, "watchlist")
    news = _synthesized_result(trace, "news", NEWS_LINE)
    ntk = _synthesized_result(trace, "need_to_know", NTK_RESTATED)
    ntk.escalation_candidate = True
    ntk.escalation_reason = "watchlist term(s) matched: boil notice"

    digest, client = _synthesize(tmp_path, trace, [news, ntk])

    assert NTK_RESTATED in digest.text
    assert _decisions(trace, "ntk_deferred") == []

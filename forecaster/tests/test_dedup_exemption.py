"""Step 43 — FR-44: exempt beats bypass dedup entirely, and the bypass is accounted.

Sarah's requirement (2026-08-16): venue listings repeat nightly while she decides. The
exemption must therefore cost nothing — no retrieval, no same-run comparison, no model
judgment — and must leave a `dedup_exempt` record so the metric can prove the repeats
were deliberate rather than a dedup outage.

The retriever double here *fails the test by being useful*: any call to it from the
exempt path is the bug.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from forecaster.agent import AgentResponse
from forecaster.beats.base import BeatItem, BeatResult
from forecaster.memory.retrieval import Neighbour
from forecaster.synthesizer import synthesize
from forecaster.trace import read_trace, records_of
from tests.helpers import make_config, make_preferences, trace_in

NOW = datetime(2026, 8, 16, 19, 0, tzinfo=timezone.utc)

#: Numberless and quoteless on purpose — dedup mechanics are the only thing under test.
LISTING_A = 'At ZACH Theatre: "Sally and Tom" — dates on the venue site.'
LISTING_B = 'At ZACH Theatre: "Come From Away" — dates on the venue site.'
FIELDS = {"venue": "ZACH Theatre", "as_of": "2026-08-16"}

EXEMPT = make_config(retrieval={"exempt_beats": ["venues"]})
NOT_EXEMPT = make_config()


class ScriptedClient:
    """Composes the digest like `FakeAgentClient`; answers any dedup prompt SUPPRESS."""

    auth_mode = "subscription_oauth"

    def __init__(self) -> None:
        self.dedup_calls = 0

    def complete(self, prompt: str, *, structured=None, system=None, effort="low"):
        if structured and "candidate" in structured:
            self.dedup_calls += 1
            return AgentResponse(text="SUPPRESS adds nothing", input_tokens=0, output_tokens=0)
        lines = list((structured or {}).get("lines", [])) + list(
            (structured or {}).get("unavailable", [])
        )
        return AgentResponse(text="\n".join(lines), input_tokens=0, output_tokens=0)


class CountingRetriever:
    """Returns a byte-identical, field-identical neighbour — the strongest possible
    suppression candidate — and counts every consultation."""

    def __init__(self) -> None:
        self.neighbour_calls = 0
        self.same_run_calls = 0

    def neighbours_for(self, text: str, *, beat: str, now=None):
        self.neighbour_calls += 1
        return [
            Neighbour(
                sent_item_id=1,
                beat=beat,
                sent_at="2026-08-15T19:00:00",
                rendered_text=text,
                checkable_fields=dict(FIELDS),
                similarity=1.0,
            )
        ]

    def same_run_neighbours(self, text: str, prior, *, beat: str):
        self.same_run_calls += 1
        return []


def _venues_result() -> BeatResult:
    return BeatResult(
        beat="venues",
        items=[
            BeatItem(beat="venues", text=LISTING_A, fields=dict(FIELDS)),
            BeatItem(beat="venues", text=LISTING_B, fields=dict(FIELDS)),
        ],
        checkable_fields={},
    )


def _synthesize(tmp_path: Path, config, results, retriever):
    trace = trace_in(tmp_path, "exemption")
    client = ScriptedClient()
    for result in results:
        trace.beat_result(result)
    digest = synthesize(
        results,
        config,
        make_preferences(topics={"venues": 1.0, "news": 1.0}),
        trace,
        agent_client=client,
        retriever=retriever,
        now=NOW,
    )
    trace.close()
    return digest, client, trace


def test_an_exempt_beat_repeats_verbatim_at_zero_cost(tmp_path: Path) -> None:
    """Identical to last night's ledger row, and it survives untouched — that's the point."""
    retriever = CountingRetriever()
    digest, client, trace = _synthesize(tmp_path, EXEMPT, [_venues_result()], retriever)

    assert LISTING_A in digest.text and LISTING_B in digest.text
    assert retriever.neighbour_calls == 0, "the exempt path may not query the ledger"
    assert retriever.same_run_calls == 0
    assert client.dedup_calls == 0, "the exempt path may not consult the model"

    exempt_records = [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record.get("decision") == "dedup_exempt"
    ]
    assert len(exempt_records) == 2
    for record in exempt_records:
        assert record["beat"] == "venues"
        assert "repeats are deliberate" in record["reason"]
        assert record["forced"] is True


def test_the_same_items_without_the_exemption_are_suppressible(tmp_path: Path) -> None:
    """The contrast case: one config line is the entire difference."""
    retriever = CountingRetriever()
    digest, client, trace = _synthesize(
        tmp_path, NOT_EXEMPT, [_venues_result()], retriever
    )

    assert retriever.neighbour_calls == 2, "normal path: every item consults the ledger"
    assert client.dedup_calls == 2
    assert LISTING_A not in digest.text and LISTING_B not in digest.text
    actions = [decision.action for _, decision in digest.dedup]
    assert actions == ["suppress", "suppress"]


def test_exempt_items_never_join_the_same_run_pool(tmp_path: Path) -> None:
    """Nothing may defer to, or be reframed against, a standing listing (FR-40 relies
    on this staying true when cross-beat deferral arrives)."""
    retriever = CountingRetriever()
    news = BeatResult(
        beat="news",
        items=[BeatItem(beat="news", text="A wire story about theatre funding.",
                        fields={"date": "2026-08-16"})],
        checkable_fields={},
    )
    _synthesize(tmp_path, EXEMPT, [_venues_result(), news], retriever)

    # The news item consults the ledger once; the venue items contributed nothing to
    # any same-run pool, so no same-run comparison ever fires.
    assert retriever.neighbour_calls == 1
    assert retriever.same_run_calls == 0


def test_dedup_off_entirely_still_works_with_an_exempt_beat_configured(tmp_path: Path) -> None:
    """retriever=None is the v1 pipeline; the exemption must not resurrect any pass."""
    digest, client, trace = _synthesize(tmp_path, EXEMPT, [_venues_result()], None)
    assert LISTING_A in digest.text
    assert client.dedup_calls == 0
    assert [r for r in records_of(read_trace(trace.path), "decision")
            if r.get("decision") == "dedup_exempt"] == []

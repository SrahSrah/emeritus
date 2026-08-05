"""FR-30 — an item-level provenance violation costs the item, not the night.

Added 2026-08-05 after a real run failed on one punctuation mark inside one quotation in
one news item, and delivered nothing: no Astros score, no forecast, nothing. FR-18's
position is that going quiet is worse than saying less, and an empty inbox at 7 pm is the
quietest failure there is.

The line this draws: a violation the checker can pin to **one item** quarantines that
item. A violation it cannot — an unsupported checkable field, an altered score, a failed
beat missing from the digest — still fails the run outright, because nothing smaller can
be dropped to fix it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.agent import AgentResponse, FakeAgentClient
from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.synthesizer import ProvenanceError, synthesize
from forecaster.trace import SYNTHESIZED, check_provenance
from tests.helpers import make_config, make_preferences, trace_in

GOOD_CHUNK = 'Anthropic said the model scored 71.5. A spokesperson called it "a real step".'


def _news_result(trace, *texts_and_topics):
    """A news BeatResult whose items each point at one recorded chunk observation."""
    observation_id = trace.tool_call(
        beat="news", adapter="corpus.retrieve_for_topic", arguments={"topic": "t"}
    )
    trace.observation(observation_id, payload=GOOD_CHUNK)
    ref = ObservationRef(observation_id, "corpus.retrieve_for_topic")
    return BeatResult(
        beat="news",
        items=[
            BeatItem(
                beat="news",
                text=text,
                fields={"topic": topic, "text_origin": SYNTHESIZED},
                observations=[ref],
            )
            for text, topic in texts_and_topics
        ],
        checkable_fields={},
        observations=[ref],
    )


def _synthesize(trace, results, client=None):
    """Mirrors the runner: beat results are recorded *before* the digest is composed.

    `synthesize` does not write them itself, and `check_provenance` reads them from the
    trace — so a test that skips this step is checking a run with no items in it.
    """
    for result in results:
        trace.beat_result(result)
    return synthesize(
        results,
        make_config(),
        make_preferences(),
        trace,
        agent_client=client or FakeAgentClient(),
    )


# --------------------------------------------------------------------------- #
# The case that motivated it
# --------------------------------------------------------------------------- #


def test_one_ungrounded_item_is_withheld_and_the_rest_is_delivered(tmp_path: Path) -> None:
    trace = trace_in(tmp_path, "quarantine")
    result = _news_result(
        trace,
        ("Anthropic's model scored 71.5, per the report.", "claude"),
        ('A spokesperson called it "the greatest leap ever seen".', "evals"),
    )

    digest = _synthesize(trace, [result])
    trace.close()

    assert digest.provenance is not None and digest.provenance.ok, digest.provenance.summary()
    assert len(digest.quarantined) == 1
    assert digest.quarantined[0][0] == "news"
    assert "71.5" in digest.text, "the grounded item still reaches the reader"
    assert "greatest leap" not in digest.text, "the ungrounded one does not"


def test_the_withheld_item_is_named_in_the_digest(tmp_path: Path) -> None:
    """Silently dropping it would be the quiet failure FR-18 forbids."""
    trace = trace_in(tmp_path, "quarantine-named")
    result = _news_result(
        trace,
        ("Anthropic's model scored 71.5.", "claude"),
        ("The model scored 99.9 on a benchmark.", "evals"),
    )

    digest = _synthesize(trace, [result])
    trace.close()

    assert "withheld" in digest.text.lower()
    assert "news" in digest.text.lower()


def test_the_quarantine_and_its_reason_are_in_the_trace(tmp_path: Path) -> None:
    from forecaster.trace import read_trace, records_of

    trace = trace_in(tmp_path, "quarantine-traced")
    result = _news_result(trace, ("The model scored 99.9 on a benchmark.", "evals"))
    _synthesize(trace, [result])
    trace.close()

    decisions = [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record["decision"] == "item_quarantined"
    ]
    assert len(decisions) == 1
    assert "99.9" in decisions[0]["reason"]
    assert decisions[0]["item_text"] == "The model scored 99.9 on a benchmark."


def test_a_recheck_is_recorded_so_the_second_verdict_is_auditable(tmp_path: Path) -> None:
    from forecaster.trace import read_trace, records_of

    trace = trace_in(tmp_path, "quarantine-recheck")
    result = _news_result(trace, ("The model scored 99.9.", "evals"))
    _synthesize(trace, [result])
    trace.close()

    kinds = [r["decision"] for r in records_of(read_trace(trace.path), "decision")]
    assert "provenance_checked" in kinds
    assert "provenance_rechecked" in kinds


# --------------------------------------------------------------------------- #
# The line: what may NOT be quarantined
# --------------------------------------------------------------------------- #


def test_an_unsupported_checkable_field_still_fails_the_whole_run(tmp_path: Path) -> None:
    """Nothing smaller can be dropped to fix a beat that claims what it never observed."""
    trace = trace_in(tmp_path, "fatal-unsupported")
    observation_id = trace.tool_call(beat="astros", adapter="mlb", arguments={})
    trace.observation(observation_id, payload={"score": "1-0"})
    result = BeatResult(
        beat="astros",
        items=[BeatItem(beat="astros", text="Final: 9-9.", fields={"game_date": "2026-08-04"})],
        checkable_fields={"final_score": "Houston 9, Toronto 9"},
        observations=[ObservationRef(observation_id, "mlb")],
    )

    with pytest.raises(ProvenanceError):
        _synthesize(trace, [result])
    trace.close()


def test_every_item_being_ungrounded_still_names_each_withholding(tmp_path: Path) -> None:
    """All the content can go, but the reader is told, every time."""
    trace = trace_in(tmp_path, "all-bad")
    result = _news_result(
        trace,
        ("The model scored 99.9.", "claude"),
        ('It was called "an unprecedented triumph".', "evals"),
    )

    digest = _synthesize(trace, [result])
    trace.close()

    assert len(digest.quarantined) == 2
    assert digest.provenance is not None and digest.provenance.ok
    assert digest.text.lower().count("withheld") >= 2


def test_quarantine_never_loops(tmp_path: Path) -> None:
    """Exactly one retry. A loop that dropped items until something passed would be a
    machine for producing an empty, confident digest."""

    class AlwaysFabricates:
        auth_mode = "subscription_oauth"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, prompt, *, structured=None, system=None, effort="low"):
            self.calls += 1
            return AgentResponse(text="Everything scored 42.0 tonight.")

    trace = trace_in(tmp_path, "no-loop")
    result = _news_result(trace, ("The model scored 99.9.", "claude"))
    client = AlwaysFabricates()

    _synthesize(trace, [result], client=client)
    trace.close()

    assert client.calls == 2, "one composition, one recomposition, and no more"


# --------------------------------------------------------------------------- #
# The exclusion is explicit, not inferred
# --------------------------------------------------------------------------- #


def test_an_excluded_item_is_not_policed_but_is_noted(tmp_path: Path) -> None:
    """The reader was never shown it, so its prose states nothing to them."""
    trace = trace_in(tmp_path, "excluded")
    result = _news_result(trace, ("The model scored 99.9.", "claude"))
    trace.beat_result(result)
    trace.digest("Nothing to report.", order=["news"])
    trace.close()

    unfiltered = check_provenance(trace.path)
    assert not unfiltered.ok

    filtered = check_provenance(trace.path, excluded_items=["The model scored 99.9."])
    assert filtered.ok
    assert any("withheld from the digest" in note for note in filtered.notes)


def test_the_two_shipped_beats_are_untouched_by_fr30(tmp_path: Path) -> None:
    """No structured beat declares text_origin, so nothing here can quarantine one."""
    trace = trace_in(tmp_path, "structured")
    observation_id = trace.tool_call(beat="weather", adapter="nws", arguments={})
    trace.observation(observation_id, payload={"low": 41})
    result = BeatResult(
        beat="weather",
        items=[
            BeatItem(
                beat="weather",
                text="Run window: 41F.",
                fields={"morning": "2026-08-05"},
                observations=[ObservationRef(observation_id, "nws")],
            )
        ],
        checkable_fields={"run_window_low_f": 41},
        observations=[ObservationRef(observation_id, "nws")],
    )

    digest = _synthesize(trace, [result])
    trace.close()

    assert digest.quarantined == []
    assert digest.provenance is not None and digest.provenance.ok


def test_the_withholding_notice_never_repeats_the_ungrounded_words(tmp_path: Path) -> None:
    """The notice may not put the unverifiable phrase in front of the reader anyway.

    Caught by a test that expected the offending text to be gone and found it echoed
    inside the very line that withheld it. The full detail belongs in the trace.
    """
    from forecaster.trace import read_trace, records_of

    trace = trace_in(tmp_path, "no-echo")
    result = _news_result(
        trace, ('It was called "the greatest leap ever seen".', "evals")
    )

    digest = _synthesize(trace, [result])
    trace.close()

    assert "greatest leap" not in digest.text
    assert "quoted phrase" in digest.text

    # ...but a human debugging it still gets the specifics.
    quarantines = [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record["decision"] == "item_quarantined"
    ]
    assert "greatest leap" in quarantines[0]["reason"]

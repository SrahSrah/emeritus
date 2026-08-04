"""Step 30 — FR-26: a number the model invented into a sentence fails the run.

Built before the beat it guards, following the parent build's pattern of landing the
check before the thing it checks. No beat is needed: these traces are hand-built, which
is also the point — the checker takes a trace file and nothing else.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.trace import Trace, check_provenance

CHUNK = (
    "Anthropic ships a new Claude model\n"
    "Anthropic said the model scored 71.5 on the benchmark, up from 64. "
    'A spokesperson called it "a meaningful step for agentic work" in a statement.'
)


def _trace_with_item(
    tmp_path: Path,
    *,
    item_text: str,
    fields: dict,
    link_observation: bool = True,
    payload: str = CHUNK,
) -> Path:
    """A minimal trace: one chunk observation, one item, one digest."""
    trace = Trace("grounded", directory=tmp_path)
    trace.run_start(auth_mode="subscription_oauth", config_digest="test")

    observation_id = trace.tool_call(
        beat="news", adapter="corpus.retrieve_for_topic", arguments={"topic": "claude"}
    )
    trace.observation(observation_id, payload=payload)

    trace._write(  # noqa: SLF001 - hand-building the record the beat would emit
        "beat_result",
        beat="news",
        items=[
            {
                "beat": "news",
                "text": item_text,
                "fields": fields,
                "observations": [observation_id] if link_observation else [],
            }
        ],
        checkable_fields={},
        available=True,
        error=None,
        escalation_candidate=False,
        escalation_reason=None,
        escalation_signals={},
        observations=[],
    )
    trace.digest(item_text, order=["news"])
    trace.close()
    return trace.path


SYNTH = {"topic": "claude", "text_origin": "synthesized"}


# --------------------------------------------------------------------------- #
# The failure the check exists for
# --------------------------------------------------------------------------- #


def test_a_number_absent_from_every_passage_fails_the_run(tmp_path: Path) -> None:
    """The fabricated-figure case, which FR-11's existing checks cannot see."""
    path = _trace_with_item(
        tmp_path,
        item_text="Anthropic's new model scored 93.2 on the benchmark.",
        fields=SYNTH,
    )

    report = check_provenance(path)

    assert not report.ok
    kinds = [violation.kind for violation in report.violations]
    assert kinds == ["ungrounded_number"]
    assert "93.2" in report.violations[0].detail


def test_a_quote_absent_from_every_passage_fails_the_run(tmp_path: Path) -> None:
    path = _trace_with_item(
        tmp_path,
        item_text='Anthropic called it "the biggest leap in years" today.',
        fields=SYNTH,
    )

    report = check_provenance(path)

    assert not report.ok
    assert [v.kind for v in report.violations] == ["ungrounded_quote"]


def test_a_synthesized_item_grounded_in_its_passages_passes(tmp_path: Path) -> None:
    path = _trace_with_item(
        tmp_path,
        item_text=(
            'Anthropic\'s new model scored 71.5, up from 64, and was called '
            '"a meaningful step for agentic work".'
        ),
        fields=SYNTH,
    )

    report = check_provenance(path)

    assert report.ok, report.summary()


def test_a_synthesized_item_with_no_linked_observation_fails(tmp_path: Path) -> None:
    """Nothing it says can be traced, which is the whole claim the flag makes."""
    path = _trace_with_item(
        tmp_path,
        item_text="Something happened in AI today.",
        fields=SYNTH,
        link_observation=False,
    )

    report = check_provenance(path)

    assert not report.ok
    assert [v.kind for v in report.violations] == ["ungrounded_item"]


# --------------------------------------------------------------------------- #
# The word-form allowance, and its limit
# --------------------------------------------------------------------------- #


def test_a_word_form_of_a_number_in_the_passage_grounds_the_digit(tmp_path: Path) -> None:
    """A model handed "three papers" may write "3 papers"."""
    path = _trace_with_item(
        tmp_path,
        item_text="The lab published 3 papers.",
        fields=SYNTH,
        payload="The lab published three papers this week.",
    )

    assert check_provenance(path).ok


def test_the_word_form_allowance_does_not_ground_a_different_number(tmp_path: Path) -> None:
    """"three" in the passage must not excuse "4" in the summary."""
    path = _trace_with_item(
        tmp_path,
        item_text="The lab published 4 papers.",
        fields=SYNTH,
        payload="The lab published three papers this week.",
    )

    report = check_provenance(path)

    assert not report.ok
    assert [v.kind for v in report.violations] == ["ungrounded_number"]


def test_the_word_form_allowance_stops_at_twenty(tmp_path: Path) -> None:
    """A closed mapping, not an English number parser."""
    path = _trace_with_item(
        tmp_path,
        item_text="The lab published 30 papers.",
        fields=SYNTH,
        payload="The lab published thirty papers this week.",
    )

    assert not check_provenance(path).ok


def test_a_decimal_written_differently_still_grounds(tmp_path: Path) -> None:
    """"64" against a passage saying "64.0" is the same observation."""
    path = _trace_with_item(
        tmp_path,
        item_text="It scored 64.",
        fields=SYNTH,
        payload="It scored 64.0 on the benchmark.",
    )

    assert check_provenance(path).ok


# --------------------------------------------------------------------------- #
# Scoping — the existing beats must not notice this exists
# --------------------------------------------------------------------------- #


def test_an_unflagged_item_with_an_unsupported_number_produces_no_new_violation(
    tmp_path: Path,
) -> None:
    """Proves the case is scoped to the flag, not applied to every item."""
    path = _trace_with_item(
        tmp_path,
        item_text="Anthropic's new model scored 93.2 on the benchmark.",
        fields={"topic": "claude"},  # no text_origin
    )

    report = check_provenance(path)

    assert report.ok, report.summary()


def test_a_short_quoted_span_is_punctuation_not_a_quotation(tmp_path: Path) -> None:
    """Under four characters, a pair of quotes is scare-quoting, not a citation."""
    path = _trace_with_item(
        tmp_path,
        item_text='The model is "up" this week.',
        fields=SYNTH,
    )

    assert check_provenance(path).ok


def test_an_item_carrying_no_fields_at_all_is_untouched(tmp_path: Path) -> None:
    """The shape every pre-FR-26 beat item has when it declares nothing."""
    path = _trace_with_item(
        tmp_path,
        item_text="Final: Houston Astros 4, Texas Rangers 2.",
        fields={},
        link_observation=False,
    )

    assert check_provenance(path).ok

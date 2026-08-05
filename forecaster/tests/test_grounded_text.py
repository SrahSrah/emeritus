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


# --------------------------------------------------------------------------- #
# Typography: a curly apostrophe is not a fabrication (found live 2026-08-04)
# --------------------------------------------------------------------------- #
#
# The news beat's first real run failed on:
#
#   [ungrounded_quote] news.text: item text quotes "didn't publish a safety framework,
#   pre-deployment testing commitments, or risk assessment", which appears verbatim in
#   none of the passages it was grounded in
#
# It did appear. The passage read `Z.ai didn\u2019t publish ...` with a curly apostrophe;
# the model quoted it back with an ASCII one. Every word matched, in order. Folding a
# publisher's typography to ASCII is what quoting correctly looks like.

CURLY_PASSAGE = (
    "In GLM-5.2\u2019s case, SaferAI says Z.ai didn\u2019t publish a safety framework, "
    "pre-deployment testing commitments, or risk assessment for the model."
)


def test_a_quote_that_differs_only_in_apostrophe_style_is_grounded(tmp_path: Path) -> None:
    """The live regression, verbatim from the run that failed."""
    path = _trace_with_item(
        tmp_path,
        item_text=(
            'SaferAI found Z.ai "didn\'t publish a safety framework, pre-deployment '
            'testing commitments, or risk assessment" for GLM-5.2.'
        ),
        fields=SYNTH,
        payload=CURLY_PASSAGE,
    )

    report = check_provenance(path)

    assert report.ok, report.summary()


def test_curly_double_quotes_around_the_span_are_also_found(tmp_path: Path) -> None:
    """Without normalizing the item text, the quote pattern would not even match."""
    path = _trace_with_item(
        tmp_path,
        item_text="SaferAI said \u201cdidn\u2019t publish a safety framework\u201d today.",
        fields=SYNTH,
        payload=CURLY_PASSAGE,
    )

    assert check_provenance(path).ok


def test_en_and_em_dashes_and_nbsp_fold_too(tmp_path: Path) -> None:
    path = _trace_with_item(
        tmp_path,
        item_text='The report says "2024-2026 was the gap" here.',
        fields=SYNTH,
        payload="The report says 2024\u20132026\u00a0was the gap, roughly.",
    )

    assert check_provenance(path).ok


def test_normalizing_punctuation_does_not_let_a_changed_word_through(
    tmp_path: Path,
) -> None:
    """The fix may not buy its relief by going blind. Words are still verbatim."""
    path = _trace_with_item(
        tmp_path,
        item_text=(
            'SaferAI found Z.ai "did publish a safety framework, pre-deployment '
            'testing commitments, or risk assessment" for GLM-5.2.'
        ),
        fields=SYNTH,
        payload=CURLY_PASSAGE,
    )

    report = check_provenance(path)

    assert not report.ok
    assert [v.kind for v in report.violations] == ["ungrounded_quote"]


def test_a_wholly_invented_quotation_is_still_caught(tmp_path: Path) -> None:
    path = _trace_with_item(
        tmp_path,
        item_text='SaferAI called it "the most reckless launch of the year".',
        fields=SYNTH,
        payload=CURLY_PASSAGE,
    )

    assert not check_provenance(path).ok


def test_the_normalizer_touches_punctuation_and_whitespace_only() -> None:
    """Stated as a test so a later edit cannot quietly widen it to words."""
    from forecaster.trace import normalize_typography

    assert normalize_typography("didn\u2019t") == "didn't"
    assert normalize_typography("\u201cquoted\u201d") == '"quoted"'
    assert normalize_typography("a\u2014b") == "a-b"
    assert normalize_typography("a\u00a0 \n b") == "a b"
    assert normalize_typography("\u2026") == "..."
    # Letters, digits, and word order are untouched.
    assert normalize_typography("Z.ai 71.5 GLM-5.2") == "Z.ai 71.5 GLM-5.2"

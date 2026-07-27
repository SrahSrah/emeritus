"""Step 13 — deterministic ordering, asserted on the ordered structure, not on prose."""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.beats.base import BeatItem, BeatResult
from forecaster.escalation import (
    FREEZE_ALERT,
    WATCHED_PLAYER_INJURY,
    OrderedItems,
    apply_escalation,
    escalation_summary,
)
from forecaster.trace import read_trace, records_of
from tests.helpers import make_config, trace_in

CONFIG = make_config()


def _astros(**kwargs) -> BeatResult:
    return BeatResult(
        beat="astros",
        items=[BeatItem(beat="astros", text="Final: Astros 3, White Sox 12.")],
        **kwargs,
    )


def _weather(freezing: bool = False, **kwargs) -> BeatResult:
    return BeatResult(
        beat="weather",
        items=[BeatItem(beat="weather", text="Run window 28-31F.")],
        escalation_candidate=freezing,
        escalation_reason=("run-window low 28F is at or below 32.0F" if freezing else None),
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# FR-10's acceptance criterion
# --------------------------------------------------------------------------- #


def test_one_candidate_becomes_the_first_item_in_the_ordered_structure() -> None:
    ordered = apply_escalation([_astros(), _weather(freezing=True)], CONFIG)

    assert isinstance(ordered, OrderedItems)
    assert ordered.beat_order[0] == "weather"
    assert ordered.items[0].promoted is True
    assert ordered.items[0].rule == FREEZE_ALERT
    assert "28" in (ordered.items[0].reason or "")
    assert ordered.beat_order == ["weather", "astros"]


def test_no_candidate_preserves_the_base_order() -> None:
    ordered = apply_escalation([_astros(), _weather(freezing=False)], CONFIG)

    assert ordered.beat_order == ["astros", "weather"]
    assert ordered.promoted == []
    assert all(not entry.promoted for entry in ordered.items)


def test_nothing_is_dropped_when_something_is_promoted() -> None:
    ordered = apply_escalation([_astros(), _weather(freezing=True)], CONFIG)
    assert len(ordered.items) == 2


# --------------------------------------------------------------------------- #
# The dormant injury rule
# --------------------------------------------------------------------------- #


def test_a_synthetic_injury_signal_naming_a_watched_player_promotes() -> None:
    """The rule is correct; nothing in v1 populates the signal it reads."""
    injured = _astros(escalation_signals={"injuries": ["Yordan Alvarez (hamstring)"]})

    ordered = apply_escalation([injured, _weather()], CONFIG)

    assert ordered.beat_order[0] == "astros"
    assert ordered.items[0].rule == WATCHED_PLAYER_INJURY
    assert "Yordan Alvarez" in (ordered.items[0].reason or "")


def test_an_injury_to_an_unwatched_player_does_not_promote() -> None:
    injured = _astros(escalation_signals={"injuries": [{"player": "Some Reliever"}]})

    ordered = apply_escalation([injured, _weather()], CONFIG)

    assert ordered.promoted == []
    reasons = [o.reason for o in ordered.outcomes if o.rule == WATCHED_PLAYER_INJURY]
    assert any("none to a configured watched player" in reason for reason in reasons)


def test_the_rule_reports_itself_as_dormant_when_no_signal_exists() -> None:
    ordered = apply_escalation([_astros(), _weather()], CONFIG)

    reasons = [o.reason for o in ordered.outcomes if o.rule == WATCHED_PLAYER_INJURY]
    assert reasons
    assert all("dormant" in reason for reason in reasons)


# --------------------------------------------------------------------------- #
# Determinism
# --------------------------------------------------------------------------- #


def test_two_candidates_are_ordered_by_the_config_rule_priority() -> None:
    injured = _astros(escalation_signals={"injuries": ["Yordan Alvarez"]})
    freezing = _weather(freezing=True)

    freeze_first = make_config(
        escalation={
            "rules": [FREEZE_ALERT, WATCHED_PLAYER_INJURY],
            "freeze_threshold_f": 32.0,
            "freeze_horizon_days": 1,
            "watched_players": ["Yordan Alvarez"],
        }
    )
    injury_first = make_config(
        escalation={
            "rules": [WATCHED_PLAYER_INJURY, FREEZE_ALERT],
            "freeze_threshold_f": 32.0,
            "freeze_horizon_days": 1,
            "watched_players": ["Yordan Alvarez"],
        }
    )

    assert apply_escalation([injured, freezing], freeze_first).beat_order == [
        "weather",
        "astros",
    ]
    assert apply_escalation([injured, freezing], injury_first).beat_order == [
        "astros",
        "weather",
    ]


def test_the_same_inputs_always_produce_the_same_output() -> None:
    results = [_astros(), _weather(freezing=True)]
    first = apply_escalation(results, CONFIG)
    second = apply_escalation(results, CONFIG)

    assert first.beat_order == second.beat_order
    assert [o.reason for o in first.outcomes] == [o.reason for o in second.outcomes]


def test_an_unknown_rule_in_config_is_an_error_not_a_silent_skip() -> None:
    bad = make_config(
        escalation={
            "rules": ["vibes"],
            "freeze_threshold_f": 32.0,
            "freeze_horizon_days": 1,
            "watched_players": [],
        }
    )
    with pytest.raises(LookupError, match="unknown rule"):
        apply_escalation([_astros()], bad)


def test_an_unavailable_beat_cannot_be_promoted_and_is_tracked() -> None:
    failed = BeatResult.unavailable("weather", "api.weather.gov returned 500")

    ordered = apply_escalation([_astros(), failed], CONFIG)

    assert ordered.unavailable == [failed]
    assert ordered.promoted == []
    freeze = [o for o in ordered.outcomes if o.rule == FREEZE_ALERT and o.beat == "weather"]
    assert freeze and not freeze[0].fired
    assert "unavailable" in freeze[0].reason


# --------------------------------------------------------------------------- #
# Every evaluation is observable
# --------------------------------------------------------------------------- #


def test_every_rule_evaluation_lands_in_the_trace_fired_or_not(tmp_path: Path) -> None:
    """PRD §8: 'escalating everything is the same as escalating nothing' — watchable."""
    trace = trace_in(tmp_path, "escalation-run")
    with trace:
        apply_escalation([_astros(), _weather(freezing=True)], CONFIG, trace=trace)

    records = list(records_of(read_trace(trace.path), "escalation"))

    # two beats x two configured rules
    assert len(records) == 4
    assert all(record["reason"] for record in records)
    fired = [record for record in records if record["fired"]]
    assert len(fired) == 1
    assert fired[0]["rule"] == FREEZE_ALERT
    assert fired[0]["beat"] == "weather"


def test_escalation_summary_is_compact_and_truthful() -> None:
    ordered = apply_escalation([_astros(), _weather(freezing=True)], CONFIG)
    summary = escalation_summary(ordered)

    assert summary["evaluations"] == 4
    assert summary["fired"] == 1
    assert summary["promoted"][0]["beat"] == "weather"


def test_no_model_call_is_possible_from_this_module() -> None:
    """FR-10 is deterministic rules only; §9 Q2 is open and stays open."""
    source = (
        Path(__file__).resolve().parent.parent / "forecaster" / "escalation.py"
    ).read_text(encoding="utf-8")
    offenders = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "agent" in line
    ]
    assert offenders == []

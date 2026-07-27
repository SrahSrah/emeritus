"""Step 11 — three fixtures, three branches, asserted on `BeatResult`, not on prose."""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.beats.astros import AstrosBeat
from forecaster.memory.scratchpad import Scratchpad
from forecaster.trace import read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import SCHEDULE_URL, make_config, make_context, trace_in


def _run(tmp_path: Path, routes, **context_kwargs):
    """Run the beat against a set of mock routes; return (result, trace, recorder)."""
    client, recorder = fixture_client(routes)
    trace = trace_in(tmp_path)
    with client, trace:
        context = make_context(trace=trace, http_client=client, **context_kwargs)
        result = AstrosBeat().run(context)
    return result, trace, recorder, context


# --------------------------------------------------------------------------- #
# FR-5's three branches
# --------------------------------------------------------------------------- #


def test_final_fixture_reports_the_final_and_previews_the_next_game(tmp_path: Path) -> None:
    result, trace, recorder, _ = _run(
        tmp_path,
        [
            # first call: today, a completed game; second: the look-ahead range
            Route(r"date=2026-07-27", fixture="mlb_final"),
            Route(r"startDate=", fixture="mlb_doubleheader"),
        ],
    )

    assert result.available is True
    assert result.checkable_fields["final_score"] == "Houston Astros 3, Chicago White Sox 12"
    assert result.checkable_fields["game_state"] == "Final"
    assert result.checkable_fields["opponent"] == "Chicago White Sox"
    assert len(recorder.requests) == 2, "the final branch needs a second call to preview"

    decisions = [r["decision"] for r in records_of(read_trace(trace.path), "decision")]
    assert "report_final" in decisions


def test_in_progress_fixture_flags_tonight_live_and_reports_the_last_completed(
    tmp_path: Path,
) -> None:
    result, trace, recorder, _ = _run(
        tmp_path,
        [
            Route(r"date=2026-07-27", fixture="mlb_in_progress"),
            Route(r"startDate=", fixture="mlb_final"),  # look-back range
        ],
    )

    assert result.available is True
    assert result.checkable_fields["live_score"] == "Houston Astros 2, Chicago White Sox 1"
    assert result.checkable_fields["live_game_state"] == "In Progress"
    assert (
        result.checkable_fields["last_completed_score"]
        == "Houston Astros 3, Chicago White Sox 12"
    )
    assert result.checkable_fields["last_completed_state"] == "Final"
    assert len(recorder.requests) == 2

    decisions = [r["decision"] for r in records_of(read_trace(trace.path), "decision")]
    assert "tonight_in_progress" in decisions
    assert "enough_information" in decisions


def test_no_game_fixture_takes_the_brief_branch_and_is_not_an_error(
    tmp_path: Path,
) -> None:
    result, trace, recorder, _ = _run(
        tmp_path, [Route(SCHEDULE_URL, fixture="mlb_no_game")]
    )

    assert result.available is True, "an off day is information, not a failure"
    assert result.error is None
    assert result.items, "the no-game branch must still say something"
    assert result.checkable_fields == {"game_count": 0}
    assert len(recorder.requests) == 1, "no second call is warranted with no game"

    decisions = [r["decision"] for r in records_of(read_trace(trace.path), "decision")]
    assert "no_game" in decisions


def test_offseason_degrades_to_no_games_rather_than_erroring(tmp_path: Path) -> None:
    """PRD §8: November to March must not look like an outage."""
    from datetime import datetime

    result, _, _, _ = _run(
        tmp_path,
        [Route(SCHEDULE_URL, fixture="mlb_no_game")],
        now=datetime(2026, 12, 15, 19, 0),
    )

    assert result.available is True
    assert result.error is None


def test_a_preview_only_day_reports_tonight_as_not_started(tmp_path: Path) -> None:
    result, trace, recorder, _ = _run(
        tmp_path, [Route(SCHEDULE_URL, fixture="mlb_preview")]
    )

    assert result.available is True
    assert result.checkable_fields["game_state"] == "Preview"
    assert len(recorder.requests) == 1

    decisions = [r["decision"] for r in records_of(read_trace(trace.path), "decision")]
    assert "tonight_not_started" in decisions


# --------------------------------------------------------------------------- #
# Seam, scratchpad, and the deliberately dormant injury signal
# --------------------------------------------------------------------------- #


def test_a_repeated_identical_call_within_one_run_hits_the_adapter_once(
    tmp_path: Path,
) -> None:
    client, recorder = fixture_client([Route(SCHEDULE_URL, fixture="mlb_no_game")])
    trace = trace_in(tmp_path)
    scratchpad = Scratchpad(trace=trace)
    beat = AstrosBeat()

    with client, trace:
        context = make_context(trace=trace, http_client=client, scratchpad=scratchpad)
        beat.run(context)
        beat.run(context)  # identical call signature, same run

    assert len(recorder.requests) == 1
    assert scratchpad.call_count == 1
    assert scratchpad.hit_count == 1


def test_injury_signal_is_left_unpopulated_because_v1_has_no_source(
    tmp_path: Path,
) -> None:
    """FR-10's injury rule is dormant by design — no feed, no guessing."""
    result, _, _, _ = _run(tmp_path, [Route(SCHEDULE_URL, fixture="mlb_no_game")])

    assert "injuries" not in result.escalation_signals
    assert result.escalation_signals == {}


def test_every_checkable_value_points_at_a_recorded_observation(tmp_path: Path) -> None:
    result, trace, _, _ = _run(
        tmp_path,
        [
            Route(r"date=2026-07-27", fixture="mlb_final"),
            Route(r"startDate=", fixture="mlb_doubleheader"),
        ],
    )

    recorded = {
        record["observation_id"]
        for record in records_of(read_trace(trace.path), "observation")
    }
    cited = {ref.observation_id for ref in result.observations}

    assert result.checkable_fields
    assert cited
    assert cited <= recorded


def test_the_beat_does_not_import_the_planner_synthesizer_or_delivery() -> None:
    source = (
        Path(__file__).resolve().parent.parent / "forecaster" / "beats" / "astros.py"
    ).read_text(encoding="utf-8")
    offenders = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
        and any(bad in line for bad in ("planner", "synthesizer", "delivery"))
    ]
    assert offenders == []


def test_an_adapter_error_propagates_and_is_recorded_as_an_observation_error(
    tmp_path: Path,
) -> None:
    """Step 15 wraps this into an unavailable result; the beat's job is to not hide it."""
    from forecaster.tools.mlb import AdapterError

    client, _ = fixture_client(
        [Route(SCHEDULE_URL, json_body={"detail": "boom"}, status=500)]
    )
    trace = trace_in(tmp_path)
    with client, trace:
        context = make_context(trace=trace, http_client=client)
        with pytest.raises(AdapterError):
            AstrosBeat().run(context)

    errors = [
        record
        for record in records_of(read_trace(trace.path), "observation")
        if record.get("error")
    ]
    assert errors, "a failed call must leave its error in the trace"
    assert "500" in errors[0]["error"]


def test_should_run_follows_config(tmp_path: Path) -> None:
    trace = trace_in(tmp_path)
    with trace:
        on = make_context(trace=trace, http_client=None, config=make_config())
        off = make_context(
            trace=trace,
            http_client=None,
            config=make_config(beats={"astros": False, "weather": True}),
        )
    assert AstrosBeat().should_run(on) is True
    assert AstrosBeat().should_run(off) is False

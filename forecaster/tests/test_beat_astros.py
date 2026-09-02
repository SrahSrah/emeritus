"""Step 11 — three fixtures, three branches, asserted on `BeatResult`, not on prose."""

from __future__ import annotations

from datetime import datetime
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
    assert result.checkable_fields == {}, (
        "an off day states no number, so it declares nothing checkable — a cardinality "
        "claim about an empty observation is not a value FR-11 can support"
    )
    assert result.items[0].fields["game_count"] == 0, "FR-19 still needs it in fields"
    assert len(recorder.requests) == 2, (
        "since 2026-08-31 an off day makes the look-back call too; here the window is "
        "also empty, so nothing further is claimed"
    )

    decisions = [r["decision"] for r in records_of(read_trace(trace.path), "decision")]
    assert "no_game" in decisions


def test_an_off_day_still_reports_the_last_completed_game(tmp_path: Path) -> None:
    """The 2026-08-31 amendment: 'no game today' now travels with yesterday's score."""
    result, _, recorder, _ = _run(
        tmp_path,
        [
            Route(r"[?&]date=", fixture="mlb_no_game"),
            Route(r"startDate=", fixture="mlb_final"),
        ],
    )

    assert result.available is True
    assert len(recorder.requests) == 2
    assert "last_completed_score" in result.checkable_fields
    assert result.checkable_fields["last_completed_state"] == "Final"
    assert any(item.text.startswith("Last completed:") for item in result.items)
    last_item = next(i for i in result.items if i.text.startswith("Last completed:"))
    assert "game_date" in last_item.fields, "FR-19: the score is about a particular day"


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
        tmp_path,
        [
            Route(r"[?&]date=", fixture="mlb_preview"),
            Route(r"startDate=", fixture="mlb_final"),  # look-back range
        ],
    )

    assert result.available is True
    assert result.checkable_fields["game_state"] == "Preview"
    assert len(recorder.requests) == 2, (
        "since 2026-08-31 the preview branch also reports the last completed game"
    )
    assert "last_completed_score" in result.checkable_fields
    assert any(item.text.startswith("Last completed:") for item in result.items)

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
        beat.run(context)  # identical call signatures, same run

    # Each run makes two distinct calls (today + look-back, since 2026-08-31); the
    # second run repeats both signatures and must be served from the scratchpad.
    assert len(recorder.requests) == 2
    assert scratchpad.call_count == 2
    assert scratchpad.hit_count == 2


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


# --------------------------------------------------------------------------- #
# A real series: two true scores that share a sentence shape (live 2026-08-04)
# --------------------------------------------------------------------------- #
#
# The first live run to hit a series failed the provenance check on two mirrored
# `altered_claim` violations. Both scores were true and observation-backed — 0-0 tonight
# in Warmup, 3-1 last night Final, same two teams. A numbers-are-wildcards fidelity
# template built from either matched the other's sentence.
#
# The whole fixture set missed it because every prior MLB fixture descends from ONE
# captured game: `mlb_in_progress.json` is a hand-edited copy of `mlb_final.json`. Only
# the live endpoint produces two same-opponent games with different states and different
# scores, so these two payloads are recorded verbatim rather than derived.
#
# This test drives the real beat through the real two-call sequence the beat actually
# makes, then runs the real provenance check over the trace it produced. Nothing here is
# synthetic except the clock.

SERIES_ROUTES = [
    Route(r"[?&]date=2026-08-04", fixture="mlb_series_today"),
    Route(r"startDate=", fixture="mlb_series_lookback"),
]
SERIES_NOW = datetime(2026, 8, 4, 19, 0)


def test_a_live_game_and_a_final_against_the_same_opponent_both_survive(
    tmp_path: Path,
) -> None:
    """The beat's half: two items, two distinct dates, both scores intact."""
    result, _, _, _ = _run(tmp_path, SERIES_ROUTES, now=SERIES_NOW)

    assert result.available is True
    assert result.checkable_fields["live_score"] == "Toronto Blue Jays 0, Houston Astros 0"
    assert (
        result.checkable_fields["last_completed_score"]
        == "Toronto Blue Jays 3, Houston Astros 1"
    )

    dates = [item.fields.get("game_date") for item in result.items]
    assert dates == ["2026-08-04", "2026-08-03"], (
        "the two items must be pinned to different days — FR-19's invariant needs it, "
        "and it is what tells a reader which game is which"
    )


def test_the_real_series_digest_passes_the_provenance_check(tmp_path: Path) -> None:
    """The regression. This exact shape failed live on 2026-08-04.

    Asserted through `check_provenance` over a real trace rather than on the report's
    internals, because the thing that broke was the check, not the beat.
    """
    from forecaster.trace import check_provenance

    client, _ = fixture_client(SERIES_ROUTES)
    trace = trace_in(tmp_path, "series-live")
    with client:
        context = make_context(trace=trace, http_client=client, now=SERIES_NOW)
        result = AstrosBeat().run(context)
        trace.beat_result(result)
    digest = "\n".join(item.text for item in result.items)
    trace.digest(digest, order=["astros"])
    trace.close()

    report = check_provenance(trace.path)

    assert report.ok, report.summary()
    assert "Toronto Blue Jays 0, Houston Astros 0" in digest
    assert "Toronto Blue Jays 3, Houston Astros 1" in digest


def test_altering_one_score_of_the_pair_still_fails(tmp_path: Path) -> None:
    """The catch must survive the fix, on the very payloads that exposed the false alarm."""
    from forecaster.trace import check_provenance

    client, _ = fixture_client(SERIES_ROUTES)
    trace = trace_in(tmp_path, "series-tampered")
    with client:
        context = make_context(trace=trace, http_client=client, now=SERIES_NOW)
        result = AstrosBeat().run(context)
        trace.beat_result(result)
    tampered = "\n".join(item.text for item in result.items).replace(
        "Toronto Blue Jays 3, Houston Astros 1",
        "Toronto Blue Jays 5, Houston Astros 1",
    )
    trace.digest(tampered, order=["astros"])
    trace.close()

    report = check_provenance(trace.path)

    assert not report.ok
    assert {v.kind for v in report.violations} == {"altered_claim"}
    assert all("5, Houston Astros 1" in v.detail for v in report.violations)


def test_an_off_day_survives_the_provenance_check(tmp_path: Path) -> None:
    """The gap that let this ship: the no-game branch was never provenance-checked.

    `test_no_game_fixture_takes_the_brief_branch_and_is_not_an_error` asserts on the
    `BeatResult` and stops there, so `check_provenance` never ran over this path — in
    tests or in the wild — until the first real off day on 2026-08-13, which failed the
    run with `[unsupported_claim] astros.game_count: value 0 does not appear in any
    observation it points at`.

    Nothing was wrong with the digest. `game_count: 0` was a claim about the observation's
    cardinality, and the observation is `[]`.
    """
    from forecaster.trace import check_provenance

    client, _ = fixture_client([Route(SCHEDULE_URL, fixture="mlb_no_game")])
    trace = trace_in(tmp_path, "off-day")
    with client:
        result = AstrosBeat().run(make_context(trace=trace, http_client=client))
        trace.beat_result(result)
    digest = "\n".join(item.text for item in result.items)
    trace.digest(digest, order=["astros"])
    trace.close()

    report = check_provenance(trace.path)

    assert report.ok, report.summary()
    assert "game today." in digest and not any(char.isdigit() for char in digest), (
        "the off-day line states no number, which is why it declares nothing checkable"
    )

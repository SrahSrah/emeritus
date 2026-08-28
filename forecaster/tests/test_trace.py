"""Step 6 — the trace round-trips, and the provenance check has teeth."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.trace import (
    SecretInTraceError,
    Trace,
    TraceError,
    check_provenance,
    read_trace,
    records_of,
)

FINAL_PAYLOAD = {
    "dates": [
        {
            "date": "2026-07-26",
            "games": [
                {
                    "gamePk": 824572,
                    "status": {"abstractGameState": "Final"},
                    "teams": {
                        "away": {"team": {"name": "Houston Astros"}, "score": 3},
                        "home": {"team": {"name": "Chicago White Sox"}, "score": 12},
                    },
                }
            ],
        }
    ]
}

CLEAN_DIGEST = (
    "Tonight's digest.\n"
    "Astros: Final — Astros 3, White Sox 12.\n"
    "Weather: run-window low 76F, 0% chance of rain.\n"
)


def _synthetic_run(tmp_path: Path, digest: str = CLEAN_DIGEST) -> Path:
    """Write one complete run: every record type, in pipeline order."""
    with Trace("run-under-test", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="abc123")
        trace.plan(
            [
                {"beat": "astros", "criterion": "last final reported"},
                {"beat": "weather", "criterion": "5-8am window covered"},
            ]
        )

        mlb_obs = trace.tool_call(
            beat="astros",
            adapter="mlb.fetch_schedule",
            arguments={"team_id": 117, "date": "2026-07-26"},
        )
        trace.observation(mlb_obs, payload=FINAL_PAYLOAD)
        trace.decision(
            beat="astros",
            decision="report_final",
            reason="today's only game is Final",
        )
        trace.beat_result(
            BeatResult(
                beat="astros",
                items=[
                    BeatItem(
                        beat="astros",
                        text="Final — Astros 3, White Sox 12.",
                        fields={"away_score": 3, "home_score": 12},
                        observations=[
                            ObservationRef(mlb_obs, "mlb.fetch_schedule")
                        ],
                    )
                ],
                checkable_fields={
                    "score": "Astros 3, White Sox 12",
                    "game_state": "Final",
                },
                observations=[ObservationRef(mlb_obs, "mlb.fetch_schedule")],
            )
        )

        wx_obs = trace.tool_call(
            beat="weather",
            adapter="weather.fetch_hourly_forecast",
            arguments={"lat": 30.2672, "lon": -97.7431},
        )
        trace.observation(
            wx_obs,
            payload={
                "periods": [
                    {"temperature": 76, "probabilityOfPrecipitation": {"value": 0}}
                ]
            },
        )
        trace.beat_result(
            BeatResult(
                beat="weather",
                items=[
                    BeatItem(
                        beat="weather",
                        text="Run-window low 76F, 0% chance of rain.",
                        observations=[
                            ObservationRef(wx_obs, "weather.fetch_hourly_forecast")
                        ],
                    )
                ],
                checkable_fields={"run_window_low_f": 76, "precip_probability_pct": 0},
                observations=[ObservationRef(wx_obs, "weather.fetch_hourly_forecast")],
            )
        )

        trace.escalation(
            rule="freeze_alert", fired=False, reason="low 76F is above 32F", beat="weather"
        )
        trace.digest(digest, order=["astros", "weather"])
        trace.delivery(deliverer="FakeDeliverer", target="nobody@example.test", success=True)
        trace.run_end(duration_ms=4210, input_tokens=0, output_tokens=0)
    return trace.path


# --------------------------------------------------------------------------- #
# Writing and round-tripping
# --------------------------------------------------------------------------- #


def test_every_record_type_round_trips_as_valid_json_lines(tmp_path: Path) -> None:
    path = _synthetic_run(tmp_path)

    raw_lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert raw_lines, "trace file is empty"
    for line in raw_lines:
        json.loads(line)  # the PowerShell ConvertFrom-Json verify, as a test

    records = read_trace(path)
    seen = {record["type"] for record in records}
    assert seen == {
        "run_start",
        "plan",
        "tool_call",
        "observation",
        "decision",
        "beat_result",
        "escalation",
        "digest",
        "delivery",
        "run_end",
    }
    assert all(record["run_id"] == "run-under-test" for record in records)
    assert all(record["at"] for record in records)


def test_run_start_stamps_the_auth_mode_for_fr14(tmp_path: Path) -> None:
    path = _synthetic_run(tmp_path)
    start = next(records_of(read_trace(path), "run_start"))
    assert start["auth_mode"] == "subscription_oauth"
    assert start["config_digest"] == "abc123"


def test_tool_call_returns_a_stable_observation_id_that_links(tmp_path: Path) -> None:
    path = _synthetic_run(tmp_path)
    records = read_trace(path)
    call_ids = {record["observation_id"] for record in records_of(records, "tool_call")}
    obs_ids = {record["observation_id"] for record in records_of(records, "observation")}
    linked = {
        oid
        for record in records_of(records, "beat_result")
        for oid in record["observations"]
    }
    assert call_ids == obs_ids
    assert linked <= obs_ids


def test_run_end_totals_tokens(tmp_path: Path) -> None:
    with Trace("tokens", directory=tmp_path) as trace:
        trace.run_end(duration_ms=1, input_tokens=120, output_tokens=45)
    end = next(records_of(read_trace(trace.path), "run_end"))
    assert end["total_tokens"] == 165


def test_trace_refuses_to_write_a_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-VERY-SECRET-VALUE")
    with Trace("secret", directory=tmp_path) as trace:
        with pytest.raises(SecretInTraceError):
            trace.decision(
                beat="astros",
                decision="oops",
                reason="token is sk-ant-oat01-VERY-SECRET-VALUE",
            )


def test_writing_to_a_closed_trace_raises(tmp_path: Path) -> None:
    trace = Trace("closed", directory=tmp_path)
    trace.close()
    with pytest.raises(TraceError, match="already closed"):
        trace.decision(beat="x", decision="y", reason="z")


def test_reading_a_malformed_trace_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    path.write_text('{"type": "run_start"}\nnot json\n', encoding="utf-8")
    with pytest.raises(TraceError, match="not valid JSON"):
        read_trace(path)


# --------------------------------------------------------------------------- #
# check_provenance
# --------------------------------------------------------------------------- #


def test_clean_run_passes_with_no_other_input_than_the_trace(tmp_path: Path) -> None:
    path = _synthetic_run(tmp_path)

    report = check_provenance(path)  # digest read from the trace itself

    assert report.ok, report.summary()
    assert report.violations == []
    assert report.checked_fields == 4
    assert "provenance OK" in report.summary()


def test_a_score_changed_by_one_is_caught(tmp_path: Path) -> None:
    """The negative case: a fabricated claim must fail the metric."""
    tampered = CLEAN_DIGEST.replace("Astros 3, White Sox 12", "Astros 4, White Sox 12")
    path = _synthetic_run(tmp_path, digest=tampered)

    report = check_provenance(path)

    assert not report.ok
    assert any(v.kind == "altered_claim" for v in report.violations)
    assert "Astros 4, White Sox 12" in report.summary()


def test_a_temperature_changed_by_ten_is_caught(tmp_path: Path) -> None:
    tampered = CLEAN_DIGEST.replace("low 76F", "low 66F")
    path = _synthetic_run(tmp_path, digest=tampered)

    report = check_provenance(path)

    assert not report.ok
    assert any(v.kind == "altered_claim" for v in report.violations)


def test_a_claim_with_no_matching_observation_is_caught(tmp_path: Path) -> None:
    """Hand-built run: the digest states a score the trace never observed."""
    with Trace("fabricated", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")
        obs = trace.tool_call(beat="astros", adapter="mlb.fetch_schedule", arguments={})
        trace.observation(obs, payload={"dates": []})
        trace.beat_result(
            BeatResult(
                beat="astros",
                items=[BeatItem(beat="astros", text="Final — Astros 9, Rangers 1.")],
                checkable_fields={"score": "Astros 9, Rangers 1"},
                observations=[ObservationRef(obs, "mlb.fetch_schedule")],
            )
        )
        trace.digest("Astros: Final — Astros 9, Rangers 1.")
        trace.run_end(duration_ms=1)

    report = check_provenance(trace.path)

    assert not report.ok
    assert any(v.kind == "unsupported_claim" for v in report.violations)
    assert "score" in report.summary()


def test_a_claim_with_no_linked_observation_at_all_is_caught(tmp_path: Path) -> None:
    with Trace("unlinked", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")
        trace.beat_result(
            BeatResult(beat="astros", checkable_fields={"score": "Astros 5, Rangers 3"})
        )
        trace.digest("Astros 5, Rangers 3")
        trace.run_end(duration_ms=1)

    report = check_provenance(trace.path)

    assert not report.ok
    assert any("no linked observation" in v.detail for v in report.violations)


def test_a_failed_beat_that_vanished_from_the_digest_is_caught(tmp_path: Path) -> None:
    with Trace("silent-failure", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")
        trace.beat_result(
            BeatResult.unavailable("astros", "MLB Stats API returned 500")
        )
        trace.digest("Weather: run-window low 76F.")
        trace.run_end(duration_ms=1)

    report = check_provenance(trace.path)

    assert not report.ok
    assert any(v.kind == "missing_unavailability_line" for v in report.violations)


def test_a_failed_beat_named_in_the_digest_passes(tmp_path: Path) -> None:
    with Trace("honest-failure", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")
        trace.beat_result(
            BeatResult.unavailable("astros", "MLB Stats API returned 500")
        )
        trace.digest("Couldn't reach astros tonight (MLB Stats API returned 500).")
        trace.run_end(duration_ms=1)

    report = check_provenance(trace.path)

    assert report.ok, report.summary()


def test_omitting_a_declared_value_is_a_note_not_a_violation(tmp_path: Path) -> None:
    """FR-11 says "appears only if it matches" — silence is allowed."""
    path = _synthetic_run(tmp_path, digest="Nothing much to report tonight.")

    report = check_provenance(path)

    assert report.ok, report.summary()
    assert report.notes


def test_check_provenance_needs_a_recorded_digest(tmp_path: Path) -> None:
    with Trace("no-digest", directory=tmp_path) as trace:
        trace.run_start(auth_mode="subscription_oauth", config_digest="x")
        trace.run_end(duration_ms=1)
    with pytest.raises(TraceError, match="records no digest"):
        check_provenance(trace.path)


def test_explicit_digest_argument_overrides_the_recorded_one(tmp_path: Path) -> None:
    path = _synthetic_run(tmp_path)
    tampered = CLEAN_DIGEST.replace("White Sox 12", "White Sox 13")

    assert check_provenance(path).ok
    assert not check_provenance(path, tampered).ok


# --------------------------------------------------------------------------- #
# Two true claims that share a sentence shape (found live 2026-08-04)
# --------------------------------------------------------------------------- #
#
# The first real nightly run against a live series failed the provenance check on two
# mirrored violations. Both scorelines were true and both were observation-backed:
# Toronto 0, Houston 0 (tonight, Warmup) and Toronto 3, Houston 1 (last night, Final).
# A numbers-are-wildcards template built from either one matches the other's sentence,
# so the check compared numbers across two different games and called it tampering.
#
# The beat was right; the checker was wrong. These pin both halves of the fix.


def _series_trace(directory: Path, digest: str) -> Path:
    """The shape of the run that failed: one live game, one final, same two teams."""
    trace = Trace("series", directory=directory)
    trace.run_start(auth_mode="subscription_oauth", config_digest="test")

    observation_id = trace.tool_call(
        beat="astros", adapter="mlb.fetch_schedule", arguments={"teamId": 117}
    )
    trace.observation(
        observation_id,
        payload={
            "games": [
                {"state": "Live", "detailed_state": "Warmup",
                 "away": "Toronto Blue Jays", "away_score": 0,
                 "home": "Houston Astros", "home_score": 0},
                {"state": "Final", "detailed_state": "Final",
                 "away": "Toronto Blue Jays", "away_score": 3,
                 "home": "Houston Astros", "home_score": 1},
            ]
        },
    )

    trace._write(  # noqa: SLF001 - the record the beat emits
        "beat_result",
        beat="astros",
        items=[
            {
                "beat": "astros",
                "text": "Live now: Toronto Blue Jays 0, Houston Astros 0.",
                "fields": {"game_date": "2026-08-04"},
                "observations": [observation_id],
            },
            {
                "beat": "astros",
                "text": "Last completed: Toronto Blue Jays 3, Houston Astros 1.",
                "fields": {"game_date": "2026-08-03"},
                "observations": [observation_id],
            },
        ],
        checkable_fields={
            "live_score": "Toronto Blue Jays 0, Houston Astros 0",
            "live_game_state": "Warmup",
            "last_completed_score": "Toronto Blue Jays 3, Houston Astros 1",
            "last_completed_state": "Final",
        },
        available=True,
        error=None,
        escalation_candidate=False,
        escalation_reason=None,
        escalation_signals={},
        observations=[observation_id],
    )
    trace.digest(digest, order=["astros"])
    trace.close()
    return trace.path


def test_two_observed_scores_of_the_same_shape_do_not_fail_each_other(tmp_path: Path) -> None:
    """The live regression, verbatim from the 2026-08-04 run that failed."""
    path = _series_trace(
        tmp_path,
        "Live now: Toronto Blue Jays 0, Houston Astros 0.\n"
        "Last completed: Toronto Blue Jays 3, Houston Astros 1.",
    )

    report = check_provenance(path)

    assert report.ok, report.summary()


def test_a_score_the_model_altered_is_still_caught_in_the_same_situation(
    tmp_path: Path,
) -> None:
    """The fix may not buy its false-positive relief by going blind.

    Same two-game night, but the final is reported 4-1 when the observation says 3-1.
    That sentence matches the shape and matches **no** observation, which is exactly the
    fabricated-box-score failure the check exists for.
    """
    path = _series_trace(
        tmp_path,
        "Live now: Toronto Blue Jays 0, Houston Astros 0.\n"
        "Last completed: Toronto Blue Jays 4, Houston Astros 1.",
    )

    report = check_provenance(path)

    assert not report.ok
    assert {v.kind for v in report.violations} == {"altered_claim"}
    assert all("4, Houston Astros 1" in v.detail for v in report.violations)
    # The true score is never itself flagged — only the invented one.
    assert not any("3, Houston Astros 1'," in v.detail for v in report.violations)


def test_an_invented_third_game_is_caught(tmp_path: Path) -> None:
    """A plausible extra line that no observation backs."""
    path = _series_trace(
        tmp_path,
        "Live now: Toronto Blue Jays 0, Houston Astros 0.\n"
        "Last completed: Toronto Blue Jays 3, Houston Astros 1.\n"
        "Earlier: Toronto Blue Jays 7, Houston Astros 2.",
    )

    report = check_provenance(path)

    assert not report.ok
    assert any("7, Houston Astros 2" in v.detail for v in report.violations)


def test_the_fix_is_case_insensitive_like_the_template_it_guards(tmp_path: Path) -> None:
    """`_template` compiles IGNORECASE — the exemption has to match that or it misfires."""
    path = _series_trace(
        tmp_path,
        "live now: toronto blue jays 0, houston astros 0.\n"
        "last completed: TORONTO BLUE JAYS 3, HOUSTON ASTROS 1.",
    )

    assert check_provenance(path).ok

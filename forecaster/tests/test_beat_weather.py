"""Step 12 — the freeze threshold, both directions, and it comes from config."""

from __future__ import annotations

from pathlib import Path

from forecaster.beats.weather import WeatherBeat
from forecaster.trace import read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import HOURLY_URL, POINTS_URL, make_config, make_context, trace_in


def _run(tmp_path: Path, hourly_fixture: str, **context_kwargs):
    client, recorder = fixture_client(
        [
            Route(POINTS_URL, fixture="nws_points_austin"),
            Route(HOURLY_URL, fixture=hourly_fixture),
        ]
    )
    trace = trace_in(tmp_path, "weather-run")
    with client, trace:
        context = make_context(trace=trace, http_client=client, **context_kwargs)
        result = WeatherBeat().run(context)
    return result, trace, recorder


# --------------------------------------------------------------------------- #
# FR-6's acceptance criterion — both directions
# --------------------------------------------------------------------------- #


def test_a_fixture_below_the_threshold_yields_escalation_candidate_true(
    tmp_path: Path,
) -> None:
    result, trace, _ = _run(tmp_path, "nws_hourly_austin_freezing")

    assert result.available is True
    assert result.escalation_candidate is True
    assert result.escalation_reason
    assert "28" in result.escalation_reason
    assert "32" in result.escalation_reason
    assert result.checkable_fields["run_window_low_f"] == 28

    decisions = list(records_of(read_trace(trace.path), "decision"))
    evaluated = [d for d in decisions if d["decision"] == "freeze_threshold_evaluated"]
    assert evaluated and evaluated[0]["low"] == 28
    assert evaluated[0]["threshold"] == 32.0


def test_a_fixture_above_the_threshold_yields_escalation_candidate_false(
    tmp_path: Path,
) -> None:
    result, _, _ = _run(tmp_path, "nws_hourly_austin")

    assert result.available is True
    assert result.escalation_candidate is False
    assert result.escalation_reason is None
    assert result.checkable_fields["run_window_low_f"] == 76


def test_the_threshold_comes_from_config_not_from_code(tmp_path: Path) -> None:
    """Same fixture, different config value, opposite outcome."""
    warm_config = make_config(
        escalation={
            "rules": ["freeze_alert"],
            "freeze_threshold_f": 32.0,
            "freeze_horizon_days": 1,
            "watched_players": [],
        }
    )
    hot_config = make_config(
        escalation={
            "rules": ["freeze_alert"],
            "freeze_threshold_f": 80.0,  # Austin in July is "cold" by this threshold
            "freeze_horizon_days": 1,
            "watched_players": [],
        }
    )

    normal, _, _ = _run(tmp_path, "nws_hourly_austin", config=warm_config)
    flipped, _, _ = _run(tmp_path, "nws_hourly_austin", config=hot_config)

    assert normal.escalation_candidate is False
    assert flipped.escalation_candidate is True
    assert "80" in (flipped.escalation_reason or "")


# --------------------------------------------------------------------------- #
# The values FR-11 polices
# --------------------------------------------------------------------------- #


def test_checkable_fields_are_exactly_temperature_wind_and_precipitation(
    tmp_path: Path,
) -> None:
    result, _, _ = _run(tmp_path, "nws_hourly_austin")

    assert set(result.checkable_fields) == {
        "run_window_low_f",
        "run_window_high_f",
        "precip_probability_pct",
        "wind_speed",
    }
    assert result.checkable_fields["wind_speed"] == "5 mph"
    assert result.checkable_fields["precip_probability_pct"] == 0


def test_every_checkable_value_points_at_a_recorded_observation(tmp_path: Path) -> None:
    result, trace, _ = _run(tmp_path, "nws_hourly_austin")

    recorded = {
        record["observation_id"]
        for record in records_of(read_trace(trace.path), "observation")
    }
    cited = {ref.observation_id for ref in result.observations}
    assert cited and cited <= recorded


def test_the_beat_reports_only_the_next_morning_window(tmp_path: Path) -> None:
    result, trace, _ = _run(tmp_path, "nws_hourly_austin")

    observation = next(records_of(read_trace(trace.path), "observation"))
    payload = observation["payload"]
    assert payload["morning"] == "2026-07-28"
    assert len(payload["periods"]) == 3
    assert payload["grid"] == "EWX 156,91"


def test_an_uncovered_window_is_unavailable_rather_than_invented(tmp_path: Path) -> None:
    from datetime import datetime

    result, _, _ = _run(
        tmp_path,
        "nws_hourly_austin",
        now=datetime(2030, 1, 1, 19, 0),  # far outside the recorded forecast
    )

    assert result.available is False
    assert "did not cover" in (result.error or "")
    assert result.checkable_fields == {}


def test_no_dressing_advice_beyond_what_the_numbers_support(tmp_path: Path) -> None:
    result, _, _ = _run(tmp_path, "nws_hourly_austin_freezing")

    text = " ".join(item.text for item in result.items).lower()
    for invented in ("wear", "jacket", "gloves", "layer", "bundle"):
        assert invented not in text


def test_the_beat_does_not_import_the_planner_synthesizer_or_delivery() -> None:
    source = (
        Path(__file__).resolve().parent.parent / "forecaster" / "beats" / "weather.py"
    ).read_text(encoding="utf-8")
    offenders = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
        and any(bad in line for bad in ("planner", "synthesizer", "delivery"))
    ]
    assert offenders == []


def test_should_run_follows_config(tmp_path: Path) -> None:
    trace = trace_in(tmp_path)
    with trace:
        on = make_context(trace=trace, http_client=None)
        off = make_context(
            trace=trace,
            http_client=None,
            config=make_config(beats={"astros": True, "weather": False}),
        )
    assert WeatherBeat().should_run(on) is True
    assert WeatherBeat().should_run(off) is False

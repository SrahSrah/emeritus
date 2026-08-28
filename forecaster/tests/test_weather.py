"""Step 10 — the NWS adapter, entirely off recorded fixtures.

The `User-Agent` assertion is the load-bearing one: without the header NWS answers 403,
and PRD §8 flags that as the failure that looks like an outage.
"""

from __future__ import annotations

from datetime import date, datetime, time

import httpx
import pytest

from forecaster.tools.mlb import AdapterError
from forecaster.tools.weather import (
    fetch_hourly_forecast,
    next_morning,
    parse_hourly,
    run_window_periods,
    user_agent,
)
from tests.conftest import Route, fixture_client, load_fixture

LAT, LON = 30.2672, -97.7431
POINTS = r"api\.weather\.gov/points/"
HOURLY = r"api\.weather\.gov/gridpoints/"

NEXT_MORNING = date(2026, 7, 28)
WINDOW_START, WINDOW_END = time(5, 0), time(8, 0)


def _client(hourly_fixture: str = "nws_hourly_austin"):
    return fixture_client(
        [
            Route(POINTS, fixture="nws_points_austin"),
            Route(HOURLY, fixture=hourly_fixture),
        ]
    )


# --------------------------------------------------------------------------- #
# FR-4's acceptance criterion
# --------------------------------------------------------------------------- #


def test_lat_long_resolves_the_grid_point_rather_than_hardcoding_it() -> None:
    client, recorder = _client()
    with client:
        forecast = fetch_hourly_forecast(LAT, LON, client=client)

    assert forecast.grid.label == "EWX 156,91"
    assert forecast.grid.office == "EWX"
    assert (forecast.grid.x, forecast.grid.y) == (156, 91)
    assert forecast.grid.forecast_hourly_url.endswith("/forecast/hourly")

    # Two hops: points first, then the URL that response handed back.
    assert len(recorder.requests) == 2
    assert "/points/" in str(recorder.requests[0].url)
    assert str(recorder.requests[1].url) == forecast.grid.forecast_hourly_url


def test_every_outgoing_request_sends_a_user_agent() -> None:
    client, recorder = _client()
    with client:
        fetch_hourly_forecast(LAT, LON, client=client)

    assert len(recorder.requests) == 2
    for request in recorder.requests:
        assert "user-agent" in {key.lower() for key in request.headers}
        assert request.headers["User-Agent"] == user_agent()
        assert request.headers["User-Agent"].strip()


def test_the_forecast_covers_the_five_to_eight_am_window() -> None:
    client, _ = _client()
    with client:
        forecast = fetch_hourly_forecast(LAT, LON, client=client)

    window = run_window_periods(
        forecast.periods, day=NEXT_MORNING, start=WINDOW_START, end=WINDOW_END
    )

    assert len(window) == 3
    assert [period.local_hour for period in window] == [5, 6, 7]
    assert all(period.start_time.date() == NEXT_MORNING for period in window)
    assert all(period.temperature_unit == "F" for period in window)
    assert all(period.wind_speed for period in window)
    assert all(period.precip_probability_pct is not None for period in window)


def test_the_recorded_july_window_is_well_above_freezing() -> None:
    """The above-threshold half of FR-6's pair, straight off the real capture."""
    client, _ = _client()
    with client:
        forecast = fetch_hourly_forecast(LAT, LON, client=client)

    window = run_window_periods(
        forecast.periods, day=NEXT_MORNING, start=WINDOW_START, end=WINDOW_END
    )
    assert min(period.temperature for period in window) == 76


def test_the_synthetic_freezing_fixture_is_below_the_threshold() -> None:
    client, _ = _client("nws_hourly_austin_freezing")
    with client:
        forecast = fetch_hourly_forecast(LAT, LON, client=client)

    window = run_window_periods(
        forecast.periods, day=NEXT_MORNING, start=WINDOW_START, end=WINDOW_END
    )
    assert len(window) == 3
    assert max(period.temperature for period in window) == 28
    assert all(period.precip_probability_pct == 40 for period in window)


# --------------------------------------------------------------------------- #
# Failure contract — the 403 must name the header
# --------------------------------------------------------------------------- #


def test_a_403_surfaces_as_an_error_naming_the_user_agent_not_an_empty_forecast() -> None:
    client, _ = fixture_client(
        [Route(POINTS, json_body={"detail": "Forbidden"}, status=403)]
    )
    with client, pytest.raises(AdapterError) as excinfo:
        fetch_hourly_forecast(LAT, LON, client=client)

    message = str(excinfo.value)
    assert excinfo.value.status == 403
    assert "User-Agent" in message
    assert "not an outage" in message


def test_a_500_on_the_second_hop_raises() -> None:
    client, _ = fixture_client(
        [
            Route(POINTS, fixture="nws_points_austin"),
            Route(HOURLY, json_body={"detail": "boom"}, status=500),
        ]
    )
    with client, pytest.raises(AdapterError, match="500"):
        fetch_hourly_forecast(LAT, LON, client=client)


def test_a_timeout_raises_adapter_error() -> None:
    client, _ = fixture_client([Route(POINTS, exc=httpx.ReadTimeout("slow"))])
    with client, pytest.raises(AdapterError, match="timed out"):
        fetch_hourly_forecast(LAT, LON, client=client)


def test_a_points_payload_without_a_grid_raises() -> None:
    client, _ = fixture_client([Route(POINTS, json_body={"properties": {}})])
    with client, pytest.raises(AdapterError, match="missing `gridId`"):
        fetch_hourly_forecast(LAT, LON, client=client)


def test_a_period_with_a_non_numeric_temperature_raises() -> None:
    payload = load_fixture("nws_hourly_austin")
    payload["properties"]["periods"][0]["temperature"] = "warm"
    with pytest.raises(AdapterError, match="non-numeric temperature"):
        parse_hourly(payload)


def test_a_payload_with_no_periods_raises() -> None:
    with pytest.raises(AdapterError, match="no `periods` list"):
        parse_hourly({"properties": {}})


# --------------------------------------------------------------------------- #
# Window helper
# --------------------------------------------------------------------------- #


def test_next_morning_is_tomorrow_because_the_digest_sends_at_7pm() -> None:
    assert next_morning(datetime(2026, 7, 27, 19, 0)) == date(2026, 7, 28)
    assert next_morning(datetime(2026, 12, 31, 19, 0)) == date(2027, 1, 1)


def test_the_window_slice_excludes_the_end_hour() -> None:
    client, _ = _client()
    with client:
        forecast = fetch_hourly_forecast(LAT, LON, client=client)

    window = run_window_periods(
        forecast.periods, day=NEXT_MORNING, start=WINDOW_START, end=WINDOW_END
    )
    assert 8 not in [period.local_hour for period in window]

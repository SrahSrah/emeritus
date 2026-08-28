"""NWS weather adapter (FR-4).

Two hops against `api.weather.gov`: ``/points/{lat},{lon}`` resolves the grid office and
x/y, then the ``properties.forecastHourly`` URL it hands back gives the hourly forecast.
The grid is **resolved, never hardcoded** — the point of the first hop is that moving the
location is a config edit.

**Every request carries a `User-Agent`.** NWS answers 403 without one, which PRD §8 calls
out as "a silent 403 that looks like an outage". A test asserts the header is on every
outgoing request, and a 403 surfaces as an error naming the header rather than as an
empty forecast.

Free, no key, no paid tier.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any, Iterable, Mapping, Sequence

import httpx

from forecaster.tools.mlb import AdapterError

POINTS_URL = "https://api.weather.gov/points/{lat},{lon}"
ADAPTER_NAME = "weather.fetch_hourly_forecast"
DEFAULT_TIMEOUT = 30.0

CONTACT_PLACEHOLDER = "your.email@example.com"


def user_agent() -> str:
    """Contact string NWS asks API clients to send. Not a secret; not a credential.

    Read at call time, not import time: ``load_env()`` populates CONTACT_EMAIL from the
    gitignored ``.env`` after this module is imported.
    """
    contact = os.environ.get("CONTACT_EMAIL", "").strip() or CONTACT_PLACEHOLDER
    return f"forecaster-capstone ({contact})"


def request_headers() -> dict[str, str]:
    return {"User-Agent": user_agent(), "Accept": "application/geo+json"}


@dataclass(frozen=True)
class GridPoint:
    """What ``/points`` resolved to."""

    office: str
    x: int
    y: int
    forecast_hourly_url: str
    timezone: str

    @property
    def label(self) -> str:
        return f"{self.office} {self.x},{self.y}"


@dataclass(frozen=True)
class HourlyPeriod:
    """One hour of forecast, normalized."""

    start_time: datetime
    end_time: datetime
    temperature: float
    temperature_unit: str
    wind_speed: str
    wind_direction: str
    precip_probability_pct: int | None
    short_forecast: str

    @property
    def local_hour(self) -> int:
        return self.start_time.hour


@dataclass(frozen=True)
class HourlyForecast:
    """The grid point plus its periods, so callers can cite both."""

    grid: GridPoint
    periods: list[HourlyPeriod]


def _get(client: httpx.Client, url: str, *, timeout: float, what: str) -> Any:
    try:
        response = client.get(url, headers=request_headers(), timeout=timeout)
    except httpx.TimeoutException as exc:
        raise AdapterError(
            f"api.weather.gov timed out after {timeout}s fetching {what}",
            adapter=ADAPTER_NAME,
        ) from exc
    except httpx.HTTPError as exc:
        raise AdapterError(
            f"api.weather.gov request for {what} failed: {exc}", adapter=ADAPTER_NAME
        ) from exc

    if response.status_code == 403:
        raise AdapterError(
            "api.weather.gov returned 403 fetching "
            f"{what}. NWS rejects requests without a descriptive `User-Agent` header — "
            "this is a rejected request, not an outage.",
            adapter=ADAPTER_NAME,
            status=403,
        )
    if response.status_code >= 400:
        raise AdapterError(
            f"api.weather.gov returned {response.status_code} fetching {what}",
            adapter=ADAPTER_NAME,
            status=response.status_code,
        )

    try:
        return response.json()
    except ValueError as exc:
        raise AdapterError(
            f"api.weather.gov returned a non-JSON body for {what}", adapter=ADAPTER_NAME
        ) from exc


def parse_grid_point(payload: Any) -> GridPoint:
    if not isinstance(payload, Mapping):
        raise AdapterError("points payload is not an object", adapter=ADAPTER_NAME)
    props = payload.get("properties")
    if not isinstance(props, Mapping):
        raise AdapterError("points payload has no `properties`", adapter=ADAPTER_NAME)
    for key in ("gridId", "gridX", "gridY", "forecastHourly"):
        if key not in props:
            raise AdapterError(
                f"points payload is missing `{key}` — the endpoint's shape may have changed",
                adapter=ADAPTER_NAME,
            )
    return GridPoint(
        office=str(props["gridId"]),
        x=int(props["gridX"]),
        y=int(props["gridY"]),
        forecast_hourly_url=str(props["forecastHourly"]),
        timezone=str(props.get("timeZone", "")),
    )


def _period_number(raw: Mapping[str, Any], key: str) -> int | None:
    block = raw.get(key)
    if not isinstance(block, Mapping):
        return None
    value = block.get("value")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AdapterError(
            f"hourly payload has a non-numeric {key}: {value!r}", adapter=ADAPTER_NAME
        )
    return int(value)


def _parse_time(raw: Any, key: str) -> datetime:
    if not isinstance(raw, str):
        raise AdapterError(
            f"hourly payload has a non-string {key}: {raw!r}", adapter=ADAPTER_NAME
        )
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise AdapterError(
            f"hourly payload has an unparseable {key} {raw!r}", adapter=ADAPTER_NAME
        ) from exc


def parse_hourly(payload: Any) -> list[HourlyPeriod]:
    if not isinstance(payload, Mapping):
        raise AdapterError("hourly payload is not an object", adapter=ADAPTER_NAME)
    props = payload.get("properties")
    if not isinstance(props, Mapping):
        raise AdapterError("hourly payload has no `properties`", adapter=ADAPTER_NAME)
    raw_periods = props.get("periods")
    if not isinstance(raw_periods, list):
        raise AdapterError("hourly payload has no `periods` list", adapter=ADAPTER_NAME)

    periods: list[HourlyPeriod] = []
    for raw in raw_periods:
        if not isinstance(raw, Mapping):
            raise AdapterError("hourly payload has a malformed period", adapter=ADAPTER_NAME)
        temperature = raw.get("temperature")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise AdapterError(
                f"hourly payload has a non-numeric temperature: {temperature!r}",
                adapter=ADAPTER_NAME,
            )
        periods.append(
            HourlyPeriod(
                start_time=_parse_time(raw.get("startTime"), "startTime"),
                end_time=_parse_time(raw.get("endTime"), "endTime"),
                temperature=float(temperature),
                temperature_unit=str(raw.get("temperatureUnit", "")),
                wind_speed=str(raw.get("windSpeed", "")),
                wind_direction=str(raw.get("windDirection", "")),
                precip_probability_pct=_period_number(raw, "probabilityOfPrecipitation"),
                short_forecast=str(raw.get("shortForecast", "")),
            )
        )
    return periods


def fetch_hourly_forecast(
    lat: float,
    lon: float,
    *,
    client: httpx.Client,
    timeout: float = DEFAULT_TIMEOUT,
) -> HourlyForecast:
    """Resolve the grid point from lat/long, then fetch its hourly forecast."""
    points_payload = _get(
        client,
        POINTS_URL.format(lat=lat, lon=lon),
        timeout=timeout,
        what="the grid point",
    )
    grid = parse_grid_point(points_payload)

    hourly_payload = _get(
        client, grid.forecast_hourly_url, timeout=timeout, what="the hourly forecast"
    )
    return HourlyForecast(grid=grid, periods=parse_hourly(hourly_payload))


def run_window_periods(
    periods: Sequence[HourlyPeriod],
    *,
    day: date,
    start: time,
    end: time,
) -> list[HourlyPeriod]:
    """Slice the periods covering ``[start, end)`` local on ``day``.

    The times on the payload already carry the grid's local offset, so this compares
    local wall-clock hours rather than converting anything.
    """
    return [
        period
        for period in periods
        if period.start_time.date() == day and start <= period.start_time.time() < end
    ]


def next_morning(now: datetime) -> date:
    """The morning the digest is about: tomorrow, since the digest sends at 7 pm."""
    from datetime import timedelta

    return (now + timedelta(days=1)).date()


__all__ = [
    "ADAPTER_NAME",
    "request_headers",
    "POINTS_URL",
    "user_agent",
    "AdapterError",
    "GridPoint",
    "HourlyForecast",
    "HourlyPeriod",
    "fetch_hourly_forecast",
    "next_morning",
    "parse_grid_point",
    "parse_hourly",
    "run_window_periods",
]

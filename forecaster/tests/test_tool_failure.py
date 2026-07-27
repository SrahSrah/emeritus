"""Step 15 — FR-18: when a tool fails, the digest says so and invents nothing.

Every test injects `FakeAgentClient`. The model is never asked to fill a gap.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from forecaster.agent import FakeAgentClient
from forecaster.beats.astros import AstrosBeat
from forecaster.beats.base import BeatResult, run_beat_safely
from forecaster.beats.weather import WeatherBeat
from forecaster.memory.preferences import parse_preferences
from forecaster.synthesizer import synthesize
from forecaster.trace import check_provenance, read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import (
    HOURLY_URL,
    POINTS_URL,
    SCHEDULE_URL,
    make_config,
    make_context,
    trace_in,
)

CONFIG = make_config()
PREFS = parse_preferences({"topics": {"astros": 1.0, "weather": 1.0}})

MLB_500 = Route(SCHEDULE_URL, json_body={"detail": "boom"}, status=500)
MLB_OK = Route(SCHEDULE_URL, fixture="mlb_final")
WX_OK = [
    Route(POINTS_URL, fixture="nws_points_austin"),
    Route(HOURLY_URL, fixture="nws_hourly_austin"),
]
WX_TIMEOUT = Route(POINTS_URL, exc=httpx.ReadTimeout("nws is slow"))


def _run_pipeline(tmp_path: Path, routes, beats, run_id="failure-run"):
    """Run the beats through the failure wrapper, then synthesize."""
    client, _ = fixture_client(routes)
    trace = trace_in(tmp_path, run_id)
    agent = FakeAgentClient()
    with client, trace:
        context = make_context(trace=trace, http_client=client)
        results = [run_beat_safely(beat, context) for beat in beats]
        for result in results:
            trace.beat_result(result)
        digest = synthesize(results, CONFIG, PREFS, trace, agent_client=agent)
    return results, digest, trace, agent


# --------------------------------------------------------------------------- #
# FR-18's acceptance criterion, exactly
# --------------------------------------------------------------------------- #


def test_a_500_on_mlb_yields_an_unavailability_line_no_score_and_clean_provenance(
    tmp_path: Path,
) -> None:
    results, digest, trace, agent = _run_pipeline(
        tmp_path, [MLB_500, *WX_OK], [AstrosBeat(), WeatherBeat()]
    )

    astros = results[0]
    assert astros.available is False
    assert "500" in (astros.error or "")
    assert astros.checkable_fields == {}

    # (a) an explicit unavailability line, naming the beat
    assert "Couldn't reach astros tonight" in digest.text
    assert "500" in digest.text

    # (b) no score anywhere
    for forbidden in ("Astros 3", "White Sox 12", "Final:"):
        assert forbidden not in digest.text

    # (c) the FR-11 provenance test passes on that run
    report = check_provenance(trace.path)
    assert report.ok, report.summary()
    assert digest.provenance is not None and digest.provenance.ok


def test_a_weather_timeout_does_the_same(tmp_path: Path) -> None:
    results, digest, trace, _ = _run_pipeline(
        tmp_path, [MLB_OK, WX_TIMEOUT], [AstrosBeat(), WeatherBeat()], "wx-timeout"
    )

    weather = results[1]
    assert weather.available is False
    assert "timed out" in (weather.error or "")
    assert weather.checkable_fields == {}

    assert "Couldn't reach weather tonight" in digest.text
    assert "timed out" in digest.text
    assert check_provenance(trace.path).ok


def test_one_beat_failing_still_delivers_the_other_beats_content(
    tmp_path: Path,
) -> None:
    _, digest, trace, _ = _run_pipeline(
        tmp_path, [MLB_500, *WX_OK], [AstrosBeat(), WeatherBeat()], "partial"
    )

    assert "Couldn't reach astros tonight" in digest.text
    assert "Run window" in digest.text, "the healthy beat's content must still ship"
    assert "76" in digest.text
    assert check_provenance(trace.path).ok


def test_the_failed_beat_appears_in_the_trace_with_its_error(tmp_path: Path) -> None:
    _, _, trace, _ = _run_pipeline(
        tmp_path, [MLB_500, *WX_OK], [AstrosBeat(), WeatherBeat()], "traced-failure"
    )

    records = read_trace(trace.path)
    errored = [r for r in records_of(records, "observation") if r.get("error")]
    assert errored, "the failure must be in the trace, not swallowed"
    assert any("500" in record["error"] for record in errored)

    unavailable = [
        r for r in records_of(records, "decision") if r["decision"] == "beat_unavailable"
    ]
    assert unavailable and unavailable[0]["beat"] == "astros"
    assert "rather than substituting" in unavailable[0]["reason"]


def test_the_model_is_never_handed_a_gap_to_fill(tmp_path: Path) -> None:
    _, _, _, agent = _run_pipeline(
        tmp_path, [MLB_500, *WX_OK], [AstrosBeat(), WeatherBeat()], "no-gap"
    )

    structured = agent.calls[0].structured
    assert structured is not None
    # The unavailability line is handed over pre-written; nothing asks for a substitute.
    assert any("Couldn't reach astros" in line for line in structured["unavailable"])
    assert all("astros" not in line.lower() for line in structured["lines"])

    # The system prompt forbids filling a gap; it never invites one.
    system = (agent.calls[0].system or "").lower()
    assert "never add, change, round, estimate, or infer" in system
    assert "do not fill the gap" in system


# --------------------------------------------------------------------------- #
# The wrapper itself
# --------------------------------------------------------------------------- #


def test_an_unexpected_exception_becomes_unavailable_rather_than_crashing(
    tmp_path: Path,
) -> None:
    class ExplodingBeat:
        name = "exploding"

        def should_run(self, context) -> bool:
            return True

        def run(self, context):
            raise ZeroDivisionError("a bug, not an outage")

    trace = trace_in(tmp_path, "bug-run")
    with trace:
        context = make_context(trace=trace, http_client=None)
        result = run_beat_safely(ExplodingBeat(), context)

    assert isinstance(result, BeatResult)
    assert result.available is False
    assert "ZeroDivisionError" in (result.error or "")
    assert "a bug, not an outage" in (result.error or "")
    assert result.checkable_fields == {}


def test_a_healthy_beat_passes_through_the_wrapper_unchanged(tmp_path: Path) -> None:
    client, _ = fixture_client(WX_OK)
    trace = trace_in(tmp_path, "healthy")
    with client, trace:
        context = make_context(trace=trace, http_client=client)
        wrapped = run_beat_safely(WeatherBeat(), context)

    assert wrapped.available is True
    assert wrapped.checkable_fields["run_window_low_f"] == 76


def test_a_failed_beat_that_the_model_omitted_is_appended_anyway(
    tmp_path: Path,
) -> None:
    """A failed beat never silently drops out, even if the composer ignores it."""

    class SilentClient(FakeAgentClient):
        def complete(self, prompt, **kwargs):
            response = super().complete(prompt, **kwargs)
            return type(response)(text="Weather looks fine.", input_tokens=0, output_tokens=0)

    client, _ = fixture_client([MLB_500, *WX_OK])
    trace = trace_in(tmp_path, "silent-composer")
    with client, trace:
        context = make_context(trace=trace, http_client=client)
        results = [run_beat_safely(AstrosBeat(), context), run_beat_safely(WeatherBeat(), context)]
        for result in results:
            trace.beat_result(result)
        digest = synthesize(results, CONFIG, PREFS, trace, agent_client=SilentClient())

    assert "Couldn't reach astros tonight" in digest.text
    assert check_provenance(trace.path).ok


def test_no_retry_with_silent_fallback_and_no_cached_substitute(tmp_path: Path) -> None:
    """One failing call is one failure — not a quiet second attempt or yesterday's value."""
    client, recorder = fixture_client([MLB_500])
    trace = trace_in(tmp_path, "no-retry")
    with client, trace:
        context = make_context(trace=trace, http_client=client)
        result = run_beat_safely(AstrosBeat(), context)

    assert result.available is False
    assert len(recorder.requests) == 1, "no hidden retry"
    assert result.items == []

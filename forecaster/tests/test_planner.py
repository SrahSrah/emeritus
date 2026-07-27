"""Step 8 — the planner emits a plan and makes exactly zero tool calls."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from forecaster.agent import FakeAgentClient
from forecaster.beats.base import BeatContext, BeatResult
from forecaster.config import parse_config
from forecaster.memory.preferences import parse_preferences
from forecaster.memory.scratchpad import Scratchpad
from forecaster.planner import GENERIC_CRITERION, PlanEntry, RunPlan, plan_run
from forecaster.trace import Trace, read_trace, records_of

NOW = datetime(2026, 7, 27, 19, 0)

BASE = {
    "run": {
        "send_time": "19:00",
        "timezone": "America/Chicago",
        "run_window_start": "05:00",
        "run_window_end": "08:00",
    },
    "beats": {"alpha": True, "beta": True},
    "location": {
        "city": "Austin",
        "state": "TX",
        "latitude": 30.2672,
        "longitude": -97.7431,
        "timezone": "America/Chicago",
    },
    "delivery": {"kind": "fake", "target": "nobody@example.test"},
    "escalation": {
        "rules": ["freeze_alert"],
        "freeze_threshold_f": 32.0,
        "freeze_horizon_days": 1,
        "watched_players": [],
    },
    "team": {"mlb_team_id": 117, "name": "Astros"},
}


class CountingAdapter:
    def __init__(self) -> None:
        self.call_count = 0

    def fetch(self, **kwargs: object) -> dict[str, object]:
        self.call_count += 1
        return {}


class AlphaBeat:
    name = "alpha"
    completion_criterion = "alpha reported last night's result"

    def __init__(self, adapter: CountingAdapter | None = None, runs: bool = True) -> None:
        self.adapter = adapter
        self.runs = runs

    def should_run(self, context: BeatContext) -> bool:
        return self.runs

    def run(self, context: BeatContext) -> BeatResult:  # pragma: no cover - never called
        raise AssertionError("the planner must not run a beat")


class BetaBeat(AlphaBeat):
    name = "beta"
    completion_criterion = None  # falls back to the generic contract


def _config(beats: dict[str, bool]) -> object:
    return parse_config({**BASE, "beats": beats})


def _prefs(topics: dict[str, float] | None = None) -> object:
    return parse_preferences({"topics": topics or {}})


def test_plan_names_both_beats_with_a_criterion_each() -> None:
    plan = plan_run(
        _config({"alpha": True, "beta": True}),
        _prefs(),
        NOW,
        beats=[AlphaBeat(), BetaBeat()],
    )

    assert isinstance(plan, RunPlan)
    assert sorted(plan.beat_names) == ["alpha", "beta"]
    assert all(entry.criterion.strip() for entry in plan.entries)
    assert plan.criterion_for("alpha") == "alpha reported last night's result"
    assert plan.criterion_for("beta") == GENERIC_CRITERION


def test_disabling_a_beat_in_config_removes_it_from_the_plan() -> None:
    """`get_beats` is config-driven, so the plan is too."""
    from forecaster.beats.base import register_beat, unregister_beat

    register_beat(AlphaBeat)
    register_beat(BetaBeat)
    try:
        both = plan_run(_config({"alpha": True, "beta": True}), _prefs(), NOW)
        one = plan_run(_config({"alpha": True, "beta": False}), _prefs(), NOW)
    finally:
        unregister_beat("alpha")
        unregister_beat("beta")

    assert sorted(both.beat_names) == ["alpha", "beta"]
    assert one.beat_names == ["alpha"]


def test_should_run_false_skips_the_beat_with_a_recorded_reason() -> None:
    plan = plan_run(
        _config({"alpha": True, "beta": True}),
        _prefs(),
        NOW,
        beats=[AlphaBeat(), BetaBeat(runs=False)],
    )

    assert plan.beat_names == ["alpha"]
    assert "beta" in plan.skipped
    assert "should_run" in plan.skipped["beta"]


def test_a_zero_preference_weight_skips_the_beat() -> None:
    plan = plan_run(
        _config({"alpha": True, "beta": True}),
        _prefs({"beta": 0.0}),
        NOW,
        beats=[AlphaBeat(), BetaBeat()],
    )

    assert plan.beat_names == ["alpha"]
    assert "preference weight" in plan.skipped["beta"]


def test_higher_weighted_topics_are_planned_first() -> None:
    plan = plan_run(
        _config({"alpha": True, "beta": True}),
        _prefs({"alpha": 1.0, "beta": 5.0}),
        NOW,
        beats=[AlphaBeat(), BetaBeat()],
    )

    assert plan.beat_names == ["beta", "alpha"]


def test_the_planner_makes_zero_tool_calls_and_zero_model_calls() -> None:
    """FR-7's acceptance: the planner plans; it does not research."""
    adapter = CountingAdapter()
    agent = FakeAgentClient()
    scratchpad = Scratchpad()

    plan = plan_run(
        _config({"alpha": True, "beta": True}),
        _prefs(),
        NOW,
        scratchpad=scratchpad,
        beats=[AlphaBeat(adapter), BetaBeat(adapter)],
    )

    assert plan.entries
    assert adapter.call_count == 0
    assert agent.call_count == 0
    assert scratchpad.call_count == 0
    assert scratchpad.searches == []


def test_the_plan_lands_in_the_trace_one_entry_per_beat(tmp_path: Path) -> None:
    with Trace("plan-run", directory=tmp_path) as trace:
        plan_run(
            _config({"alpha": True, "beta": True}),
            _prefs(),
            NOW,
            trace=trace,
            beats=[AlphaBeat(), BetaBeat(runs=False)],
        )

    records = read_trace(trace.path)
    plan_record = next(records_of(records, "plan"))
    assert [entry["beat"] for entry in plan_record["beats"]] == ["alpha"]
    assert plan_record["beats"][0]["criterion"]

    skips = [r for r in records_of(records, "decision") if r["decision"] == "beat_skipped"]
    assert [record["beat"] for record in skips] == ["beta"]


def test_plan_records_the_date_and_day_of_week() -> None:
    plan = plan_run(_config({"alpha": True}), _prefs(), NOW, beats=[AlphaBeat()])
    assert plan.date == "2026-07-27"
    assert plan.day_of_week == "Monday"


def test_planner_does_not_import_a_concrete_beat() -> None:
    source = (
        Path(__file__).resolve().parent.parent / "forecaster" / "planner.py"
    ).read_text(encoding="utf-8")
    offenders = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
        and ("beats.astros" in line or "beats.weather" in line)
    ]
    assert offenders == []


def test_plan_entry_serializes_for_the_trace() -> None:
    entry = PlanEntry(beat="alpha", criterion="done when reported", weight=2.0)
    assert entry.as_record() == {
        "beat": "alpha",
        "criterion": "done when reported",
        "weight": 2.0,
    }

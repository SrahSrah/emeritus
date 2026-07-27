"""Shared builders for beat/pipeline tests. Not a test module."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from forecaster.beats.base import BeatContext
from forecaster.config import Config, parse_config
from forecaster.memory.preferences import Preferences, parse_preferences
from forecaster.memory.scratchpad import Scratchpad
from forecaster.trace import Trace

#: 7 pm CT on the evening the fixtures were captured, so "next morning" is 2026-07-28.
NOW = datetime(2026, 7, 27, 19, 0)

BASE_CONFIG: dict[str, Any] = {
    "run": {
        "send_time": "19:00",
        "timezone": "America/Chicago",
        "run_window_start": "05:00",
        "run_window_end": "08:00",
    },
    "beats": {"astros": True, "weather": True},
    "location": {
        "city": "Austin",
        "state": "TX",
        "latitude": 30.2672,
        "longitude": -97.7431,
        "timezone": "America/Chicago",
    },
    "delivery": {"kind": "fake", "target": "nobody@example.test"},
    "escalation": {
        "rules": ["freeze_alert", "watched_player_injury"],
        "freeze_threshold_f": 32.0,
        "freeze_horizon_days": 1,
        "watched_players": ["Yordan Alvarez"],
    },
    "team": {"mlb_team_id": 117, "name": "Houston Astros"},
}


def make_config(**overrides: Any) -> Config:
    """Deep-ish merge of section overrides onto the base config."""
    data = {section: dict(values) for section, values in BASE_CONFIG.items()}
    for section, values in overrides.items():
        if isinstance(values, dict) and section in data:
            data[section].update(values)
        else:
            data[section] = values
    return parse_config(data)


def make_preferences(**overrides: Any) -> Preferences:
    data: dict[str, Any] = {"topics": {"astros": 1.0, "weather": 1.0}}
    data.update(overrides)
    return parse_preferences(data)


def make_context(
    *,
    trace: Trace,
    http_client: Any,
    config: Config | None = None,
    preferences: Preferences | None = None,
    now: datetime = NOW,
    scratchpad: Scratchpad | None = None,
) -> BeatContext:
    return BeatContext(
        config=config or make_config(),
        preferences=preferences or make_preferences(),
        now=now,
        scratchpad=scratchpad if scratchpad is not None else Scratchpad(trace=trace),
        trace=trace,
        http_client=http_client,
    )


SCHEDULE_URL = r"statsapi\.mlb\.com/api/v1/schedule"
POINTS_URL = r"api\.weather\.gov/points/"
HOURLY_URL = r"api\.weather\.gov/gridpoints/"


def trace_in(tmp_path: Path, run_id: str = "beat-run") -> Trace:
    return Trace(run_id, directory=tmp_path)

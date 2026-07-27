"""Step 3 — config loads, config alone decides which beats run, bad config fails loud."""

from __future__ import annotations

from datetime import time
from pathlib import Path

import pytest

from forecaster.config import (
    Config,
    ConfigError,
    config_digest,
    enabled_beats,
    load_config,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_CONFIG = PROJECT_ROOT / "config.toml"

TWO_BEATS = """
[run]
send_time = "19:00"
timezone = "America/Chicago"
run_window_start = "05:00"
run_window_end = "08:00"

[beats]
astros = true
weather = true

[location]
city = "Austin"
state = "TX"
latitude = 30.2672
longitude = -97.7431
timezone = "America/Chicago"

[delivery]
kind = "fake"
target = "nobody@example.test"

[escalation]
rules = ["freeze_alert", "watched_player_injury"]
freeze_threshold_f = 32.0
freeze_horizon_days = 1
watched_players = ["Yordan Alvarez"]

[team]
mlb_team_id = 117
name = "Astros"
"""

ONE_BEAT = TWO_BEATS.replace("weather = true", "weather = false")


def _write(tmp_path: Path, name: str, body: str) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_real_config_loads_with_the_expected_typed_fields() -> None:
    config = load_config(REAL_CONFIG)

    assert isinstance(config, Config)
    assert config.run.send_time == time(19, 0)
    assert config.run.timezone == "America/Chicago"
    assert config.run.run_window_start == time(5, 0)
    assert config.run.run_window_end == time(8, 0)

    assert config.location.city == "Austin"
    assert config.location.latitude == pytest.approx(30.2672)
    assert config.location.longitude == pytest.approx(-97.7431)

    assert config.team.mlb_team_id == 117
    assert config.escalation.freeze_threshold_f == pytest.approx(32.0)
    assert config.escalation.rules == ["freeze_alert", "watched_player_injury"]
    assert "Yordan Alvarez" in config.escalation.watched_players
    assert config.delivery.target


def test_enabled_beats_differs_by_config_alone(tmp_path: Path) -> None:
    """FR-1's structural half: the beat set is a function of the file, nothing else."""
    both = load_config(_write(tmp_path, "both.toml", TWO_BEATS))
    one = load_config(_write(tmp_path, "one.toml", ONE_BEAT))

    assert enabled_beats(both) == ["astros", "weather"]
    assert enabled_beats(one) == ["astros"]
    assert enabled_beats(both) != enabled_beats(one)


def test_malformed_toml_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "bad.toml", "[run\nsend_time = ")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(path)


def test_missing_section_raises_naming_the_section(tmp_path: Path) -> None:
    body = TWO_BEATS.replace('[team]\nmlb_team_id = 117\nname = "Astros"\n', "")
    path = _write(tmp_path, "no_team.toml", body)
    with pytest.raises(ConfigError, match=r"\[team\]"):
        load_config(path)


def test_missing_key_raises_naming_the_key(tmp_path: Path) -> None:
    body = TWO_BEATS.replace("freeze_threshold_f = 32.0\n", "")
    path = _write(tmp_path, "no_threshold.toml", body)
    with pytest.raises(ConfigError, match="freeze_threshold_f"):
        load_config(path)


def test_wrong_type_raises_rather_than_coercing(tmp_path: Path) -> None:
    body = TWO_BEATS.replace("astros = true", 'astros = "yes"')
    path = _write(tmp_path, "bad_beat.toml", body)
    with pytest.raises(ConfigError, match="true or false"):
        load_config(path)


def test_missing_file_raises() -> None:
    with pytest.raises(ConfigError, match="No config file"):
        load_config(PROJECT_ROOT / "definitely-not-here.toml")


def test_config_digest_is_stable_and_content_sensitive(tmp_path: Path) -> None:
    both = load_config(_write(tmp_path, "a.toml", TWO_BEATS))
    same = load_config(_write(tmp_path, "b.toml", TWO_BEATS))
    other = load_config(_write(tmp_path, "c.toml", ONE_BEAT))

    assert config_digest(both) == config_digest(same)
    assert config_digest(both) != config_digest(other)


def test_no_module_but_config_hardcodes_the_location_or_timezone() -> None:
    """The PowerShell verify, as a test: only config.py may name the place."""
    package = PROJECT_ROOT / "forecaster"
    offenders: list[str] = []
    for path in package.rglob("*.py"):
        if path.name == "config.py":
            continue
        text = path.read_text(encoding="utf-8")
        for needle in ("Austin", "America/Chicago", "EWX"):
            if needle in text:
                offenders.append(f"{path.relative_to(PROJECT_ROOT)}: {needle}")
    assert offenders == []

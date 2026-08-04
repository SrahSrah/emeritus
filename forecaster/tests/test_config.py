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

[retrieval]
enabled = false
model = "test-hashing-embedder"
k = 5
similarity_floor = 0.60
window_days = 14
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


# --------------------------------------------------------------------------- #
# Step 24 — the news section
# --------------------------------------------------------------------------- #


def _news_config(**overrides: object) -> Config:
    """Parse a base config with `[news]` merged in, applying section overrides."""
    from tests.helpers import NEWS_CONFIG, make_config

    news = {key: value for key, value in NEWS_CONFIG.items()}
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(news.get(key), dict):
            news[key] = {**news[key], **value}
        else:
            news[key] = value
    return make_config(news=news)


def test_the_real_config_parses_its_news_section() -> None:
    config = load_config(REAL_CONFIG)
    assert config.news is not None
    assert config.news.chunking.target_chars == 900
    assert config.news.corpus.ttl_days == 7
    assert config.news.retrieval.k == 6
    assert config.news.retrieval.similarity_floor == 0.35
    assert [feed.name for feed in config.news.feeds][0] == "Ars Technica"
    assert [topic.id for topic in config.news.topics] == ["claude", "agents", "evals"]


def test_the_news_beat_ships_disabled_until_it_is_registered() -> None:
    """Enabling a beat nobody registered is a LookupError; Step 32 flips this."""
    config = load_config(REAL_CONFIG)
    assert config.beats["news"] is False
    assert "news" not in enabled_beats(config)


def test_a_config_with_no_news_section_is_still_valid() -> None:
    """Every config that predates the news beat is still a config."""
    from tests.helpers import make_config

    assert make_config().news is None


def test_enabling_news_without_a_news_section_raises() -> None:
    from tests.helpers import make_config

    with pytest.raises(ConfigError, match=r"no \[news\] section"):
        make_config(beats={"news": True})


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"chunking": {"overlap_chars": 900}}, "less than target_chars"),
        ({"chunking": {"overlap_chars": -1}}, "must not be negative"),
        ({"chunking": {"target_chars": 2000}}, "must not exceed max_chars"),
        ({"retrieval": {"k": 0}}, r"\[news.retrieval\].k must be at least 1"),
        ({"retrieval": {"similarity_floor": 1.5}}, "within 0.0"),
        ({"retrieval": {"window_days": 0}}, "window_days must be at least 1"),
        ({"retrieval": {"max_chunks_per_article": 0}}, "max_chunks_per_article"),
        ({"corpus": {"ttl_days": 0}}, "ttl_days must be at least 1"),
        ({"retrieval": {"window_days": 30}}, "exceeds"),
        ({"user_agent": ""}, "non-empty string"),
    ],
)
def test_each_news_validation_rule_has_a_raising_case(overrides, message) -> None:
    """A config that would silently misbehave at 2 am fails here instead."""
    with pytest.raises(ConfigError, match=message):
        _news_config(**overrides)


def test_a_window_wider_than_the_ttl_is_rejected() -> None:
    """Retrieving over articles the purge already deleted is a config bug, not a quirk."""
    with pytest.raises(ConfigError, match="already deleted"):
        _news_config(retrieval={"window_days": 8})


def test_duplicate_feed_names_and_topic_ids_are_rejected() -> None:
    """A duplicate makes a trace entry ambiguous — same reasoning as suppression ids."""
    with pytest.raises(ConfigError, match="duplicate name"):
        _news_config(
            feeds=[
                {"name": "Ars Technica", "url": "https://a.test/feed"},
                {"name": "Ars Technica", "url": "https://b.test/feed"},
            ]
        )
    with pytest.raises(ConfigError, match="duplicate id"):
        _news_config(
            topics=[
                {"id": "claude", "query": "one"},
                {"id": "claude", "query": "two"},
            ]
        )


def test_enabling_news_with_no_feeds_or_no_topics_raises() -> None:
    from tests.helpers import NEWS_CONFIG, make_config

    with pytest.raises(ConfigError, match="nothing to read"):
        make_config(beats={"news": True}, news={**NEWS_CONFIG, "feeds": []})
    with pytest.raises(ConfigError, match="retrieval has no query"):
        make_config(beats={"news": True}, news={**NEWS_CONFIG, "topics": []})


def test_news_retrieval_is_a_separate_setting_from_ledger_retrieval() -> None:
    """Q5 and Q6 are siblings. Conflating the two sets would answer one with the other."""
    config = load_config(REAL_CONFIG)
    assert config.news is not None
    assert config.retrieval.k != config.news.retrieval.k
    assert config.retrieval.similarity_floor != config.news.retrieval.similarity_floor
    assert config.retrieval.window_days != config.news.retrieval.window_days

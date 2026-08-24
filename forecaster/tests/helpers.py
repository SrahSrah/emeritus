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
    # Off by default so every pre-FR-9b test keeps asserting exactly the v1 behaviour.
    # The retrieval tests opt in with make_config(retrieval={"enabled": True}).
    "retrieval": {
        "enabled": False,
        "model": "test-hashing-embedder",
        "k": 5,
        "similarity_floor": 0.60,
        "window_days": 14,
    },
}


#: Opt-in news settings, mirroring how `retrieval` stays off by default. A test that
#: needs the news beat passes `make_config(beats={"news": True}, news=NEWS_CONFIG)`.
#: Deliberately small — two feeds, two topics — so a fixture set stays readable.
NEWS_CONFIG: dict[str, Any] = {
    "user_agent": "forecaster-test/0.1 (tests@example.test)",
    "fetch_delay_seconds": 0.0,
    "timeout_seconds": 5,
    "min_body_chars": 600,
    "feeds": [
        {"name": "Ars Technica", "url": "https://feeds.arstechnica.test/index"},
        {"name": "The Verge", "url": "https://www.theverge.test/rss/index.xml"},
    ],
    "chunking": {"target_chars": 900, "max_chars": 1200, "overlap_chars": 150},
    "corpus": {"path": "data/corpus.db", "ttl_days": 7},
    "retrieval": {
        "k": 6,
        "similarity_floor": 0.35,
        "window_days": 3,
        "max_chunks_per_article": 2,
    },
    "topics": [
        {"id": "claude", "query": "Anthropic Claude model releases and pricing"},
        {"id": "agents", "query": "AI agents, tool use, and agent frameworks"},
    ],
}


#: Opt-in need-to-know settings, mirroring NEWS_CONFIG's role. A test that needs the
#: beat passes `make_config(beats={"need_to_know": True}, need_to_know=NEED_TO_KNOW_CONFIG)`.
#: Two feeds keeps fixture sets readable; the corpus path deliberately matches
#: NEWS_CONFIG's so the shared-file default is what tests exercise unless they override.
NEED_TO_KNOW_CONFIG: dict[str, Any] = {
    "user_agent": "forecaster-test/0.1 (tests@example.test)",
    "fetch_delay_seconds": 0.0,
    "timeout_seconds": 5,
    "min_body_chars": 600,
    "feeds": [
        {"name": "BBC World", "url": "https://feeds.bbci.test/news/world/rss.xml"},
        {"name": "Texas Tribune", "url": "https://feeds.texastribune.test/feeds/main/"},
    ],
    "chunking": {"target_chars": 900, "max_chars": 1200, "overlap_chars": 150},
    "corpus": {"path": "data/corpus.db", "ttl_days": 7},
    "corroboration": {"window_days": 2, "floor": 0.55, "min_sources": 2},
    # v5: required blocks. Test values, deliberately small; matching is case-insensitive.
    # Terms chosen to be ABSENT from the captured real feeds (the TT capture mentions
    # ERCOT), so v4-era fixture runs stay watchlist-quiet unless a test opts in.
    "watchlist": {"terms": ["boil notice", "wildfire evacuation"]},
    "bar": {
        "deliver": ["local safety", "world emergencies"],
        "exclude": ["election outcomes"],
    },
}


#: Opt-in venue settings, mirroring the other beat-config dicts. A test that needs the
#: beat passes `make_config(beats={"venues": True}, venues=VENUES_CONFIG)`. The dedup
#: exemption is NOT included here — tests opt into it explicitly via
#: `retrieval={"exempt_beats": ["venues"]}` so the un-exempt path stays testable.
VENUES_CONFIG: dict[str, Any] = {
    "user_agent": "forecaster-test/0.1 (tests@example.test)",
    "timeout_seconds": 5,
    "window_days": 14,
    "venues": [
        {"name": "ZACH Theatre", "kind": "zach_shows", "url": "https://www.zachtheater.test/tickets/shows/"},
    ],
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
    embedder: Any = None,
    corpus: Any = None,
    agent_client: Any = None,
) -> BeatContext:
    """The last three are only used by a document-shaped beat (FR-23/24/25)."""
    return BeatContext(
        config=config or make_config(),
        preferences=preferences or make_preferences(),
        now=now,
        scratchpad=scratchpad if scratchpad is not None else Scratchpad(trace=trace),
        trace=trace,
        http_client=http_client,
        embedder=embedder,
        corpus=corpus,
        agent_client=agent_client,
    )


def make_retriever(tmp_path: Path, **overrides: Any) -> Any:
    """A `LedgerRetriever` over a temp ledger, using the offline hashing embedder."""
    from forecaster.memory.ledger import connect
    from forecaster.memory.retrieval import HashingEmbedder, LedgerRetriever

    settings: dict[str, Any] = {"k": 5, "similarity_floor": 0.60, "window_days": 14}
    settings.update(overrides)
    return LedgerRetriever(
        connection=connect(tmp_path / "ledger.db"),
        embedder=HashingEmbedder(),
        **settings,
    )


SCHEDULE_URL = r"statsapi\.mlb\.com/api/v1/schedule"
POINTS_URL = r"api\.weather\.gov/points/"
HOURLY_URL = r"api\.weather\.gov/gridpoints/"


def trace_in(tmp_path: Path, run_id: str = "beat-run") -> Trace:
    return Trace(run_id, directory=tmp_path)

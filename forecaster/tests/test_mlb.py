"""Step 9 — the MLB adapter, entirely off recorded fixtures."""

from __future__ import annotations

import httpx
import pytest

from forecaster.tools.mlb import (
    STATE_FINAL,
    STATE_LIVE,
    AdapterError,
    Game,
    fetch_schedule,
    parse_schedule,
)
from tests.conftest import Route, fixture_client, load_fixture

TZ = "America/Chicago"
SCHEDULE = r"statsapi\.mlb\.com/api/v1/schedule"


def _client(fixture: str) -> tuple[httpx.Client, object]:
    return fixture_client([Route(SCHEDULE, fixture=fixture)])


# --------------------------------------------------------------------------- #
# FR-3's acceptance criterion
# --------------------------------------------------------------------------- #


def test_doubleheader_fixture_returns_the_right_count_states_and_local_times() -> None:
    client, recorder = _client("mlb_doubleheader")
    with client:
        games = fetch_schedule(117, "2026-04-30", client=client, tz_name=TZ)

    assert len(games) == 2, "a doubleheader is two games, not one"
    assert all(isinstance(game, Game) for game in games)
    assert all(game.is_doubleheader for game in games)
    assert sorted(game.game_number for game in games) == [1, 2]
    assert {game.abstract_game_state for game in games} == {STATE_FINAL}

    for game in games:
        assert game.start_time_utc.utcoffset().total_seconds() == 0
        assert str(game.start_time_local.tzinfo) == TZ
        # Same instant, different wall clock — that's the whole point of localizing.
        assert game.start_time_local.timestamp() == game.start_time_utc.timestamp()
        assert game.start_time_local.utcoffset() != game.start_time_utc.utcoffset()

    assert len(recorder.requests) == 1


def test_in_progress_fixture_exposes_the_live_score() -> None:
    client, _ = _client("mlb_in_progress")
    with client:
        games = fetch_schedule(117, "2026-07-26", client=client, tz_name=TZ)

    assert len(games) == 1
    game = games[0]
    assert game.is_live
    assert game.abstract_game_state == STATE_LIVE
    assert game.detailed_state == "In Progress"
    assert game.away_score == 2
    assert game.home_score == 1
    assert game.score_line() == "Houston Astros 2, Chicago White Sox 1"


def test_final_fixture_carries_the_completed_score() -> None:
    client, _ = _client("mlb_final")
    with client:
        games = fetch_schedule(117, "2026-07-26", client=client, tz_name=TZ)

    game = games[0]
    assert game.is_final
    assert game.score_line() == "Houston Astros 3, Chicago White Sox 12"
    assert game.opponent_of("Houston Astros") == "Chicago White Sox"
    assert game.game_pk == 824572


def test_no_game_fixture_returns_an_empty_list_not_an_error() -> None:
    """A real off day is information, not a failure."""
    client, _ = _client("mlb_no_game")
    with client:
        games = fetch_schedule(117, "2026-07-02", client=client, tz_name=TZ)

    assert games == []


# --------------------------------------------------------------------------- #
# Failure contract
# --------------------------------------------------------------------------- #


def test_a_500_raises_adapter_error_carrying_the_status() -> None:
    client, _ = fixture_client([Route(SCHEDULE, json_body={"detail": "boom"}, status=500)])
    with client, pytest.raises(AdapterError) as excinfo:
        fetch_schedule(117, "2026-07-26", client=client, tz_name=TZ)

    assert excinfo.value.status == 500
    assert "500" in str(excinfo.value)


def test_a_timeout_raises_adapter_error() -> None:
    client, _ = fixture_client(
        [Route(SCHEDULE, exc=httpx.ReadTimeout("too slow"))]
    )
    with client, pytest.raises(AdapterError, match="timed out"):
        fetch_schedule(117, "2026-07-26", client=client, tz_name=TZ)


def test_an_unrecognizable_payload_raises_rather_than_guessing() -> None:
    client, _ = fixture_client([Route(SCHEDULE, json_body={"unexpected": True})])
    with client, pytest.raises(AdapterError, match="no `dates` key"):
        fetch_schedule(117, "2026-07-26", client=client, tz_name=TZ)


def test_a_game_missing_its_teams_raises_rather_than_emitting_a_partial_game() -> None:
    payload = {"dates": [{"date": "2026-07-26", "games": [{"status": {}}]}]}
    with pytest.raises(AdapterError, match="missing `status` or `teams`"):
        parse_schedule(payload, tz_name=TZ)


def test_an_unparseable_start_time_raises() -> None:
    payload = load_fixture("mlb_final")
    payload["dates"][0]["games"][0]["gameDate"] = "not-a-timestamp"
    with pytest.raises(AdapterError, match="unparseable gameDate"):
        parse_schedule(payload, tz_name=TZ)


def test_an_unknown_timezone_raises() -> None:
    with pytest.raises(AdapterError, match="Unknown timezone"):
        parse_schedule(load_fixture("mlb_final"), tz_name="Mars/Olympus_Mons")


# --------------------------------------------------------------------------- #
# Range support (FR-5's "preview the next game" branch)
# --------------------------------------------------------------------------- #


def test_a_date_range_sends_start_and_end_rather_than_a_single_date() -> None:
    client, recorder = _client("mlb_final")
    with client:
        fetch_schedule(117, "2026-07-27", "2026-08-03", client=client, tz_name=TZ)

    url = str(recorder.requests[0].url)
    assert "startDate=2026-07-27" in url
    assert "endDate=2026-08-03" in url
    assert "&date=" not in url


def test_a_single_date_sends_the_date_parameter() -> None:
    client, recorder = _client("mlb_final")
    with client:
        fetch_schedule(117, "2026-07-26", client=client, tz_name=TZ)

    url = str(recorder.requests[0].url)
    assert "date=2026-07-26" in url
    assert "teamId=117" in url
    assert "sportId=1" in url

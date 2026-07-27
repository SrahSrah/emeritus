"""MLB Stats API adapter (FR-3).

Normalizes `statsapi.mlb.com`'s schedule endpoint into typed :class:`Game` objects, with
UTC start times converted to the configured local timezone.

PRD §8: this is an **undocumented public endpoint** under MLB's copyright terms. It can
change shape or rate-limit without notice, so every failure path here raises
:class:`AdapterError` rather than returning a partial or guessed `Game`. Step 15 turns
that into an unavailable `BeatResult`; nothing ever substitutes a plausible score.

Free, no key, no paid tier. Verified live 2026-07-27.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

BASE_URL = "https://statsapi.mlb.com/api/v1/schedule"
ADAPTER_NAME = "mlb.fetch_schedule"
DEFAULT_TIMEOUT = 20.0

#: `abstractGameState` values the endpoint actually returns. Note that a game in
#: progress reports **"Live"** here; "In Progress" is the `detailedState`.
STATE_PREVIEW = "Preview"
STATE_LIVE = "Live"
STATE_FINAL = "Final"


class AdapterError(RuntimeError):
    """An upstream call failed. Carries enough to say so honestly in the digest."""

    def __init__(self, message: str, *, adapter: str, status: int | None = None) -> None:
        super().__init__(message)
        self.adapter = adapter
        self.status = status


@dataclass(frozen=True)
class Game:
    """One scheduled game, normalized."""

    game_pk: int
    game_date: str
    abstract_game_state: str
    detailed_state: str
    start_time_utc: datetime
    start_time_local: datetime
    home_team: str
    away_team: str
    home_score: int | None
    away_score: int | None
    is_doubleheader: bool
    game_number: int

    @property
    def is_final(self) -> bool:
        return self.abstract_game_state == STATE_FINAL

    @property
    def is_live(self) -> bool:
        return self.abstract_game_state == STATE_LIVE

    @property
    def is_preview(self) -> bool:
        return self.abstract_game_state == STATE_PREVIEW

    def opponent_of(self, team_name: str) -> str:
        return self.away_team if self.home_team == team_name else self.home_team

    def score_line(self) -> str | None:
        """`"Astros 3, White Sox 12"` — or None when there is no score yet."""
        if self.away_score is None or self.home_score is None:
            return None
        return f"{self.away_team} {self.away_score}, {self.home_team} {self.home_score}"


def _tzinfo(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise AdapterError(
            f"Unknown timezone {name!r} from config", adapter=ADAPTER_NAME
        ) from exc


def _parse_start(raw: Any) -> datetime:
    if not isinstance(raw, str):
        raise AdapterError(
            f"schedule payload has a non-string gameDate: {raw!r}", adapter=ADAPTER_NAME
        )
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdapterError(
            f"schedule payload has an unparseable gameDate {raw!r}", adapter=ADAPTER_NAME
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _score(side: Mapping[str, Any]) -> int | None:
    value = side.get("score")
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise AdapterError(
            f"schedule payload has a non-integer score {value!r}", adapter=ADAPTER_NAME
        )
    return value


def parse_schedule(payload: Any, *, tz_name: str) -> list[Game]:
    """Normalize a schedule payload. Raises rather than guessing at anything."""
    if not isinstance(payload, Mapping):
        raise AdapterError(
            f"schedule payload is {type(payload).__name__}, expected an object",
            adapter=ADAPTER_NAME,
        )
    dates = payload.get("dates")
    if dates is None:
        raise AdapterError(
            "schedule payload has no `dates` key — the endpoint's shape may have changed",
            adapter=ADAPTER_NAME,
        )
    if not isinstance(dates, list):
        raise AdapterError("schedule payload `dates` is not a list", adapter=ADAPTER_NAME)

    local = _tzinfo(tz_name)
    games: list[Game] = []

    for day in dates:
        if not isinstance(day, Mapping):
            raise AdapterError("schedule payload has a malformed date entry", adapter=ADAPTER_NAME)
        game_date = str(day.get("date", ""))
        for raw in day.get("games", []) or []:
            if not isinstance(raw, Mapping):
                raise AdapterError(
                    "schedule payload has a malformed game entry", adapter=ADAPTER_NAME
                )
            status = raw.get("status")
            teams = raw.get("teams")
            if not isinstance(status, Mapping) or not isinstance(teams, Mapping):
                raise AdapterError(
                    "schedule payload game is missing `status` or `teams`",
                    adapter=ADAPTER_NAME,
                )
            home = teams.get("home")
            away = teams.get("away")
            if not isinstance(home, Mapping) or not isinstance(away, Mapping):
                raise AdapterError(
                    "schedule payload game is missing a home/away side", adapter=ADAPTER_NAME
                )

            start_utc = _parse_start(raw.get("gameDate"))
            games.append(
                Game(
                    game_pk=int(raw.get("gamePk", 0)),
                    game_date=game_date,
                    abstract_game_state=str(status.get("abstractGameState", "")),
                    detailed_state=str(status.get("detailedState", "")),
                    start_time_utc=start_utc,
                    start_time_local=start_utc.astimezone(local),
                    home_team=str((home.get("team") or {}).get("name", "")),
                    away_team=str((away.get("team") or {}).get("name", "")),
                    home_score=_score(home),
                    away_score=_score(away),
                    is_doubleheader=str(raw.get("doubleHeader", "N")).upper() != "N",
                    game_number=int(raw.get("gameNumber", 1)),
                )
            )

    return games


def fetch_schedule(
    team_id: int,
    start_date: str | date,
    end_date: str | date | None = None,
    *,
    client: httpx.Client,
    tz_name: str = "UTC",
    timeout: float = DEFAULT_TIMEOUT,
) -> list[Game]:
    """Fetch a team's games for a date — or a date **range**.

    FR-5's "preview the next game" branch needs a range, not a single date, which is why
    ``end_date`` exists. An empty result is an empty list, not an error: a real off day is
    information, not a failure.
    """
    start = start_date.isoformat() if isinstance(start_date, date) else str(start_date)
    params: dict[str, Any] = {"sportId": 1, "teamId": team_id}
    if end_date is None:
        params["date"] = start
    else:
        params["startDate"] = start
        params["endDate"] = (
            end_date.isoformat() if isinstance(end_date, date) else str(end_date)
        )

    try:
        response = client.get(BASE_URL, params=params, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise AdapterError(
            f"MLB Stats API timed out after {timeout}s", adapter=ADAPTER_NAME
        ) from exc
    except httpx.HTTPError as exc:
        raise AdapterError(
            f"MLB Stats API request failed: {exc}", adapter=ADAPTER_NAME
        ) from exc

    if response.status_code >= 400:
        raise AdapterError(
            f"MLB Stats API returned {response.status_code}",
            adapter=ADAPTER_NAME,
            status=response.status_code,
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise AdapterError(
            "MLB Stats API returned a body that is not JSON", adapter=ADAPTER_NAME
        ) from exc

    return parse_schedule(payload, tz_name=tz_name)


def games_on(games: Iterable[Game], day: str | date) -> list[Game]:
    """Filter to a single calendar date, by the game's own `date` field."""
    wanted = day.isoformat() if isinstance(day, date) else str(day)
    return [game for game in games if game.game_date == wanted]


__all__ = [
    "ADAPTER_NAME",
    "BASE_URL",
    "STATE_FINAL",
    "STATE_LIVE",
    "STATE_PREVIEW",
    "AdapterError",
    "Game",
    "fetch_schedule",
    "games_on",
    "parse_schedule",
]

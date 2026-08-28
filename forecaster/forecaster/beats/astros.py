"""Astros beat worker (FR-5).

A ReAct loop: call the schedule, look at what came back, decide whether that is enough or
whether a second call is needed, then stop. Three branches:

- **final, none tonight** → report the final, then look ahead and preview the next game;
- **tonight in progress** → report the last completed game *and* flag tonight live with
  its current score;
- **no game** → say so briefly.

Every call goes through the scratchpad and every decision goes into the trace with its
reason. Nothing here imports the planner, the synthesizer, or delivery — only the
protocol, the adapter, the scratchpad, and the trace (FR-2's seam).

**No injury data.** The MLB adapter returns schedule, state, score, and game ID; there is
no injury feed in v1. `escalation_signals["injuries"]` is deliberately left unpopulated —
adding a feed or scraping a roster page is new scope requiring Sarah's decision.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from forecaster.beats.base import BeatContext, BeatItem, BeatResult, ObservationRef, register_beat
from forecaster.tools import mlb

#: How far to look for the next scheduled game, and for the last completed one.
LOOKAHEAD_DAYS = 14
LOOKBACK_DAYS = 14


def _observe(
    context: BeatContext, *, arguments: dict[str, Any], call: Any
) -> tuple[list[mlb.Game], ObservationRef]:
    """Make one traced, memoized adapter call and return its games plus a citation."""
    observation_id = context.trace.tool_call(
        beat=AstrosBeat.name, adapter=mlb.ADAPTER_NAME, arguments=arguments
    )
    try:
        games = context.scratchpad.get_or_call(
            call, beat=AstrosBeat.name, adapter=mlb.ADAPTER_NAME, arguments=arguments
        )
    except mlb.AdapterError as exc:
        context.trace.observation(observation_id, error=str(exc))
        raise
    context.trace.observation(
        observation_id, payload=[_game_payload(game) for game in games]
    )
    return games, ObservationRef(observation_id, mlb.ADAPTER_NAME)


def _game_payload(game: mlb.Game) -> dict[str, Any]:
    """What the observation records. Everything a later claim could be checked against."""
    return {
        "game_pk": game.game_pk,
        "game_date": game.game_date,
        "abstract_game_state": game.abstract_game_state,
        "detailed_state": game.detailed_state,
        "start_time_utc": game.start_time_utc.isoformat(),
        "home_team": game.home_team,
        "away_team": game.away_team,
        "home_score": game.home_score,
        "away_score": game.away_score,
        "is_doubleheader": game.is_doubleheader,
        "game_number": game.game_number,
    }


def _local(game: mlb.Game) -> str:
    """Local start time as prose. Deliberately *not* a checkable field.

    FR-11 scopes checkable values to scores, game state, and the weather numbers, and
    calls dates and times prose. A localized rendering is derived rather than observed —
    the observed value is the UTC timestamp, which is what the beat declares.
    """
    return game.start_time_local.strftime("%I:%M %p").lstrip("0")


@register_beat
class AstrosBeat:
    """`name = "astros"`. One class; the only other cost is a `config.toml` entry."""

    name = "astros"
    completion_criterion = (
        "tonight's game state reported, with either a final score, a live score, or an "
        "explicit 'no game', and the next game previewed when there is one"
    )

    def should_run(self, context: BeatContext) -> bool:
        return bool(context.config.beats.get(self.name, False))

    # -- the loop ----------------------------------------------------------- #

    def run(self, context: BeatContext) -> BeatResult:
        team_id = context.config.team.mlb_team_id
        team_name = context.config.team.name
        tz_name = context.config.location.timezone
        today: date = context.now.date()
        client = context.http_client

        def fetch(start: date, end: date | None = None):
            return lambda: mlb.fetch_schedule(
                team_id, start, end, client=client, tz_name=tz_name
            )

        today_args = {"team_id": team_id, "date": today.isoformat()}
        today_games, today_ref = _observe(
            context, arguments=today_args, call=fetch(today)
        )

        live = [game for game in today_games if game.is_live]
        finals = [game for game in today_games if game.is_final]
        upcoming = [game for game in today_games if game.is_preview]

        if live:
            return self._live_branch(context, live, today, team_id, team_name, tz_name, today_ref)
        if finals:
            return self._final_branch(
                context, finals, today, team_id, team_name, tz_name, today_ref
            )
        if upcoming:
            return self._preview_tonight_branch(context, upcoming, team_name, today_ref)
        return self._no_game_branch(context, today, team_name, today_ref)

    # -- branches ----------------------------------------------------------- #

    def _live_branch(
        self,
        context: BeatContext,
        live: list[mlb.Game],
        today: date,
        team_id: int,
        team_name: str,
        tz_name: str,
        today_ref: ObservationRef,
    ) -> BeatResult:
        game = live[0]
        context.trace.decision(
            beat=self.name,
            decision="tonight_in_progress",
            reason=(
                f"today's game {game.game_pk} is {game.abstract_game_state!r} "
                f"({game.detailed_state!r}); one call is not enough — the last completed "
                "game is still worth reporting"
            ),
        )

        window_start = today - timedelta(days=LOOKBACK_DAYS)
        window_end = today - timedelta(days=1)
        args = {
            "team_id": team_id,
            "start_date": window_start.isoformat(),
            "end_date": window_end.isoformat(),
        }
        previous_games, previous_ref = _observe(
            context,
            arguments=args,
            call=lambda: mlb.fetch_schedule(
                team_id,
                window_start,
                window_end,
                client=context.http_client,
                tz_name=tz_name,
            ),
        )
        completed = [game_ for game_ in previous_games if game_.is_final]
        last = completed[-1] if completed else None

        live_line = game.score_line() or "no score yet"
        items = [
            BeatItem(
                beat=self.name,
                text=f"Live now: {live_line}.",
                fields={
                    "state": game.abstract_game_state,
                    "detailed_state": game.detailed_state,
                    "away_score": game.away_score,
                    "home_score": game.home_score,
                    "start_time_local": _local(game),
                    # FR-19: what day this is about. Without it two different games
                    # sharing a scoreline look identical to the dedup rule.
                    "game_date": game.game_date,
                },
                observations=[today_ref],
            )
        ]
        checkable: dict[str, Any] = {
            "live_score": live_line,
            "live_game_state": game.detailed_state,
            "opponent": game.opponent_of(team_name),
            "start_time_utc": game.start_time_utc.isoformat(),
        }
        observations = [today_ref]

        if last is not None:
            last_line = last.score_line() or "no score recorded"
            items.append(
                BeatItem(
                    beat=self.name,
                    text=f"Last completed: {last_line}.",
                    fields={"state": last.abstract_game_state, "game_date": last.game_date},
                    observations=[previous_ref],
                )
            )
            checkable["last_completed_score"] = last_line
            checkable["last_completed_state"] = last.abstract_game_state
            observations.append(previous_ref)
        else:
            context.scratchpad.note_missing(
                self.name, f"no completed game in the {LOOKBACK_DAYS} days before {today}"
            )

        context.trace.decision(
            beat=self.name,
            decision="enough_information",
            reason="live score and last completed game both in hand; stopping",
        )
        return BeatResult(
            beat=self.name,
            items=items,
            checkable_fields=checkable,
            escalation_signals={},
            observations=observations,
        )

    def _final_branch(
        self,
        context: BeatContext,
        finals: list[mlb.Game],
        today: date,
        team_id: int,
        team_name: str,
        tz_name: str,
        today_ref: ObservationRef,
    ) -> BeatResult:
        game = finals[-1]
        context.trace.decision(
            beat=self.name,
            decision="report_final",
            reason=(
                f"today's game {game.game_pk} is Final and nothing is live; the next game "
                "is not in today's payload, so a second call is needed to preview it"
            ),
        )

        score_line = game.score_line() or "no score recorded"
        items = [
            BeatItem(
                beat=self.name,
                text=f"Final: {score_line}.",
                fields={
                    "state": game.abstract_game_state,
                    "away_score": game.away_score,
                    "home_score": game.home_score,
                    "doubleheader": game.is_doubleheader,
                    # FR-19: see the live branch. A 4-2 win on the 3rd and a 4-2 win
                    # on the 9th are different games, and only the date says so.
                    "game_date": game.game_date,
                },
                observations=[today_ref],
            )
        ]
        checkable: dict[str, Any] = {
            "final_score": score_line,
            "game_state": game.abstract_game_state,
            "opponent": game.opponent_of(team_name),
            "start_time_utc": game.start_time_utc.isoformat(),
        }
        observations = [today_ref]

        window_start = today + timedelta(days=1)
        window_end = today + timedelta(days=LOOKAHEAD_DAYS)
        args = {
            "team_id": team_id,
            "start_date": window_start.isoformat(),
            "end_date": window_end.isoformat(),
        }
        next_games, next_ref = _observe(
            context,
            arguments=args,
            call=lambda: mlb.fetch_schedule(
                team_id,
                window_start,
                window_end,
                client=context.http_client,
                tz_name=tz_name,
            ),
        )
        upcoming = [g for g in next_games if g.is_preview]
        if upcoming:
            nxt = upcoming[0]
            items.append(
                BeatItem(
                    beat=self.name,
                    text=(
                        f"Next: {nxt.away_team} at {nxt.home_team} on {nxt.game_date}, "
                        f"first pitch {_local(nxt)} local."
                    ),
                    fields={
                        "opponent": nxt.opponent_of(team_name),
                        "game_date": nxt.game_date,
                        "start_time_local": _local(nxt),
                    },
                    observations=[next_ref],
                )
            )
            checkable["next_opponent"] = nxt.opponent_of(team_name)
            checkable["next_start_time_utc"] = nxt.start_time_utc.isoformat()
            observations.append(next_ref)
        else:
            context.scratchpad.note_missing(
                self.name, f"no scheduled game in the next {LOOKAHEAD_DAYS} days"
            )
            items.append(
                BeatItem(
                    beat=self.name,
                    text=f"No game scheduled in the next {LOOKAHEAD_DAYS} days.",
                    fields={"as_of": today.isoformat()},  # FR-19
                    observations=[next_ref],
                )
            )

        return BeatResult(
            beat=self.name,
            items=items,
            checkable_fields=checkable,
            observations=observations,
        )

    def _preview_tonight_branch(
        self,
        context: BeatContext,
        upcoming: list[mlb.Game],
        team_name: str,
        today_ref: ObservationRef,
    ) -> BeatResult:
        game = upcoming[0]
        context.trace.decision(
            beat=self.name,
            decision="tonight_not_started",
            reason=(
                f"today's game {game.game_pk} is still {game.abstract_game_state!r}; "
                "one call is enough"
            ),
        )
        return BeatResult(
            beat=self.name,
            items=[
                BeatItem(
                    beat=self.name,
                    text=(
                        f"Tonight: {game.away_team} at {game.home_team}, first pitch "
                        f"{_local(game)} local. Not started yet."
                    ),
                    fields={
                        "state": game.abstract_game_state,
                        "start_time_local": _local(game),
                        "game_date": game.game_date,  # FR-19
                    },
                    observations=[today_ref],
                )
            ],
            checkable_fields={
                "game_state": game.abstract_game_state,
                "opponent": game.opponent_of(team_name),
                "start_time_utc": game.start_time_utc.isoformat(),
            },
            observations=[today_ref],
        )

    def _no_game_branch(
        self,
        context: BeatContext,
        today: date,
        team_name: str,
        today_ref: ObservationRef,
    ) -> BeatResult:
        """Off day or offseason. Normal, available result — not an error, not empty."""
        context.trace.decision(
            beat=self.name,
            decision="no_game",
            reason=(
                f"the schedule returned no games for {today}; that is an off day or the "
                "offseason, which is information rather than a failure"
            ),
        )
        return BeatResult(
            beat=self.name,
            items=[
                BeatItem(
                    beat=self.name,
                    text=f"No {team_name} game today.",
                    # FR-19: identical on every off day without the date, so a run of
                    # off days would go silent about the Astros entirely.
                    fields={"game_count": 0, "date": today.isoformat()},
                    observations=[today_ref],
                )
            ],
            # Nothing checkable on an off day. "No Astros game today." states no number,
            # and `game_count: 0` was a claim about the observation's *cardinality* rather
            # than a value inside it — the adapter returns a normalized `Game` list, so an
            # off day records `[]`, and the count of an empty list is not one of its
            # leaves. FR-11's support check looks for the value in the payload and cannot
            # see a count, so declaring it failed a run that had stated nothing wrong.
            #
            # Found live 2026-08-13, the first off day since the pipeline started running.
            # `game_count` stays in the item's `fields`, where FR-19 uses it and where
            # nothing polices it. FR-11's own scope note applies exactly: a value the
            # digest does not state is prose, not a claim.
            checkable_fields={},
            observations=[today_ref],
        )


__all__ = ["LOOKAHEAD_DAYS", "LOOKBACK_DAYS", "AstrosBeat"]

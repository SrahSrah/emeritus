"""FR-19, the time-scoped case: a fact about a particular day is never a repeat.

Found 2026-08-02 by asking a plain question about the design: does the retrieval check
need to run on the two beats that are pure API calls?

The answer is that it may run harmlessly, but only because every item says which day it
is about. FR-19's first invariant is "a checkable value that differs may be reframed but
never suppressed", and it is the *date* that differs for a time-scoped item even when
every other value is identical. Without it:

- two off days in a row produce byte-identical lines, so the Astros beat goes silent
  for the whole stretch;
- a 4-2 win on the 3rd and a 4-2 win on the 9th carry identical fields, so the second
  one can be dropped as a repeat of the first.

Both fall through to the model, and FR-19 exists precisely so that no model judgment is
load-bearing for whether a real fact reaches the digest.

The weather beat already carried ``morning``. The Astros items did not; they do now.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.agent import AgentResponse
from forecaster.beats.astros import AstrosBeat
from forecaster.beats.base import BeatItem, load_builtin_beats, run_beat_safely
from forecaster.beats.weather import WeatherBeat
from forecaster.memory.dedup import assess_item
from forecaster.memory.retrieval import Neighbour
from tests.conftest import Route, fixture_client
from tests.helpers import HOURLY_URL, NOW, POINTS_URL, SCHEDULE_URL, make_context, trace_in

load_builtin_beats()

#: Any one of these in an item's ``fields`` pins it to a point in time.
DATE_KEYS = {"game_date", "date", "as_of", "morning"}

WEATHER_ROUTES = [
    Route(POINTS_URL, fixture="nws_points_austin"),
    Route(HOURLY_URL, fixture="nws_hourly_austin"),
]


class Suppressor:
    """Worst case: a model that calls every near-duplicate redundant."""

    auth_mode = "subscription_oauth"

    def __init__(self) -> None:
        self.asked = 0

    def complete(self, prompt, *, structured=None, system=None, effort="low"):
        self.asked += 1
        return AgentResponse(text="SUPPRESS adds nothing", input_tokens=0, output_tokens=0)


def _run(beat, routes, tmp_path: Path, now=NOW):
    client, _ = fixture_client(routes)
    with client:
        trace = trace_in(tmp_path, "time-scoped")
        result = run_beat_safely(beat, make_context(trace=trace, http_client=client, now=now))
        trace.close()
    return result


# --------------------------------------------------------------------------- #
# Structural: every shipped item says which day it is about
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "label,beat,routes",
    [
        ("weather", WeatherBeat, WEATHER_ROUTES),
        ("astros-final", AstrosBeat, [Route(SCHEDULE_URL, fixture="mlb_final")]),
        ("astros-no-game", AstrosBeat, [Route(SCHEDULE_URL, fixture="mlb_no_game")]),
        ("astros-preview", AstrosBeat, [Route(SCHEDULE_URL, fixture="mlb_preview")]),
        ("astros-doubleheader", AstrosBeat, [Route(SCHEDULE_URL, fixture="mlb_doubleheader")]),
    ],
)
def test_every_delivered_item_carries_a_date(label, beat, routes, tmp_path: Path) -> None:
    """The guard. A new item with no date is a silent-suppression bug waiting to happen."""
    result = _run(beat(), routes, tmp_path)
    assert result.items, f"{label} produced no items to check"
    for item in result.items:
        assert DATE_KEYS & set(item.fields), (
            f"{label}: item {item.text!r} carries no date field. Without one, FR-19's "
            f"first invariant cannot fire and this line can be suppressed as a repeat "
            f"of a different day. Add one of {sorted(DATE_KEYS)} to its fields."
        )


# --------------------------------------------------------------------------- #
# Behavioural: the cases that were actually broken
# --------------------------------------------------------------------------- #


def _decide(item: BeatItem, prior_fields: dict, prior_text: str | None = None):
    client = Suppressor()
    neighbour = Neighbour(
        sent_item_id=1,
        beat=item.beat,
        sent_at="2026-07-27T19:00:00",
        rendered_text=prior_text if prior_text is not None else item.text,
        checkable_fields=prior_fields,
        similarity=1.0,
    )
    return assess_item(item, [neighbour], agent_client=client, beat=item.beat), client


def test_two_off_days_running_do_not_silence_the_astros(tmp_path: Path) -> None:
    """Identical text, identical everything but the day. Must survive."""
    today = _run(AstrosBeat(), [Route(SCHEDULE_URL, fixture="mlb_no_game")], tmp_path).items[0]
    yesterday = dict(today.fields)
    yesterday["date"] = "2026-07-26"

    decision, client = _decide(today, yesterday)

    assert decision.action != "suppress"
    assert decision.forced is True
    assert client.asked == 0, "a rule must decide this, not the model"


def test_a_different_game_with_the_same_scoreline_survives(tmp_path: Path) -> None:
    """A 4-2 win on the 3rd and a 4-2 win on the 9th are two different games."""
    item = BeatItem(
        beat="astros",
        text="Final: Houston Astros 4, Texas Rangers 2.",
        fields={"state": "Final", "away_score": 4, "home_score": 2, "game_date": "2026-08-09"},
    )
    prior = {"state": "Final", "away_score": 4, "home_score": 2, "game_date": "2026-08-03"}

    decision, client = _decide(item, prior)

    assert decision.action != "suppress"
    assert "game_date" in decision.reason
    assert client.asked == 0


def test_the_same_game_on_the_same_day_is_still_suppressible(tmp_path: Path) -> None:
    """The fix must not disable dedup. A true repeat still reaches the judgment."""
    item = BeatItem(
        beat="astros",
        text="Final: Houston Astros 4, Texas Rangers 2.",
        fields={"state": "Final", "away_score": 4, "home_score": 2, "game_date": "2026-08-03"},
    )
    decision, client = _decide(item, dict(item.fields))

    assert decision.action == "suppress"
    assert client.asked == 1, "with nothing distinguishing them, the model should decide"


def test_the_weather_beat_was_already_protected(tmp_path: Path) -> None:
    """Regression note: `morning` predates this fix. Assert it, so it stays."""
    item = _run(WeatherBeat(), WEATHER_ROUTES, tmp_path).items[0]
    assert "morning" in item.fields

    yesterday = dict(item.fields)
    yesterday["morning"] = "2026-07-27"
    decision, client = _decide(item, yesterday)

    assert decision.action != "suppress"
    assert client.asked == 0

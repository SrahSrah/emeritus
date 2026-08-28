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

## Amended 2026-08-04 by FR-27 — the rule does not generalize

Everything above assumes a **recurring status item**. A document-shaped beat inverts it:
the same story on a different day *is* the repeat, and a date in ``fields`` would make
FR-19's first invariant fire nightly and silently disable dedup for that beat. So an item
declaring ``text_origin="synthesized"`` is exempt from the date requirement and is
covered instead by FR-27's grounded-value veto, which reads the prose — a new number,
quotation, or proper noun — rather than typed fields.

The exemption is narrow and its inverse is asserted below: such an item must carry
**none** of the per-artifact keys, because carrying one is exactly the bug.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.agent import AgentResponse
from forecaster.beats.astros import AstrosBeat
from forecaster.beats.base import (
    BeatItem,
    load_builtin_beats,
    registered_beats,
    run_beat_safely,
)
from forecaster.beats.weather import WeatherBeat
from forecaster.memory.dedup import SYNTHESIZED, assess_item
from forecaster.memory.retrieval import Neighbour
from tests.conftest import Route, fixture_client
from tests.helpers import HOURLY_URL, NOW, POINTS_URL, SCHEDULE_URL, make_context, trace_in

load_builtin_beats()

#: Any one of these in an item's ``fields`` pins it to a point in time.
DATE_KEYS = {"game_date", "date", "as_of", "morning"}

#: Keys a synthesized item may never declare. Each one, in a document-shaped beat, makes
#: FR-19's first invariant fire on every candidate and silently disables dedup.
ARTIFACT_KEYS = DATE_KEYS | {"published", "url", "source"}

#: Beat names this file drives through real fixtures. The coverage test below fails when
#: a registered beat is missing from it, so a new beat cannot land unexamined.
COVERED_BEATS = {"astros", "weather", "news", "need_to_know", "venues", "wsb"}

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


def _run(beat, routes, tmp_path: Path, now=NOW, **context_kwargs):
    client, _ = fixture_client(routes)
    with client:
        trace = trace_in(tmp_path, "time-scoped")
        result = run_beat_safely(
            beat,
            make_context(trace=trace, http_client=client, now=now, **context_kwargs),
        )
        trace.close()
    return result


def _run_news(tmp_path: Path):
    """The news beat needs three collaborators the structured beats do not."""
    from tests.test_beat_news import NOW as NEWS_NOW, PassageClient, _routes

    from forecaster.beats.news import NewsBeat
    from forecaster.memory import corpus as corpus_module
    from forecaster.memory.retrieval import HashingEmbedder
    from tests.helpers import NEWS_CONFIG, make_config

    return _run(
        NewsBeat(),
        _routes(),
        tmp_path,
        now=NEWS_NOW,
        config=make_config(beats={"news": True}, news=NEWS_CONFIG),
        embedder=HashingEmbedder(),
        corpus=corpus_module.connect(tmp_path / "corpus.db"),
        agent_client=PassageClient(),
    )


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
        exempt = item.fields.get("text_origin") == SYNTHESIZED
        assert (DATE_KEYS & set(item.fields)) or exempt, (
            f"{label}: item {item.text!r} carries no date field. Without one, FR-19's "
            f"first invariant cannot fire and this line can be suppressed as a repeat "
            f"of a different day. Add one of {sorted(DATE_KEYS)} to its fields — or, if "
            f"this is a document-shaped beat whose text the model wrote, declare "
            f"text_origin={SYNTHESIZED!r} and rely on FR-27's grounded-value veto."
        )


def test_every_registered_beat_is_exercised_by_this_file() -> None:
    """The forcing function: a new beat cannot land without being examined here.

    This file drives real beats through real fixtures, which a registry walk cannot do on
    its own — it has no way to know a new beat's fixture routes. So instead of silently
    covering less, the coverage list is asserted against the registry, and adding a beat
    without adding its cases fails right here with an explanation.
    """
    registered = set(registered_beats())
    missing = registered - COVERED_BEATS
    assert not missing, (
        f"beat(s) {sorted(missing)} are registered but not exercised in this file. Add "
        "their fixture routes to the parametrize list above. A beat whose items are "
        "never checked for time-scoping is exactly the silent-suppression bug FR-19 and "
        "FR-27 exist to prevent."
    )


@pytest.mark.parametrize(
    "label,beat,routes",
    [
        ("weather", WeatherBeat, WEATHER_ROUTES),
        ("astros-final", AstrosBeat, [Route(SCHEDULE_URL, fixture="mlb_final")]),
    ],
)
def test_no_synthesized_item_carries_a_per_artifact_key(label, beat, routes, tmp_path: Path) -> None:
    """The inverse of the exemption, checked on real beat output.

    Vacuous for the two structured beats, which is correct — they declare no
    ``text_origin``. The news case below is where it bites.
    """
    _assert_no_artifact_keys(label, _run(beat(), routes, tmp_path).items)


def _assert_no_artifact_keys(label: str, items) -> None:
    for item in items:
        if item.fields.get("text_origin") != SYNTHESIZED:
            continue
        offenders = ARTIFACT_KEYS & set(item.fields)
        assert not offenders, (
            f"{label}: synthesized item declares {sorted(offenders)}. Each of those "
            "differs between two articles about the same story, so FR-19's first "
            "invariant would fire every night and dedup would never suppress anything."
        )


# --------------------------------------------------------------------------- #
# The news beat — the exemption's only current user
# --------------------------------------------------------------------------- #


def test_news_items_take_the_exemption_and_declare_no_artifact_key(tmp_path: Path) -> None:
    """The document-shaped case: exempt from the date rule, and it must earn that."""
    result = _run_news(tmp_path)
    assert result.items, "the news fixtures should produce at least one item"

    for item in result.items:
        assert item.fields.get("text_origin") == SYNTHESIZED, (
            "a news item with no text_origin would fall under the date rule, which "
            "inverts for a document-shaped beat"
        )
        assert not DATE_KEYS & set(item.fields)

    _assert_no_artifact_keys("news", result.items)


def test_two_news_runs_of_the_same_story_are_suppressible(tmp_path: Path) -> None:
    """The failure mode the whole increment exists for, through the real beat.

    Checkpoint 1 named it: several days of AI news collapsing into "Fable rocks but is
    expensive". The item must reach the judgment rather than being vetoed by a field.
    """
    item = _run_news(tmp_path).items[0]

    client = Suppressor()
    neighbour = Neighbour(
        sent_item_id=1,
        beat="news",
        sent_at="2026-08-03T19:00:00",
        rendered_text=item.text,
        checkable_fields=dict(item.fields),
        similarity=1.0,
    )
    decision = assess_item(item, [neighbour], agent_client=client, beat="news")

    assert decision.action == "suppress"
    assert client.asked == 1, "no field may decide this — the prose has nothing new in it"


def test_a_stray_date_cannot_disable_dedup_for_a_synthesized_item() -> None:
    """FR-27 short-circuits the typed invariant rather than merely coexisting with it.

    The spec framed "news items carry no date, url, or source in ``fields``" as a
    requirement, on the reasoning that a per-artifact field would make FR-19's first
    invariant fire nightly. The implementation is stronger: for a synthesized item the
    typed comparison is **never reached**, so a field that leaked in cannot disable dedup.
    The convention still holds — those keys are meaningless noise on a news item — but it
    is belt-and-braces now, not load-bearing.

    Enforcing the property rather than requesting it is the same reasoning as FR-11's
    provenance check and FR-19's invariants.
    """
    text = "Anthropic shipped a faster Claude model, per Ars Technica."
    neighbour = Neighbour(
        sent_item_id=1,
        beat="news",
        sent_at="2026-08-03T19:00:00",
        rendered_text=text,
        checkable_fields={"topic": "claude", "text_origin": SYNTHESIZED, "date": "2026-08-03"},
        similarity=1.0,
    )

    for label, fields in (
        ("clean", {"topic": "claude", "text_origin": SYNTHESIZED}),
        ("stray date", {"topic": "claude", "text_origin": SYNTHESIZED, "date": "2026-08-04"}),
        ("stray url", {"topic": "claude", "text_origin": SYNTHESIZED, "url": "https://b.test/x"}),
    ):
        client = Suppressor()
        decision = assess_item(
            BeatItem(beat="news", text=text, fields=dict(fields)),
            [neighbour],
            agent_client=client,
            beat="news",
        )
        assert decision.action == "suppress", f"{label}: dedup went dead"
        assert client.asked == 1, f"{label}: the judgment must still be reachable"


def test_the_typed_date_rule_still_governs_a_structured_beat(tmp_path: Path) -> None:
    """FR-27 carved out one class of item. It did not weaken the original rule."""
    today = _run(AstrosBeat(), [Route(SCHEDULE_URL, fixture="mlb_no_game")], tmp_path).items[0]
    yesterday = dict(today.fields)
    yesterday["date"] = "2026-07-26"

    decision, client = _decide(today, yesterday)

    assert decision.action != "suppress"
    assert decision.forced is True
    assert client.asked == 0


# --------------------------------------------------------------------------- #
# The need-to-know beat — dated status lines are its only items (v4, FR-34)
# --------------------------------------------------------------------------- #


def _run_ntk(tmp_path: Path, *, routes=None):
    """The observation beat: embedder + corpus, but deliberately no working model."""
    from tests.test_beat_need_to_know import NOW as NTK_NOW, _no_model, _routes

    from forecaster.beats.need_to_know import NeedToKnowBeat
    from forecaster.memory import corpus as corpus_module
    from forecaster.memory.retrieval import HashingEmbedder
    from tests.helpers import NEED_TO_KNOW_CONFIG, make_config

    return _run(
        NeedToKnowBeat(),
        routes if routes is not None else _routes(),
        tmp_path,
        now=NTK_NOW,
        config=make_config(
            beats={"need_to_know": True}, need_to_know=NEED_TO_KNOW_CONFIG
        ),
        embedder=HashingEmbedder(),
        corpus=corpus_module.connect(tmp_path / "corpus.db"),
        agent_client=_no_model(),
    )


def test_need_to_know_quiet_nights_emit_one_dated_pulse_line(tmp_path: Path) -> None:
    """The v5 contract (FR-39): quiet is inbox-visible as one code-assembled, dated line.

    v4 asserted zero items here; the pulse line replaced designed silence with designed
    accounting. It is a status item, so the original date rule governs it — reframe-only
    against last night's near-identical pulse, never suppressed.
    """
    result = _run_ntk(tmp_path)
    assert result.available
    (pulse,) = result.items
    assert pulse.fields.get("text_origin") is None
    assert DATE_KEYS & set(pulse.fields)
    assert "Nothing cleared the need-to-know bar" in pulse.text


def test_need_to_know_unavailability_lines_carry_a_date(tmp_path: Path) -> None:
    """Its only items are FR-28 status lines, and they fall under the original date rule."""
    from tests.test_beat_need_to_know import _routes_with_dead_feed

    result = _run_ntk(tmp_path, routes=_routes_with_dead_feed())
    assert result.items, "a dead source must produce a named status line"
    for item in result.items:
        assert item.fields.get("text_origin") is None, (
            "a status line is code-assembled, never synthesized — the date rule governs it"
        )
        assert DATE_KEYS & set(item.fields), (
            "an undated unavailability line could be suppressed as a repeat of last "
            "night's outage, which is exactly FR-18's silent failure"
        )


# --------------------------------------------------------------------------- #
# The venues beat — dated, code-assembled listings (FR-43); dedup handled by FR-44
# --------------------------------------------------------------------------- #


def test_venue_items_carry_dates_and_are_never_synthesized(tmp_path: Path) -> None:
    """Every listing and status line is code-assembled and dated.

    Dedup for this beat is governed by FR-44's config exemption, not by these fields —
    but the fields still matter: if the exemption is ever lifted, the date rule is what
    keeps a standing listing from being suppressed as last night's repeat.
    """
    from tests.test_beat_venues import NOW as VENUES_NOW, _no_model, _routes

    from forecaster.beats.venues import VenueListingsBeat
    from tests.helpers import VENUES_CONFIG, make_config

    result = _run(
        VenueListingsBeat(),
        _routes(),
        tmp_path,
        now=VENUES_NOW,
        config=make_config(beats={"venues": True}, venues=VENUES_CONFIG),
        agent_client=_no_model(),
    )
    assert result.items, "the capture has in-window productions"
    for item in result.items:
        assert item.fields.get("text_origin") is None, (
            "a listing is code-assembled; nothing in this beat is model-written"
        )
        assert DATE_KEYS & set(item.fields)


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


# --------------------------------------------------------------------------- #
# The wsb beat — dated, code-assembled counts (FR-49); standard dedup path
# --------------------------------------------------------------------------- #


def test_wsb_items_carry_dates_and_are_never_synthesized(tmp_path: Path) -> None:
    """Both delivered shapes — counts and the quiet line — are code-assembled and dated.

    This beat takes the standard dedup path (no FR-44 exemption), so `as_of` is exactly
    what keeps a recurring counts line reframe-only rather than suppressible.
    """
    from tests.test_beat_wsb import NOW as WSB_NOW, _no_model, _routes
    from tests.conftest import Route as _Route

    from forecaster.beats.wsb import WsbMentionsBeat
    from tests.helpers import WSB_CONFIG, make_config

    for fixture in ("feed_wsb.xml", "feed_wsb_nomatch.xml"):
        result = _run(
            WsbMentionsBeat(),
            [_Route(r"reddit\.test/r/wallstreetbets/\.rss", fixture=fixture)],
            tmp_path,
            now=WSB_NOW,
            config=make_config(beats={"wsb": True}, wsb=WSB_CONFIG),
            agent_client=_no_model(),
        )
        assert result.items, f"{fixture} must deliver a line"
        for item in result.items:
            assert item.fields.get("text_origin") is None, (
                "a count line is code-assembled; nothing in this beat is model-written"
            )
            assert DATE_KEYS & set(item.fields)

"""Step 42 — FR-43/FR-45: the venue listings beat, driven by the real captured page.

The clock is pinned to the capture evening (2026-08-16), so of the eleven parsed
productions exactly two intersect the 14-day window: "Sally & Tom" (through Aug 23) and
"Come From Away" (opens Aug 19). Everything here asserts against those real shows.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from forecaster.beats.base import BeatContext, load_builtin_beats, run_beat_safely
from forecaster.beats.venues import VenueListingsBeat
from forecaster.tools.venues import Production
from forecaster.trace import check_provenance, read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import VENUES_CONFIG, make_config, make_preferences, trace_in

load_builtin_beats()

#: The evening the page was captured — "Sally & Tom" is running, "Come From Away" opens
#: in three days, and everything else is outside the fortnight.
NOW = datetime(2026, 8, 16, 19, 0, tzinfo=timezone.utc)

SHOWS_URL = r"zachtheater\.test/tickets/shows"


class _no_model:
    auth_mode = "subscription_oauth"

    def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("the venues beat must never call the model")


def _routes(shows: Route | None = None):
    return [
        Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
        shows or Route(SHOWS_URL, fixture="zach_shows.html", content_type="text/html"),
    ]


def _run(tmp_path: Path, *, routes=None, config=None, now=NOW):
    http, recorder = fixture_client(routes or _routes())
    trace = trace_in(tmp_path, "venues")
    with http:
        context = BeatContext(
            config=config or make_config(beats={"venues": True}, venues=VENUES_CONFIG),
            preferences=make_preferences(),
            now=now,
            scratchpad=__import__(
                "forecaster.memory.scratchpad", fromlist=["Scratchpad"]
            ).Scratchpad(trace=trace),
            trace=trace,
            http_client=http,
            embedder=None,
            corpus=None,
            agent_client=_no_model(),
        )
        result = run_beat_safely(VenueListingsBeat(), context)
    trace.beat_result(result)
    trace.close()
    return result, trace


def _decisions(trace, kind: str):
    return [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record.get("decision") == kind
    ]


# --------------------------------------------------------------------------- #
# The healthy night — real shows, exact window
# --------------------------------------------------------------------------- #


def test_exactly_the_intersecting_productions_are_listed(tmp_path) -> None:
    result, trace = _run(tmp_path)

    assert result.available
    titles = [item.fields.get("title") for item in result.items]
    assert titles == ["Sally & Tom", "Come From Away"]

    (decision,) = _decisions(trace, "venue_listed")
    assert (decision["listed"], decision["parsed"]) == (2, 11)


def test_listings_quote_the_pages_own_dates_and_carry_the_link(tmp_path) -> None:
    result, _ = _run(tmp_path)
    sally = result.items[0]
    assert "July 22 - August 23, 2026" in sally.text, "the venue's words, verbatim"
    assert "/tickets/pdps/sally-tom/" in sally.text
    assert sally.fields["end_date"] == "2026-08-23"
    assert sally.fields["as_of"] == "2026-08-16"


def test_every_listing_passes_the_provenance_check(tmp_path) -> None:
    """FR-11, unmodified, polices this beat: titles and dates are checkable values."""
    result, trace = _run(tmp_path)

    assert result.checkable_fields, "listings must declare their claims"
    digest_text = "\n".join(item.text for item in result.items)
    report = check_provenance(trace.path, digest_text)
    assert report.violations == []
    assert report.checked_fields >= 4  # two titles + two date strings


def test_a_tampered_listing_fails_the_provenance_check(tmp_path) -> None:
    """The check has teeth here: a date the beat never observed is a violation."""
    result, trace = _run(tmp_path)
    tampered = "\n".join(item.text for item in result.items).replace(
        "August 23", "August 30"
    )
    report = check_provenance(trace.path, tampered)
    assert report.violations, "an altered date must not pass"


def test_the_beat_touches_no_model_embedder_or_corpus(tmp_path) -> None:
    """Injected: an exploding client and None for both memory collaborators."""
    result, _ = _run(tmp_path)  # _no_model raises on contact; None corpus/embedder
    assert result.available


# --------------------------------------------------------------------------- #
# Quiet vs broken — FR-45's whole point
# --------------------------------------------------------------------------- #


def test_a_parsed_empty_calendar_is_a_quiet_line_not_an_outage(tmp_path) -> None:
    routes = _routes(
        Route(SHOWS_URL, fixture="zach_shows_empty.html", content_type="text/html")
    )
    result, trace = _run(tmp_path, routes=routes)

    assert result.available
    (item,) = result.items
    assert "Nothing on the calendar at ZACH Theatre in the next 14 days." == item.text
    assert item.fields["as_of"] == "2026-08-16"
    assert len(_decisions(trace, "venue_quiet")) == 1
    assert _decisions(trace, "venue_unavailable") == []


def test_a_window_with_no_shows_is_also_quiet(tmp_path) -> None:
    """Same page, a January clock: eleven productions parsed, none in the fortnight."""
    result, trace = _run(tmp_path, now=datetime(2026, 1, 10, 19, 0, tzinfo=timezone.utc))
    assert result.available
    (item,) = result.items
    assert "Nothing on the calendar" in item.text
    (decision,) = _decisions(trace, "venue_quiet")
    assert "parsed 11 production(s)" in decision["reason"]


def test_a_redesigned_page_is_the_unavailable_shape(tmp_path) -> None:
    routes = _routes(
        Route(SHOWS_URL, fixture="zach_shows_redesigned.html", content_type="text/html")
    )
    result, trace = _run(tmp_path, routes=routes)

    assert result.available is False
    assert "ZACH Theatre" in (result.error or "")
    assert result.checkable_fields == {}
    assert len(_decisions(trace, "venue_unavailable")) == 1


def test_one_dark_venue_among_two_stays_available_and_is_named(tmp_path) -> None:
    config = make_config(
        beats={"venues": True},
        venues={
            **VENUES_CONFIG,
            "venues": [
                {"name": "ZACH Theatre", "kind": "zach_shows", "url": "https://www.zachtheater.test/tickets/shows/"},
                {"name": "Dark Stage", "kind": "zach_shows", "url": "https://dark.test/shows/"},
            ],
        },
    )
    routes = _routes() + [Route(r"dark\.test/", json_body={"error": 1}, status=500)]
    result, trace = _run(tmp_path, routes=routes, config=config)

    assert result.available
    outage = [item for item in result.items if "Couldn't read" in item.text]
    assert len(outage) == 1 and "Dark Stage" in outage[0].text
    assert [item.fields.get("title") for item in result.items[:2]] == [
        "Sally & Tom",
        "Come From Away",
    ]


def test_an_unknown_kind_is_a_named_runtime_failure(tmp_path) -> None:
    config = make_config(
        beats={"venues": True},
        venues={
            **VENUES_CONFIG,
            "venues": [{"name": "Somewhere", "kind": "not_a_parser", "url": "https://a.test/"}],
        },
    )
    result, trace = _run(tmp_path, config=config)
    assert result.available is False
    assert "no parser registered for kind 'not_a_parser'" in (result.error or "")


# --------------------------------------------------------------------------- #
# The window rule, including what must not be dropped
# --------------------------------------------------------------------------- #


def test_unparsed_dates_are_included_never_dropped() -> None:
    beat = VenueListingsBeat()

    class _Ctx:
        now = NOW

    class _Settings:
        window_days = 14

    unparsed = Production(
        title="Mystery Gala", url="https://a.test/", raw_dates="Dates TBA",
        start_date=None, end_date=None,
    )
    closed = Production(
        title="Closed Show", url="https://a.test/", raw_dates="July 1 - July 10, 2026",
        start_date=date(2026, 7, 1), end_date=date(2026, 7, 10),
    )
    kept = beat._in_window(_Ctx(), _Settings(), [unparsed, closed])
    assert kept == [unparsed]


def test_disabling_the_flag_removes_the_beat_from_the_run() -> None:
    from forecaster.beats.base import get_beats

    on = make_config(beats={"venues": True}, venues=VENUES_CONFIG)
    off = make_config(venues=VENUES_CONFIG)
    assert "venues" in [beat.name for beat in get_beats(on)]
    assert "venues" not in [beat.name for beat in get_beats(off)]

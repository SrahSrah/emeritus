"""Step 41 — FR-42: the ZACH parser, driven by the real captured page.

The capture (2026-08-16) supplies the mess on purpose: hyphens and en-dashes, NBSPs,
cross-year ranges, year-inheriting starts, a day-only second half, an all-caps month,
and a title containing "|". Assertions name real productions from the capture — read it,
don't assume it.
"""

from __future__ import annotations

from datetime import date

import pytest

from forecaster.tools.venues import (
    Production,
    VenueParseError,
    fetch_listings,
    parse_date_range,
    parse_listings,
)
from tests.conftest import Route, fixture_client, load_text_fixture

BASE = "https://www.zachtheater.test/tickets/shows/"


def _parse_fixture(name: str = "zach_shows.html") -> list[Production]:
    return parse_listings(load_text_fixture(name), base_url=BASE)


# --------------------------------------------------------------------------- #
# The real page
# --------------------------------------------------------------------------- #


def test_the_captured_page_parses_its_productions() -> None:
    productions = _parse_fixture()
    by_title = {production.title: production for production in productions}

    assert len(productions) == 11

    sally = by_title["Sally & Tom"]
    assert sally.start_date == date(2026, 7, 22)
    assert sally.end_date == date(2026, 8, 23)
    assert sally.url == "https://www.zachtheater.test/tickets/pdps/sally-tom/"
    assert "The Kleberg" in sally.raw_dates

    # Cross-year, both years explicit.
    lion = by_title["THE LION, THE WITCH AND THE WARDROBE"]
    assert (lion.start_date, lion.end_date) == (date(2026, 10, 16), date(2027, 2, 14))

    # Start inherits the end's year.
    carol = by_title["A Christmas Carol"]
    assert (carol.start_date, carol.end_date) == (date(2026, 11, 18), date(2026, 12, 27))

    # Day-only second half, all-caps month.
    liberation = by_title["Liberation"]
    assert (liberation.start_date, liberation.end_date) == (
        date(2027, 6, 2),
        date(2027, 6, 27),
    )


def test_a_title_containing_a_pipe_survives_intact() -> None:
    """'GO, DOG. GO! | VE PERRO ¡VE!' — why nothing here splits on '|'."""
    titles = [production.title for production in _parse_fixture()]
    assert any(title.startswith("GO, DOG. GO!") and "|" in title for title in titles)


def test_a_card_with_no_ticket_link_falls_back_to_the_listing_url() -> None:
    productions = _parse_fixture()
    fallbacks = [p for p in productions if p.url == BASE]
    linked = [p for p in productions if p.url != BASE]
    assert linked, "the capture has ticket links"
    for production in fallbacks:
        assert production.title  # still a real listing, just without its own page yet


def test_every_parsed_production_keeps_the_pages_own_words() -> None:
    for production in _parse_fixture():
        assert production.raw_dates, (
            f"{production.title}: raw_dates must carry the page text verbatim even "
            "when the dates parsed"
        )


# --------------------------------------------------------------------------- #
# The three structural outcomes
# --------------------------------------------------------------------------- #


def test_landmarks_without_cards_is_parsed_empty_not_an_error() -> None:
    assert _parse_fixture("zach_shows_empty.html") == []


def test_a_redesigned_page_raises_rather_than_reading_as_empty() -> None:
    with pytest.raises(VenueParseError, match="redesign"):
        _parse_fixture("zach_shows_redesigned.html")


# --------------------------------------------------------------------------- #
# Date parsing rules, incl. what must NOT parse
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("July 22 - August 23, 2026 | The Kleberg", (date(2026, 7, 22), date(2026, 8, 23))),
        ("JUNE 2–27, 2027", (date(2027, 6, 2), date(2027, 6, 27))),
        ("October 16, 2026–February 14, 2027", (date(2026, 10, 16), date(2027, 2, 14))),
        # A start with no year, after its end's month: crossed a year boundary.
        ("December 5 – January 3, 2027", (date(2026, 12, 5), date(2027, 1, 3))),
        ("October 16, 2026", (date(2026, 10, 16), date(2026, 10, 16))),
        # NBSP where a space should be, as the capture actually has.
        ("November 6–December 27, 2026 | The Kleberg", (date(2026, 11, 6), date(2026, 12, 27))),
    ],
)
def test_date_range_forms_from_the_capture(raw, expected) -> None:
    assert parse_date_range(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "Season announcement coming soon",
        "June 2 – 27",  # no year anywhere — no claim
        "February 30 – March 2, 2027",  # impossible day
        "",
    ],
)
def test_unparseable_dates_make_no_claim(raw) -> None:
    assert parse_date_range(raw) == (None, None)


# --------------------------------------------------------------------------- #
# The fetch posture
# --------------------------------------------------------------------------- #


def _fetch(routes):
    client, recorder = fixture_client(routes)
    with client:
        return (
            fetch_listings(
                BASE, client=client, user_agent="forecaster-test/0.1", timeout=5
            ),
            recorder,
        )


def test_fetch_parses_and_sends_the_identifying_user_agent() -> None:
    productions, recorder = _fetch(
        [
            Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
            Route(r"tickets/shows", fixture="zach_shows.html", content_type="text/html"),
        ]
    )
    assert len(productions) == 11
    for request in recorder.requests:
        assert request.headers["user-agent"] == "forecaster-test/0.1"


def test_a_robots_disallow_is_an_error_not_a_fetch() -> None:
    client, recorder = fixture_client(
        [
            Route(r"/robots\.txt", text="User-agent: *\nDisallow: /tickets/\n"),
            Route(r"tickets/shows", fixture="zach_shows.html", content_type="text/html"),
        ]
    )
    with client:
        with pytest.raises(VenueParseError, match="robots"):
            fetch_listings(BASE, client=client, user_agent="forecaster-test/0.1", timeout=5)
    assert all("/robots.txt" in str(request.url) for request in recorder.requests), (
        "the listings page must never have been fetched"
    )


def test_a_non_200_is_an_error_and_redirects_are_not_chased() -> None:
    with pytest.raises(VenueParseError, match="HTTP 500"):
        _fetch(
            [
                Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
                Route(r"tickets/shows", json_body={"error": 1}, status=500),
            ]
        )
    # The domain gotcha: a session-bounce redirect must surface, not be followed.
    with pytest.raises(VenueParseError, match="HTTP 301"):
        _fetch(
            [
                Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
                Route(r"tickets/shows", text="", status=301),
            ]
        )

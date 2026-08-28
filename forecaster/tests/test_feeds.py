"""Step 25 — FR-20: the feed adapter normalizes RSS and Atom, and drops rather than guesses.

All three fixtures are real or deliberately synthetic; none is fetched at test time. The
socket guard would fail the suite if one were.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecaster.tools.feeds import (
    AdapterError,
    FeedEntry,
    fetch_feed,
    parse_feed,
    strip_markup,
    within_window,
)
from tests.conftest import Route, fixture_client, load_text_fixture
from tests.helpers import trace_in

ARS_URL = r"feeds\.arstechnica\.com"
VERGE_URL = r"theverge\.com/rss"
MALFORMED_URL = r"malformed\.test/feed"

USER_AGENT = "forecaster-test/0.1 (tests@example.test)"


def _fetch(routes, url: str, source: str, **kwargs):
    client, recorder = fixture_client(routes)
    with client:
        entries = fetch_feed(
            url, source, client=client, user_agent=USER_AGENT, **kwargs
        )
    return entries, recorder


# --------------------------------------------------------------------------- #
# The two real shapes
# --------------------------------------------------------------------------- #


def test_rss_two_point_zero_normalizes() -> None:
    """Ars Technica: 20 <item>, RFC 822 <pubDate>, body in <content:encoded>."""
    entries, _ = _fetch(
        [Route(ARS_URL, fixture="feed_arstechnica.xml")],
        "https://feeds.arstechnica.com/arstechnica/index",
        "Ars Technica",
        tz_name="America/Chicago",
    )

    assert len(entries) == 20
    first = entries[0]
    assert first.source == "Ars Technica"
    assert first.url.startswith("http")
    assert first.headline
    assert first.summary
    assert "<" not in first.summary, "markup must be stripped, not passed through"
    assert first.text_source == "unfetched", "the article itself has not been read yet"
    assert first.body == ""


def test_atom_normalizes() -> None:
    """The Verge: 10 <entry>, ISO 8601 <published>, url in a link href attribute."""
    entries, _ = _fetch(
        [Route(VERGE_URL, fixture="feed_theverge.xml")],
        "https://www.theverge.com/rss/index.xml",
        "The Verge",
        tz_name="America/Chicago",
    )

    assert len(entries) == 10
    assert all(entry.url.startswith("http") for entry in entries)
    assert all(entry.headline for entry in entries)
    assert all(entry.source == "The Verge" for entry in entries)


@pytest.mark.parametrize(
    "fixture,source",
    [("feed_arstechnica.xml", "Ars Technica"), ("feed_theverge.xml", "The Verge")],
)
def test_published_is_timezone_aware_and_localized(fixture, source) -> None:
    """A naive timestamp would put an article in the wrong retrieval window."""
    entries, _ = parse_feed(
        load_text_fixture(fixture), source=source, tz_name="America/Chicago"
    )
    assert entries
    for entry in entries:
        assert entry.published.tzinfo is not None
        assert "Chicago" in str(entry.published.tzinfo)


def test_timezone_conversion_actually_moves_the_clock() -> None:
    """Asserting tzinfo alone would pass on a no-op conversion."""
    utc, _ = parse_feed(
        load_text_fixture("feed_arstechnica.xml"), source="Ars", tz_name="UTC"
    )
    local, _ = parse_feed(
        load_text_fixture("feed_arstechnica.xml"), source="Ars", tz_name="America/Chicago"
    )
    assert utc[0].published == local[0].published, "the instant is the same"
    assert utc[0].published.hour != local[0].published.hour, "the wall clock is not"


# --------------------------------------------------------------------------- #
# Dropping, not defaulting
# --------------------------------------------------------------------------- #


def test_entries_with_no_date_or_no_link_are_dropped_with_a_reason(tmp_path: Path) -> None:
    """FR-20's criterion. A substituted date would file the article in the wrong window."""
    trace = trace_in(tmp_path, "feed-drop")
    client, _ = fixture_client([Route(MALFORMED_URL, fixture="feed_malformed.xml")])
    with client:
        entries = fetch_feed(
            "https://malformed.test/feed",
            "Synthetic",
            client=client,
            user_agent=USER_AGENT,
            trace=trace,
        )
    trace.close()

    assert len(entries) == 1
    assert entries[0].url == "https://malformed.test/good-article"

    from forecaster.trace import read_trace, records_of

    drops = list(records_of(read_trace(trace.path), "decision"))
    drops = [d for d in drops if d["decision"] == "feed_entry_dropped"]
    assert len(drops) == 3, "no-date, no-link, and unparseable-date all get recorded"
    joined = " ".join(d["reason"] for d in drops)
    assert "no resolvable publication date" in joined
    assert "no resolvable link" in joined


def test_a_dropped_entry_is_never_silently_defaulted() -> None:
    """Belt and braces: nothing in the output carries an invented date."""
    entries, dropped = parse_feed(
        load_text_fixture("feed_malformed.xml"), source="Synthetic"
    )
    assert len(entries) == 1
    assert len(dropped) == 3


# --------------------------------------------------------------------------- #
# Failure contract — same shape as mlb.py and weather.py
# --------------------------------------------------------------------------- #


def test_a_500_raises_adapter_error() -> None:
    client, _ = fixture_client([Route(ARS_URL, json_body={"detail": "nope"}, status=500)])
    with client:
        with pytest.raises(AdapterError, match="returned 500"):
            fetch_feed(
                "https://feeds.arstechnica.com/x",
                "Ars Technica",
                client=client,
                user_agent=USER_AGENT,
            )


def test_a_body_that_is_not_xml_raises_rather_than_returning_nothing() -> None:
    """An empty list would look like a quiet news day. It is not the same thing."""
    client, _ = fixture_client([Route(ARS_URL, text="<<< not xml at all", content_type="text/html")])
    with client:
        with pytest.raises(AdapterError, match="not parseable XML"):
            fetch_feed(
                "https://feeds.arstechnica.com/x",
                "Ars Technica",
                client=client,
                user_agent=USER_AGENT,
            )


def test_the_configured_user_agent_is_sent_on_every_request() -> None:
    """Politeness, and the thing that makes a publisher able to identify this client."""
    _, recorder = _fetch(
        [Route(ARS_URL, fixture="feed_arstechnica.xml")],
        "https://feeds.arstechnica.com/arstechnica/index",
        "Ars Technica",
    )
    assert recorder.requests
    for request in recorder.requests:
        assert request.headers["user-agent"] == USER_AGENT


# --------------------------------------------------------------------------- #
# The window filter — FR-21 depends on this running first
# --------------------------------------------------------------------------- #


def _entry(days_ago: float, *, now: datetime) -> FeedEntry:
    return FeedEntry(
        url=f"https://example.test/{days_ago}",
        source="Test",
        headline=f"{days_ago} days ago",
        published=now - timedelta(days=days_ago),
        summary="",
    )


def test_within_window_keeps_only_recent_entries() -> None:
    now = datetime(2026, 8, 4, 19, 0, tzinfo=timezone.utc)
    entries = [_entry(d, now=now) for d in (0, 1, 2.5, 3.5, 10)]

    kept = within_window(entries, now=now, window_days=3)

    assert [e.headline for e in kept] == ["0 days ago", "1 days ago", "2.5 days ago"]


def test_within_window_tolerates_mixed_awareness() -> None:
    """Feeds mix aware and naive timestamps; a TypeError here would fail a whole beat."""
    now = datetime(2026, 8, 4, 19, 0)
    aware = FeedEntry(
        url="https://example.test/aware",
        source="Test",
        headline="aware",
        published=datetime(2026, 8, 4, 12, 0, tzinfo=timezone.utc),
        summary="",
    )
    assert within_window([aware], now=now, window_days=3) == [aware]


# --------------------------------------------------------------------------- #
# Markup handling
# --------------------------------------------------------------------------- #


def test_strip_markup_unescapes_and_flattens() -> None:
    assert strip_markup("<p>Hello &amp; welcome</p>") == "Hello & welcome"
    assert strip_markup("&lt;p&gt;Double escaped&lt;/p&gt;") == "Double escaped"
    assert strip_markup(None) == ""
    assert strip_markup("") == ""


def test_feed_summaries_are_short_which_is_why_fr21_exists() -> None:
    """The measurement the source decision turned on, pinned as a test.

    If a publisher starts shipping full article bodies in RSS this fails, and that is
    worth knowing — it would change whether FR-21's fetch is needed at all.
    """
    entries, _ = parse_feed(load_text_fixture("feed_arstechnica.xml"), source="Ars")
    lengths = sorted(len(entry.summary) for entry in entries)
    median = lengths[len(lengths) // 2]
    assert median < 2000, (
        f"Ars Technica RSS summaries now run {median} chars. They were ~975 on "
        "2026-08-04. If feeds now carry full articles, FR-21's fetch may be unnecessary."
    )


def test_drop_records_carry_the_calling_beats_name(tmp_path: Path) -> None:
    """FR-49's adapter amendment: `beat="wsb"` labels drops honestly; the default is
    unchanged, so every existing news call site keeps recording `beat="news"`."""
    for passed, expected in ((None, "news"), ("wsb", "wsb")):
        trace = trace_in(tmp_path, f"feed-drop-{expected}")
        client, _ = fixture_client([Route(MALFORMED_URL, fixture="feed_malformed.xml")])
        kwargs = {} if passed is None else {"beat": passed}
        with client:
            fetch_feed(
                "https://malformed.test/feed",
                "Synthetic",
                client=client,
                user_agent=USER_AGENT,
                trace=trace,
                **kwargs,
            )
        trace.close()

        from forecaster.trace import read_trace, records_of

        drops = [
            record
            for record in records_of(read_trace(trace.path), "decision")
            if record["decision"] == "feed_entry_dropped"
        ]
        assert drops, "the malformed fixture must produce drops for this test to bite"
        assert {record["beat"] for record in drops} == {expected}

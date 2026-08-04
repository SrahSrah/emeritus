"""Step 26 — FR-21: fetch the article body, and never invent one.

The five acceptance clauses, plus the two mechanics that are easy to get wrong: the
window filter runs **before** the fetch, and `robots.txt` goes through the injected
client rather than `RobotFileParser.read()`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from forecaster.tools.feeds import (
    SOURCE_ARTICLE,
    SOURCE_SUMMARY,
    FeedEntry,
    HostRateLimiter,
    RobotsCache,
    extract_body,
    fetch_article_bodies,
    fetch_article_body,
)
from forecaster.trace import read_trace, records_of
from tests.conftest import Route, fixture_client, load_text_fixture
from tests.helpers import trace_in

USER_AGENT = "forecaster-test/0.1 (tests@example.test)"
NOW = datetime(2026, 8, 4, 19, 0, tzinfo=timezone.utc)

ALLOW_ALL = Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n")


def _entry(url: str, *, days_ago: float = 0.5, summary: str = "The feed's own short summary.") -> FeedEntry:
    return FeedEntry(
        url=url,
        source="Test Source",
        headline="A headline",
        published=NOW - timedelta(days=days_ago),
        summary=summary,
    )


def _fetch_one(entry: FeedEntry, routes, *, min_body_chars: int = 600, trace=None):
    client, recorder = fixture_client(routes)
    with client:
        result = fetch_article_body(
            entry,
            client=client,
            user_agent=USER_AGENT,
            robots=RobotsCache(client=client, user_agent=USER_AGENT),
            limiter=HostRateLimiter(delay=0.0),
            min_body_chars=min_body_chars,
            trace=trace,
        )
    return result, recorder


def _decisions(trace_path: Path, kind: str) -> list[dict]:
    return [
        record
        for record in records_of(read_trace(trace_path), "decision")
        if record["decision"] == kind
    ]


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #


def test_a_real_article_page_yields_a_document_sized_body() -> None:
    """FR-21 (i). This is the number the whole source decision rested on."""
    body = extract_body(load_text_fixture("article_arstechnica.html"))

    assert 3000 < len(body) < 12000, (
        f"extracted {len(body)} chars; the measured range on 2026-08-04 was 3,233–6,838. "
        "Far outside it means the page shape changed or the extractor regressed."
    )
    assert "\n\n" in body, "FR-22 splits on paragraph boundaries and needs them present"


def test_extraction_drops_boilerplate_blocks_whole() -> None:
    """nav/header/footer/aside/script are never article prose."""
    body = extract_body(load_text_fixture("article_paywalled.html"))

    assert "Sections" not in body
    assert "Subscribe to continue" in body, "in-article prose survives; chrome does not"
    assert "Copyright the Synthetic Times" not in body
    assert "Related:" not in body
    assert "paywall" not in body.lower() or "Subscribe" in body


def test_extraction_of_an_empty_document_is_empty_not_an_error() -> None:
    assert extract_body("") == ""
    assert extract_body("<html><body></body></html>") == ""


# --------------------------------------------------------------------------- #
# The three outcomes, none of which invents text
# --------------------------------------------------------------------------- #


def test_a_full_article_is_marked_article() -> None:
    """FR-21 (i)."""
    entry = _entry("https://arstechnica.test/story")
    result, _ = _fetch_one(
        entry,
        [ALLOW_ALL, Route(r"arstechnica\.test/story", fixture="article_arstechnica.html")],
    )

    assert result is not None
    assert result.text_source == SOURCE_ARTICLE
    assert len(result.body) > 600


def test_a_paywalled_page_falls_back_to_the_summary_verbatim(tmp_path: Path) -> None:
    """FR-21 (ii). The summary is copied, not padded, not paraphrased, not invented."""
    trace = trace_in(tmp_path, "paywall")
    entry = _entry("https://paywalled.test/story", summary="Exactly this, and nothing more.")
    result, _ = _fetch_one(
        entry,
        [ALLOW_ALL, Route(r"paywalled\.test/story", fixture="article_paywalled.html")],
        trace=trace,
    )
    trace.close()

    assert result is not None
    assert result.text_source == SOURCE_SUMMARY
    assert result.body == "Exactly this, and nothing more."

    short = _decisions(trace.path, "article_body_short")
    assert len(short) == 1
    assert "under the 600-char floor" in short[0]["reason"]


def test_a_disallowed_url_is_skipped_entirely(tmp_path: Path) -> None:
    """FR-21 (iii). Skipped, not summarized — the publisher said no."""
    trace = trace_in(tmp_path, "robots")
    entry = _entry("https://blocked.test/articles/story")
    result, recorder = _fetch_one(
        entry,
        [
            Route(r"blocked\.test/robots\.txt", fixture="robots_disallow.txt"),
            Route(r"blocked\.test/articles/", fixture="article_arstechnica.html"),
        ],
        trace=trace,
    )
    trace.close()

    assert result is None
    article_requests = [
        request for request in recorder.requests if "robots.txt" not in str(request.url)
    ]
    assert article_requests == [], "the article page must never be requested"
    assert len(_decisions(trace.path, "article_skipped")) == 1


def test_an_allowed_path_on_the_same_disallowing_host_still_fetches() -> None:
    """The robots rules are read, not just their presence noticed."""
    entry = _entry("https://blocked.test/blog/story")
    result, _ = _fetch_one(
        entry,
        [
            Route(r"blocked\.test/robots\.txt", fixture="robots_disallow.txt"),
            Route(r"blocked\.test/blog/", fixture="article_arstechnica.html"),
        ],
    )
    assert result is not None
    assert result.text_source == SOURCE_ARTICLE


def test_a_timeout_keeps_the_entry_at_summary_rather_than_dropping_it(tmp_path: Path) -> None:
    """FR-21 (iv). A slow publisher is not a reason to lose the headline."""
    trace = trace_in(tmp_path, "timeout")
    entry = _entry("https://slow.test/story", summary="Still something to say.")
    result, _ = _fetch_one(
        entry,
        [
            ALLOW_ALL,
            Route(r"slow\.test/story", exc=httpx.ReadTimeout("too slow")),
        ],
        trace=trace,
    )
    trace.close()

    assert result is not None
    assert result.text_source == SOURCE_SUMMARY
    assert result.body == "Still something to say."
    assert len(_decisions(trace.path, "article_fetch_failed")) == 1


def test_a_500_also_falls_back_rather_than_raising() -> None:
    entry = _entry("https://broken.test/story")
    result, _ = _fetch_one(
        entry,
        [ALLOW_ALL, Route(r"broken\.test/story", json_body={"e": 1}, status=500)],
    )
    assert result is not None
    assert result.text_source == SOURCE_SUMMARY


def test_no_outcome_ever_produces_a_body_that_was_not_fetched_or_summarized() -> None:
    """The FR-18 guarantee at document level, asserted over every branch."""
    cases = [
        ("article_arstechnica.html", SOURCE_ARTICLE),
        ("article_paywalled.html", SOURCE_SUMMARY),
    ]
    for fixture, expected in cases:
        entry = _entry("https://x.test/story", summary="known summary")
        result, _ = _fetch_one(
            entry, [ALLOW_ALL, Route(r"x\.test/story", fixture=fixture)]
        )
        assert result is not None
        assert result.text_source == expected
        if expected == SOURCE_SUMMARY:
            assert result.body == entry.summary


# --------------------------------------------------------------------------- #
# robots.txt goes through the injected client
# --------------------------------------------------------------------------- #


def test_robots_is_fetched_through_the_injected_client_with_the_configured_agent() -> None:
    """`RobotFileParser.read()` would open its own socket and dodge this entirely."""
    entry = _entry("https://polite.test/story")
    _, recorder = _fetch_one(
        entry,
        [
            Route(r"polite\.test/robots\.txt", text="User-agent: *\nDisallow:\n"),
            Route(r"polite\.test/story", fixture="article_arstechnica.html"),
        ],
    )

    robots_requests = [r for r in recorder.requests if "robots.txt" in str(r.url)]
    assert len(robots_requests) == 1
    assert robots_requests[0].headers["user-agent"] == USER_AGENT


def test_robots_is_fetched_once_per_host_not_once_per_article() -> None:
    client, recorder = fixture_client(
        [
            Route(r"polite\.test/robots\.txt", text="User-agent: *\nDisallow:\n"),
            Route(r"polite\.test/", fixture="article_arstechnica.html"),
        ]
    )
    robots = RobotsCache(client=client, user_agent=USER_AGENT)
    with client:
        for index in range(3):
            fetch_article_body(
                _entry(f"https://polite.test/story-{index}"),
                client=client,
                user_agent=USER_AGENT,
                robots=robots,
                limiter=HostRateLimiter(delay=0.0),
                min_body_chars=600,
            )

    assert len([r for r in recorder.requests if "robots.txt" in str(r.url)]) == 1


def test_an_unreachable_robots_file_disallows_rather_than_assuming_permission() -> None:
    """RFC 9309. "Nobody said no" and "we could not ask" are different things."""
    entry = _entry("https://unknown.test/story")
    result, recorder = _fetch_one(
        entry,
        [
            Route(r"unknown\.test/robots\.txt", json_body={"e": 1}, status=503),
            Route(r"unknown\.test/story", fixture="article_arstechnica.html"),
        ],
    )
    assert result is None
    assert [r for r in recorder.requests if "robots.txt" not in str(r.url)] == []


def test_a_404_robots_file_means_no_restrictions() -> None:
    entry = _entry("https://norobots.test/story")
    result, _ = _fetch_one(
        entry,
        [
            Route(r"norobots\.test/robots\.txt", json_body={}, status=404),
            Route(r"norobots\.test/story", fixture="article_arstechnica.html"),
        ],
    )
    assert result is not None
    assert result.text_source == SOURCE_ARTICLE


# --------------------------------------------------------------------------- #
# Rate limiting, without spending the time
# --------------------------------------------------------------------------- #


def test_the_rate_limit_waits_between_requests_to_the_same_host() -> None:
    # Clock reads, in order: first wait_for stamps 0.0; second reads 0.1 (so 0.9s of the
    # 1.0s delay is still owed); then re-reads after sleeping to re-stamp.
    ticks = iter([0.0, 0.1, 0.1])
    slept: list[float] = []
    limiter = HostRateLimiter(
        delay=1.0, sleep=slept.append, clock=lambda: next(ticks)
    )

    limiter.wait_for("https://a.test/one")
    limiter.wait_for("https://a.test/two")

    assert slept == [pytest.approx(0.9)]
    assert limiter.waits[0][0] == "a.test"


def test_the_rate_limit_does_not_wait_across_different_hosts() -> None:
    slept: list[float] = []
    limiter = HostRateLimiter(delay=1.0, sleep=slept.append, clock=lambda: 0.0)

    limiter.wait_for("https://a.test/one")
    limiter.wait_for("https://b.test/one")

    assert slept == []


def test_a_zero_delay_never_sleeps() -> None:
    slept: list[float] = []
    limiter = HostRateLimiter(delay=0.0, sleep=slept.append, clock=lambda: 0.0)
    limiter.wait_for("https://a.test/one")
    limiter.wait_for("https://a.test/two")
    assert slept == []


# --------------------------------------------------------------------------- #
# FR-21 (v) — the filter runs BEFORE the fetch
# --------------------------------------------------------------------------- #


def test_the_window_filter_runs_before_the_fetch_not_after() -> None:
    """FR-21 (v), the clause that keeps a run from making a thousand HTTP calls.

    Built in code rather than as a checked-in fixture: a 1,108-entry XML file would be
    roughly a megabyte of repo for a test whose entire subject is the *count*.
    """
    entries = [_entry(f"https://bulk.test/old-{i}", days_ago=10 + i) for i in range(1096)]
    entries += [_entry(f"https://bulk.test/new-{i}", days_ago=0.5) for i in range(12)]
    assert len(entries) == 1108

    client, recorder = fixture_client(
        [
            Route(r"bulk\.test/robots\.txt", text="User-agent: *\nDisallow:\n"),
            Route(r"bulk\.test/", fixture="article_arstechnica.html"),
        ]
    )
    with client:
        fetched = fetch_article_bodies(
            entries,
            client=client,
            user_agent=USER_AGENT,
            now=NOW,
            window_days=3,
            min_body_chars=600,
        )

    article_requests = [r for r in recorder.requests if "robots.txt" not in str(r.url)]
    assert len(article_requests) == 12, (
        f"issued {len(article_requests)} article fetches for 12 in-window entries out of "
        "1,108 — the date filter is running after the fetch, not before it"
    )
    assert len(fetched) == 12

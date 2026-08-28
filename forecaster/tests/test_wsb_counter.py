"""Step 52 — the mention counter, pure and exactly as naive as the spec says (FR-48)."""

from __future__ import annotations

from dataclasses import dataclass

from forecaster.beats.wsb import count_mentions
from forecaster.tools.feeds import parse_feed
from tests.conftest import load_text_fixture


@dataclass
class _Post:
    """The slice of FeedEntry the counter reads: url, headline, summary."""

    url: str
    headline: str
    summary: str = ""


def _posts(*pairs: tuple[str, str]) -> list[_Post]:
    return [_Post(url=f"https://r.test/{i}", headline=h, summary=s) for i, (h, s) in enumerate(pairs)]


def test_cashtag_and_bare_forms_of_one_ticker_count_across_posts() -> None:
    posts = _posts(("$NVDA to the moon", ""), ("NVDA earnings tomorrow", ""))
    table = count_mentions(posts, stoplist=[])
    assert table["NVDA"]["count"] == 2
    assert table["NVDA"]["post_urls"] == ["https://r.test/0", "https://r.test/1"]


def test_five_occurrences_in_one_title_count_once() -> None:
    posts = _posts(("GME GME GME GME GME", "and $GME again in the summary"))
    table = count_mentions(posts, stoplist=[])
    assert table["GME"]["count"] == 1


def test_a_stoplisted_token_yields_no_entry() -> None:
    posts = _posts(("YOLO into calls", ""))
    assert "YOLO" not in count_mentions(posts, stoplist=["YOLO"])
    assert "YOLO" in count_mentions(posts, stoplist=[])


def test_lowercase_bare_does_not_count_but_lowercase_cashtag_does() -> None:
    posts = _posts(("nvda looking strong", ""), ("$nvda looking strong", ""))
    table = count_mentions(posts, stoplist=[])
    assert table["NVDA"]["count"] == 1
    assert table["NVDA"]["post_urls"] == ["https://r.test/1"]


def test_token_length_bounds() -> None:
    posts = _posts(("ABCDEF is six letters and $ABCDEF is too", ""))
    assert count_mentions(posts, stoplist=[]) == {}
    posts = _posts(("F pays a dividend but bare single letters are noise", ""))
    assert count_mentions(posts, stoplist=[]) == {}
    posts = _posts(("$F pays a dividend", ""))
    assert count_mentions(posts, stoplist=[])["F"]["count"] == 1


def test_changing_the_stoplist_changes_the_result_with_no_code_edit() -> None:
    """FR-48's closing acceptance clause, run against the same input twice."""
    posts = _posts(("DD on CAKE", ""))
    loose = count_mentions(posts, stoplist=[])
    strict = count_mentions(posts, stoplist=["DD"])
    assert set(loose) == {"DD", "CAKE"}
    assert set(strict) == {"CAKE"}


def test_counts_are_posts_mentioning_with_distinct_urls() -> None:
    """The same url twice (a feed hiccup) must not inflate a count."""
    posts = [
        _Post(url="https://r.test/same", headline="$TSLA calls"),
        _Post(url="https://r.test/same", headline="TSLA puts"),
    ]
    table = count_mentions(posts, stoplist=[])
    assert table["TSLA"]["count"] == 1


def test_the_real_fixture_counts_through_the_shipped_adapter() -> None:
    """The captured hot page parses and the counter runs over real snippets."""
    entries, _ = parse_feed(
        load_text_fixture("feed_wsb.xml"), source="r/wallstreetbets", tz_name="UTC"
    )
    assert len(entries) == 25
    table = count_mentions(entries, stoplist=["DD", "YOLO", "CEO", "AI"])
    for ticker, record in table.items():
        assert record["count"] == len(set(record["post_urls"]))
        assert 1 <= len(ticker) <= 5
        urls = {entry.url for entry in entries}
        assert set(record["post_urls"]) <= urls

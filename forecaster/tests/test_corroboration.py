"""Step 37 — FR-33: corroboration is a count over a read-time relation.

Fixture construction note: the suite embeds with `HashingEmbedder`, a hashed bag of
words whose scores do not match the shipped model's. Corroborating texts here share
almost all their wording so they score near 1.0 under hashing, the unrelated text
shares none, and every assertion is on set membership — never an absolute score.
"""

from __future__ import annotations

from datetime import datetime, timezone

from forecaster.memory.corpus import (
    SCHEMA,
    chunk_article,
    connect,
    corroborating_sources,
    index_article,
)
from forecaster.memory.retrieval import HashingEmbedder
from forecaster.tools.feeds import SOURCE_ARTICLE, FeedEntry

NOW = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)
FLOOR = 0.60
WINDOW_DAYS = 2
SOURCES = ["BBC World", "NPR News", "Al Jazeera", "Texas Tribune"]

STORY = (
    "Reservoir levels across central Texas fell to record lows this week as the "
    "drought entered its third month, and state officials began preparing emergency "
    "water restrictions for the affected counties."
)
UNRELATED = (
    "A championship chess tournament opened yesterday in Reykjavik with forty-two "
    "grandmasters competing over nine rounds for the world title."
)


def _entry(url: str, source: str, body: str, *, published: str = "2026-08-14T09:00:00+00:00"):
    return FeedEntry(
        url=url,
        source=source,
        headline=body.split(",")[0][:60],
        published=datetime.fromisoformat(published),
        summary=body[:120],
        body=body,
        text_source=SOURCE_ARTICLE,
    )


def _index(conn, embedder, *entries) -> None:
    for entry in entries:
        chunks = chunk_article(
            entry.headline, entry.body, target_chars=900, max_chars=1200, overlap_chars=150
        )
        index_article(conn, entry, chunks, embedder, fetched_at=NOW)


def _corroborate(conn, url, **overrides):
    settings = {"sources": SOURCES, "floor": FLOOR, "window_days": WINDOW_DAYS, "now": NOW}
    settings.update(overrides)
    return corroborating_sources(conn, url, **settings)


def test_a_story_three_sources_carry_counts_the_other_two(tmp_path) -> None:
    conn = connect(tmp_path / "corpus.db")
    embedder = HashingEmbedder()
    _index(
        conn,
        embedder,
        _entry("https://bbc.test/reservoir", "BBC World", STORY),
        _entry("https://npr.test/reservoir", "NPR News", STORY + " Rain is not forecast."),
        _entry("https://tt.test/reservoir", "Texas Tribune", STORY + " Austin is affected."),
        _entry("https://aj.test/chess", "Al Jazeera", UNRELATED),
    )

    result = _corroborate(conn, "https://bbc.test/reservoir")

    assert set(result) == {"NPR News", "Texas Tribune"}
    npr_urls = {hit.url for hit in result["NPR News"]}
    assert npr_urls == {"https://npr.test/reservoir"}
    for hits in result.values():
        assert all(hit.chunk_id > 0 for hit in hits)


def test_an_unrelated_article_has_no_corroborators(tmp_path) -> None:
    conn = connect(tmp_path / "corpus.db")
    embedder = HashingEmbedder()
    _index(
        conn,
        embedder,
        _entry("https://aj.test/chess", "Al Jazeera", UNRELATED),
        _entry("https://bbc.test/reservoir", "BBC World", STORY),
        _entry("https://npr.test/reservoir", "NPR News", STORY),
    )

    assert _corroborate(conn, "https://aj.test/chess") == {}


def test_a_source_outside_the_supplied_list_contributes_nothing(tmp_path) -> None:
    """The shared corpus holds AI-beat articles too; they must never inflate a count."""
    conn = connect(tmp_path / "corpus.db")
    embedder = HashingEmbedder()
    _index(
        conn,
        embedder,
        _entry("https://bbc.test/reservoir", "BBC World", STORY),
        _entry("https://ars.test/reservoir", "Ars Technica", STORY),  # AI beat's tenant
    )

    assert _corroborate(conn, "https://bbc.test/reservoir") == {}


def test_two_matching_articles_from_one_source_count_that_source_once(tmp_path) -> None:
    conn = connect(tmp_path / "corpus.db")
    embedder = HashingEmbedder()
    _index(
        conn,
        embedder,
        _entry("https://bbc.test/reservoir", "BBC World", STORY),
        _entry("https://npr.test/reservoir-a", "NPR News", STORY),
        _entry("https://npr.test/reservoir-b", "NPR News", STORY + " Updated overnight."),
    )

    result = _corroborate(conn, "https://bbc.test/reservoir")

    assert set(result) == {"NPR News"}
    assert {hit.url for hit in result["NPR News"]} == {
        "https://npr.test/reservoir-a",
        "https://npr.test/reservoir-b",
    }


def test_the_candidates_own_source_never_corroborates_it(tmp_path) -> None:
    """A second article from the same outlet is repetition, not independence."""
    conn = connect(tmp_path / "corpus.db")
    embedder = HashingEmbedder()
    _index(
        conn,
        embedder,
        _entry("https://bbc.test/reservoir", "BBC World", STORY),
        _entry("https://bbc.test/reservoir-live", "BBC World", STORY + " Live updates."),
    )

    assert _corroborate(conn, "https://bbc.test/reservoir") == {}


def test_an_article_outside_the_window_contributes_nothing(tmp_path) -> None:
    conn = connect(tmp_path / "corpus.db")
    embedder = HashingEmbedder()
    _index(
        conn,
        embedder,
        _entry("https://bbc.test/reservoir", "BBC World", STORY),
        _entry(
            "https://npr.test/reservoir-old",
            "NPR News",
            STORY,
            published="2026-08-10T09:00:00+00:00",  # four days back, window is two
        ),
    )

    assert _corroborate(conn, "https://bbc.test/reservoir") == {}


def test_an_unindexed_url_and_a_cold_corpus_return_empty(tmp_path) -> None:
    """'Nothing known' is not an error — the same posture as retrieval on a cold corpus."""
    conn = connect(tmp_path / "corpus.db")
    assert _corroborate(conn, "https://bbc.test/never-indexed") == {}


def test_corroboration_stores_no_identity() -> None:
    """§9 Q3's answer, enforced: the schema gained no column, table, or hash for this.

    The literal schema is the guard — a stored story id, fingerprint, or cluster key
    would have to appear here to exist at all.
    """
    lowered = SCHEMA.lower()
    for forbidden in ("identity", "fingerprint", "hash", "cluster", "story_id", "dedup"):
        assert forbidden not in lowered
    assert "create table if not exists articles" in lowered
    assert "create table if not exists chunks" in lowered
    assert lowered.count("create table") == 2

"""Step 32 — FR-25: the news beat, assembled from Steps 25–31.

The acceptance that matters is the `ast` seam test in `test_cli.py` staying green with
this beat registered and enabled — one class plus one config entry, with no edit to
`planner.py`, `synthesizer.py`, or `delivery/`. Everything here is the behaviour behind it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from forecaster.agent import AgentResponse
from forecaster.beats.base import BeatContext, load_builtin_beats, run_beat_safely
from forecaster.beats.news import NewsBeat
from forecaster.memory import corpus as corpus_module
from forecaster.memory.retrieval import HashingEmbedder
from forecaster.trace import SYNTHESIZED, check_provenance, read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import NEWS_CONFIG, make_config, make_preferences, trace_in

load_builtin_beats()

NOW = datetime(2026, 8, 4, 19, 0, tzinfo=timezone.utc)

ARS_FEED = r"feeds\.arstechnica\.test/index"
VERGE_FEED = r"theverge\.test/rss"


class PassageClient:
    """Writes a sentence using only figures present in the passages it was handed.

    Not a stand-in for the real model's judgement — it is the FR-26 contract, executed
    deterministically, so a test can prove the check passes on honest output and fails on
    dishonest output without ever making a model call.
    """

    auth_mode = "subscription_oauth"

    def __init__(self, *, fabricate: bool = False) -> None:
        self.fabricate = fabricate
        self.calls: list[dict] = []

    def complete(self, prompt, *, structured=None, system=None, effort="low"):
        self.calls.append(dict(structured or {}))
        passages = (structured or {}).get("passages") or []
        source = passages[0]["source"] if passages else "a publication"
        if self.fabricate:
            return AgentResponse(text=f"{source} reports a score of 99.9 today.")
        # Echo a passage verbatim: every figure in it is, by construction, grounded.
        body = passages[0]["text"] if passages else ""
        return AgentResponse(text=f"Per {source}: {body[:200]}")


def _feed_xml(*items: tuple[str, str, str]) -> str:
    entries = "".join(
        f"<item><title>{title}</title><link>{url}</link>"
        f"<pubDate>{date}</pubDate><description>short</description></item>"
        for title, url, date in items
    )
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<title>Test</title>{entries}</channel></rss>"
    )


ARTICLE_HTML = (
    "<html><body><article>"
    + "".join(
        f"<p>Anthropic said the Claude model scored 71.5 on the agents benchmark, "
        f"paragraph {n}, and pricing changed accordingly for tool use and evaluations.</p>"
        for n in range(12)
    )
    + "</article></body></html>"
)

RECENT = "Mon, 03 Aug 2026 14:30:00 +0000"


def _routes():
    return [
        Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
        Route(
            ARS_FEED,
            text=_feed_xml(
                ("Claude model pricing and agents", "https://ars.test/claude", RECENT)
            ),
            content_type="application/xml",
        ),
        Route(
            VERGE_FEED,
            text=_feed_xml(
                ("Agents and tool use benchmark", "https://verge.test/agents", RECENT)
            ),
            content_type="application/xml",
        ),
        Route(r"(ars|verge)\.test/", text=ARTICLE_HTML, content_type="text/html"),
    ]


def _run(tmp_path: Path, *, client=None, routes=None, config=None):
    http, recorder = fixture_client(routes or _routes())
    trace = trace_in(tmp_path, "news")
    corpus = corpus_module.connect(tmp_path / "corpus.db")
    agent = client or PassageClient()
    with http:
        context = BeatContext(
            config=config or make_config(beats={"news": True}, news=NEWS_CONFIG),
            preferences=make_preferences(),
            now=NOW,
            scratchpad=__import__(
                "forecaster.memory.scratchpad", fromlist=["Scratchpad"]
            ).Scratchpad(trace=trace),
            trace=trace,
            http_client=http,
            embedder=HashingEmbedder(),
            corpus=corpus,
            agent_client=agent,
        )
        result = run_beat_safely(NewsBeat(), context)
        trace.beat_result(result)
    trace.digest("\n".join(item.text for item in result.items), order=["news"])
    trace.close()
    return result, trace, agent, recorder


def _decisions(trace, kind: str) -> list[dict]:
    return [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record["decision"] == kind
    ]


# --------------------------------------------------------------------------- #
# The beat produces grounded items
# --------------------------------------------------------------------------- #


def test_one_item_per_topic_that_retrieved_something(tmp_path: Path) -> None:
    result, _, _, _ = _run(tmp_path)

    assert result.available
    assert result.items, "the seeded corpus should satisfy at least one topic"
    topics = {item.fields["topic"] for item in result.items}
    assert topics <= {"claude", "agents"}


def test_every_item_links_to_the_chunks_it_was_written_from(tmp_path: Path) -> None:
    """§2(b)'s attribution metric is vacuous if this is not true."""
    result, trace, _, _ = _run(tmp_path)

    observation_ids = {
        record["observation_id"] for record in records_of(read_trace(trace.path), "observation")
    }
    for item in result.items:
        assert item.observations, f"{item.fields['topic']} item points at no passage"
        for ref in item.observations:
            assert ref.observation_id in observation_ids


def test_a_grounded_run_passes_the_provenance_check(tmp_path: Path) -> None:
    """FR-26, end to end through the real beat rather than a hand-built trace."""
    result, trace, _, _ = _run(tmp_path)
    assert result.items

    report = check_provenance(trace.path)

    assert report.ok, report.summary()


def test_a_fabricated_figure_fails_the_provenance_check(tmp_path: Path) -> None:
    """The failure FR-26 exists for, reached through the beat's own wiring."""
    result, trace, _, _ = _run(tmp_path, client=PassageClient(fabricate=True))
    assert result.items

    report = check_provenance(trace.path)

    assert not report.ok
    assert any(v.kind == "ungrounded_number" for v in report.violations), report.summary()


# --------------------------------------------------------------------------- #
# The fields contract FR-27 depends on
# --------------------------------------------------------------------------- #


def test_items_declare_only_topic_and_origin(tmp_path: Path) -> None:
    """A date, url, or source here is the bug FR-27 was written to prevent."""
    result, _, _, _ = _run(tmp_path)

    for item in result.items:
        assert set(item.fields) == {"topic", "text_origin"}
        assert item.fields["text_origin"] == SYNTHESIZED


def test_the_beat_declares_no_checkable_fields(tmp_path: Path) -> None:
    """A news item states no typed value the synthesizer copies; FR-26 polices its prose."""
    result, _, _, _ = _run(tmp_path)
    assert result.checkable_fields == {}


# --------------------------------------------------------------------------- #
# A quiet topic is recorded, not filled
# --------------------------------------------------------------------------- #


def test_a_topic_that_retrieves_nothing_emits_no_item_and_says_so(tmp_path: Path) -> None:
    config = make_config(
        beats={"news": True},
        news={
            **NEWS_CONFIG,
            "topics": [
                {"id": "claude", "query": "Anthropic Claude model pricing and agents"},
                {"id": "cheese", "query": "artisanal raw milk cheese aging caves"},
            ],
        },
    )
    result, trace, _, _ = _run(tmp_path, config=config)

    assert "cheese" not in {item.fields["topic"] for item in result.items}
    empties = _decisions(trace, "topic_empty")
    assert any(record["topic"] == "cheese" for record in empties)


def test_the_model_is_never_asked_about_a_topic_with_no_passages(tmp_path: Path) -> None:
    """Nothing fills a gap. If there is no passage, there is no sentence."""
    config = make_config(
        beats={"news": True},
        news={**NEWS_CONFIG, "topics": [{"id": "cheese", "query": "raw milk cheese caves"}]},
    )
    result, _, agent, _ = _run(tmp_path, config=config)

    assert result.items == []
    assert agent.calls == []


# --------------------------------------------------------------------------- #
# Corpus lifecycle, through the beat
# --------------------------------------------------------------------------- #


def test_the_run_purges_expired_articles_before_indexing(tmp_path: Path) -> None:
    corpus = corpus_module.connect(tmp_path / "corpus.db")
    from forecaster.tools.feeds import SOURCE_ARTICLE, FeedEntry

    stale = FeedEntry(
        url="https://old.test/story",
        source="Old",
        headline="An old story",
        published=NOW - timedelta(days=30),
        summary="",
        body="Old body text. " * 60,
        text_source=SOURCE_ARTICLE,
    )
    corpus_module.index_article(
        corpus,
        stale,
        corpus_module.chunk_article(stale.headline, stale.body, target_chars=900, max_chars=1200, overlap_chars=150),
        HashingEmbedder(),
        fetched_at=NOW - timedelta(days=30),
    )
    corpus.close()
    assert corpus_module.article_count(corpus_module.connect(tmp_path / "corpus.db")) == 1

    _run(tmp_path)

    conn = corpus_module.connect(tmp_path / "corpus.db")
    urls = {row[0] for row in conn.execute("SELECT url FROM articles")}
    assert "https://old.test/story" not in urls


# --------------------------------------------------------------------------- #
# Honest failure
# --------------------------------------------------------------------------- #


def test_the_beat_is_unavailable_when_it_is_not_wired_up(tmp_path: Path) -> None:
    """Missing embedder or corpus says so; it does not pretend the news was quiet."""
    http, _ = fixture_client(_routes())
    trace = trace_in(tmp_path, "news-unwired")
    from forecaster.memory.scratchpad import Scratchpad

    with http:
        result = run_beat_safely(
            NewsBeat(),
            BeatContext(
                config=make_config(beats={"news": True}, news=NEWS_CONFIG),
                preferences=make_preferences(),
                now=NOW,
                scratchpad=Scratchpad(trace=trace),
                trace=trace,
                http_client=http,
            ),
        )
    trace.close()

    assert result.available is False
    assert "embedder" in result.error


def test_the_beat_is_unavailable_when_news_is_unconfigured(tmp_path: Path) -> None:
    http, _ = fixture_client(_routes())
    trace = trace_in(tmp_path, "news-unconfigured")
    from forecaster.memory.scratchpad import Scratchpad

    config = make_config(beats={"news": True}, news=NEWS_CONFIG)
    object.__setattr__(config, "news", None)

    with http:
        result = run_beat_safely(
            NewsBeat(),
            BeatContext(
                config=config,
                preferences=make_preferences(),
                now=NOW,
                scratchpad=Scratchpad(trace=trace),
                trace=trace,
                http_client=http,
                embedder=HashingEmbedder(),
                corpus=corpus_module.connect(tmp_path / "corpus.db"),
                agent_client=PassageClient(),
            ),
        )
    trace.close()

    assert result.available is False
    assert "[news]" in result.error

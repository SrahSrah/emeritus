"""Step 38 — FR-31/FR-34: the beat that proves its silence.

Driven through the **real captured feeds** (BBC World, Texas Tribune — recorded live
2026-08-14 with `capture_fixture.py --raw`), so the parse-through-observe path runs over
prose nobody wrote to be convenient. The two properties that matter:

- a healthy night produces **zero digest items** and per-candidate accounting in the
  trace (or one explicit `no_candidates`) — silence is provable, not inferable;
- the model is **never** consulted: the agent client injected everywhere here raises on
  contact, and every test would fail loudly if the beat reached for it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from forecaster.beats.base import BeatContext, load_builtin_beats, run_beat_safely
from forecaster.beats.need_to_know import NeedToKnowBeat
from forecaster.memory import corpus as corpus_module
from forecaster.memory.retrieval import HashingEmbedder
from forecaster.trace import read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import NEED_TO_KNOW_CONFIG, make_config, make_preferences, trace_in

load_builtin_beats()

#: The evening the feed fixtures were captured, so their entries sit inside the
#: two-day corroboration window.
NOW = datetime(2026, 8, 14, 19, 0, tzinfo=timezone.utc)

BBC_FEED = r"feeds\.bbci\.test/"
TT_FEED = r"feeds\.texastribune\.test/"


class _no_model:
    """FR-31's zero-model-call guarantee, enforced by construction in every test."""

    auth_mode = "subscription_oauth"

    def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("the need-to-know beat must never call the model in v4")


def _routes():
    return [
        Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
        Route(BBC_FEED, fixture="feed_bbc_world.xml", content_type="application/xml"),
        Route(TT_FEED, fixture="feed_texastribune.xml", content_type="application/xml"),
        # Every article link inside the captured feeds resolves to a real captured page.
        Route(r"https://", fixture="article_texastribune.html", content_type="text/html"),
    ]


def _routes_with_dead_feed():
    return [
        Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
        Route(BBC_FEED, json_body={"error": 1}, status=500),
        Route(TT_FEED, fixture="feed_texastribune.xml", content_type="application/xml"),
        Route(r"https://", fixture="article_texastribune.html", content_type="text/html"),
    ]


def _run(tmp_path: Path, *, routes=None, now=NOW, config=None):
    http, recorder = fixture_client(routes or _routes())
    trace = trace_in(tmp_path, "need-to-know")
    corpus = corpus_module.connect(tmp_path / "corpus.db")
    with http:
        context = BeatContext(
            config=config
            or make_config(
                beats={"need_to_know": True}, need_to_know=NEED_TO_KNOW_CONFIG
            ),
            preferences=make_preferences(),
            now=now,
            scratchpad=__import__(
                "forecaster.memory.scratchpad", fromlist=["Scratchpad"]
            ).Scratchpad(trace=trace),
            trace=trace,
            http_client=http,
            embedder=HashingEmbedder(),
            corpus=corpus,
            agent_client=_no_model(),
        )
        result = run_beat_safely(NeedToKnowBeat(), context)
    trace.close()
    return result, trace, recorder


def _decisions(trace, kind: str):
    return [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record.get("decision") == kind
    ]


def _observation_ids(trace) -> set[str]:
    return {
        str(record.get("observation_id"))
        for record in records_of(read_trace(trace.path), "observation")
    }


# --------------------------------------------------------------------------- #
# The healthy night — silence, fully accounted for
# --------------------------------------------------------------------------- #


def test_a_healthy_run_emits_only_the_pulse_and_accounts_for_every_candidate(tmp_path) -> None:
    """v4 asserted zero items here; FR-39 (Step 48) made the quiet night inbox-visible.

    Nothing clears the bar on the real captures (no watchlist term, gate unmet), so the
    single permitted item is the code-assembled pulse line with its counts declared.
    """
    result, trace, _ = _run(tmp_path)

    assert result.available
    (pulse,) = result.items
    assert pulse.fields.get("text_origin") is None
    assert "Nothing cleared the need-to-know bar tonight" in pulse.text
    assert pulse.fields["as_of"] == "2026-08-14"
    assert result.checkable_fields["ntk_watched"] > 0

    observed = _decisions(trace, "corroboration_observed")
    assert observed, "the captured feeds have in-window entries; each must be accounted"
    assert _decisions(trace, "no_candidates") == []

    observation_ids = _observation_ids(trace)
    for decision in observed:
        assert str(decision.get("observation")) in observation_ids, (
            "every corroboration decision must point at a resolvable observation"
        )
        assert isinstance(decision.get("count"), int)
        assert decision.get("count") == len(decision.get("sources") or [])
        assert str(decision.get("reason", "")).strip()


def test_counts_match_the_observation_payloads(tmp_path) -> None:
    """FR-35's condition (b), proven at the source: count == distinct payload sources."""
    _, trace, _ = _run(tmp_path)
    records = read_trace(trace.path)
    payloads = {
        str(record.get("observation_id")): record.get("payload")
        for record in records_of(records, "observation")
    }
    for decision in _decisions(trace, "corroboration_observed"):
        payload = payloads[str(decision["observation"])]
        assert decision["count"] == len(payload.get("corroborators") or {})
        assert sorted(payload.get("corroborators") or {}) == decision["sources"]


def test_a_quiet_night_records_no_candidates_and_a_zero_count_pulse(tmp_path) -> None:
    """Ten days after capture, every entry is outside the window. That is quiet, not broken."""
    result, trace, _ = _run(tmp_path, now=NOW + timedelta(days=10))

    assert result.available
    (pulse,) = result.items
    assert "0 stories watched, max corroboration 0" in pulse.text
    quiet = _decisions(trace, "no_candidates")
    assert len(quiet) == 1
    assert "quiet night" in quiet[0]["reason"]
    assert _decisions(trace, "corroboration_observed") == []


def test_candidates_are_indexed_into_the_shared_corpus(tmp_path) -> None:
    from forecaster.memory.retrieval import load_vec

    _, trace, _ = _run(tmp_path)
    conn = corpus_module.connect(tmp_path / "corpus.db")
    load_vec(conn)  # vec0 is per-connection; without it the count reads as zero
    assert corpus_module.article_count(conn) > 0
    assert corpus_module.vector_count(conn) == corpus_module.chunk_count(conn)


# --------------------------------------------------------------------------- #
# Failure — FR-28 at feed granularity, FR-18 when everything is down
# --------------------------------------------------------------------------- #


def test_one_dead_feed_yields_a_dated_status_line_and_the_rest_still_observe(tmp_path) -> None:
    result, trace, _ = _run(tmp_path, routes=_routes_with_dead_feed())

    assert result.available
    assert len(result.items) == 2, "the outage line plus the FR-39 pulse"
    line = result.items[0]
    assert "BBC World" in line.text
    assert line.fields["source"] == "BBC World"
    assert line.fields["as_of"] == "2026-08-14"
    assert "Nothing cleared" in result.items[1].text

    assert len(_decisions(trace, "source_unavailable")) == 1
    assert _decisions(trace, "corroboration_observed"), (
        "the surviving source's candidates must still be observed"
    )


def test_every_feed_dead_is_the_standard_unavailable_shape(tmp_path) -> None:
    routes = [
        Route(BBC_FEED, json_body={"error": 1}, status=500),
        Route(TT_FEED, json_body={"error": 1}, status=500),
    ]
    result, _, _ = _run(tmp_path, routes=routes)

    assert result.available is False
    assert "BBC World" in (result.error or "")
    assert "Texas Tribune" in (result.error or "")
    assert result.checkable_fields == {}


def test_missing_injections_degrade_to_unavailable(tmp_path) -> None:
    trace = trace_in(tmp_path, "need-to-know-bare")
    context = BeatContext(
        config=make_config(
            beats={"need_to_know": True}, need_to_know=NEED_TO_KNOW_CONFIG
        ),
        preferences=make_preferences(),
        now=NOW,
        scratchpad=__import__(
            "forecaster.memory.scratchpad", fromlist=["Scratchpad"]
        ).Scratchpad(trace=trace),
        trace=trace,
        http_client=None,
        embedder=None,
        corpus=None,
        agent_client=_no_model(),
    )
    result = run_beat_safely(NeedToKnowBeat(), context)
    trace.close()
    assert result.available is False
    assert "embedder" in (result.error or "")


# --------------------------------------------------------------------------- #
# The seam and the flag
# --------------------------------------------------------------------------- #


def test_disabling_the_flag_removes_the_beat_from_the_run() -> None:
    from forecaster.beats.base import get_beats

    on = make_config(beats={"need_to_know": True}, need_to_know=NEED_TO_KNOW_CONFIG)
    off = make_config(need_to_know=NEED_TO_KNOW_CONFIG)
    assert "need_to_know" in [beat.name for beat in get_beats(on)]
    assert "need_to_know" not in [beat.name for beat in get_beats(off)]


def test_should_run_reads_only_the_config_flag() -> None:
    beat = NeedToKnowBeat()
    on = make_config(beats={"need_to_know": True}, need_to_know=NEED_TO_KNOW_CONFIG)
    off = make_config(need_to_know=NEED_TO_KNOW_CONFIG)

    class _Ctx:
        def __init__(self, config):
            self.config = config

    assert beat.should_run(_Ctx(on)) is True
    assert beat.should_run(_Ctx(off)) is False

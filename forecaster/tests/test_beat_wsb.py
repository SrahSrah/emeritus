"""Step 53 — FR-49/FR-50: the WSB beat, driven by the real captured hot page.

The clock is pinned to the capture evening (2026-08-28). Everything structural asserts
against the real 25-entry fixture; the degenerate states run on synthetic variants built
in the same Atom shape (declared in `tests/fixtures/README.md`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from forecaster.beats.base import BeatContext, load_builtin_beats, run_beat_safely
from forecaster.beats.wsb import ADAPTER_COUNT, WsbMentionsBeat
from forecaster.memory.scratchpad import Scratchpad
from forecaster.trace import check_provenance, read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import WSB_CONFIG, make_config, make_preferences, trace_in

load_builtin_beats()

#: The evening the real fixture was captured.
NOW = datetime(2026, 8, 28, 19, 0, tzinfo=timezone.utc)

FEED_URL = r"reddit\.test/r/wallstreetbets/\.rss"


class _no_model:
    auth_mode = "subscription_oauth"

    def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("the wsb beat must never call the model (FR-51)")


def _routes(feed: Route | None = None):
    return [feed or Route(FEED_URL, fixture="feed_wsb.xml")]


def _run(tmp_path: Path, *, routes=None, config=None, now=NOW, run_id: str = "wsb"):
    http, recorder = fixture_client(routes or _routes())
    trace = trace_in(tmp_path, run_id)
    with http:
        context = BeatContext(
            config=config or make_config(beats={"wsb": True}, wsb=WSB_CONFIG),
            preferences=make_preferences(),
            now=now,
            scratchpad=Scratchpad(trace=trace),
            trace=trace,
            http_client=http,
            embedder=None,
            corpus=None,
            agent_client=_no_model(),
        )
        result = run_beat_safely(WsbMentionsBeat(), context)
    trace.beat_result(result)
    trace.close()
    return result, trace, recorder


def _decisions(trace, *kinds: str):
    return [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record.get("decision") in kinds
    ]


def _count_observation(trace):
    records = read_trace(trace.path)
    call = next(
        record
        for record in records_of(records, "tool_call")
        if record.get("adapter") == ADAPTER_COUNT
    )
    return next(
        record
        for record in records_of(records, "observation")
        if record.get("observation_id") == call.get("observation_id")
    )


# --------------------------------------------------------------------------- #
# The counts path, on the real fixture
# --------------------------------------------------------------------------- #


def test_the_real_fixture_yields_exactly_one_item_with_checkable_counts(tmp_path) -> None:
    result, trace, _ = _run(tmp_path)

    assert result.available
    assert len(result.items) == 1
    item = result.items[0]
    assert item.fields["as_of"] == "2026-08-28"
    assert result.checkable_fields["wsb:post_total"] == 25
    for name, value in result.checkable_fields.items():
        assert str(value) in item.text, f"{name}={value!r} must appear in the text"


def test_every_delivered_count_passes_the_provenance_check(tmp_path) -> None:
    """FR-11, unmodified, polices this beat: counts and the post total are checkable."""
    result, trace, _ = _run(tmp_path)

    digest_text = "\n".join(item.text for item in result.items)
    report = check_provenance(trace.path, digest_text)
    assert report.violations == []
    assert report.checked_fields >= 2  # at least one ticker count + the post total


def test_a_tampered_count_fails_the_provenance_check(tmp_path) -> None:
    """The check has teeth: a count the counter never produced is a violation."""
    result, trace, _ = _run(tmp_path)
    top = next(
        (name, value)
        for name, value in result.checkable_fields.items()
        if name != "wsb:post_total"
    )
    digest_text = result.items[0].text.replace(
        f"in {top[1]} post", f"in {top[1] + 7} post", 1
    )
    report = check_provenance(trace.path, digest_text)
    assert report.violations, "an altered count must not pass"


def test_three_matches_under_a_top_n_of_five_reports_all_three(tmp_path) -> None:
    result, _, _ = _run(
        tmp_path,
        routes=_routes(Route(FEED_URL, fixture="feed_wsb_tied.xml")),
        config=make_config(
            beats={"wsb": True}, wsb={**WSB_CONFIG, "stoplist": ["GME"]}
        ),
    )
    # GME stoplisted → AAPL, MSFT, NVDA remain, all tied at 2, top_n = 5.
    text = result.items[0].text
    assert "AAPL mentioned in 2 posts, MSFT in 2, NVDA in 2." in text
    assert set(result.checkable_fields) == {
        "wsb:post_total", "wsb:AAPL", "wsb:MSFT", "wsb:NVDA",
    }


def test_a_tie_straddling_the_top_n_boundary_truncates_alphabetically(tmp_path) -> None:
    result, _, _ = _run(
        tmp_path,
        routes=_routes(Route(FEED_URL, fixture="feed_wsb_tied.xml")),
        config=make_config(beats={"wsb": True}, wsb={**WSB_CONFIG, "top_n": 2}),
    )
    # AAPL, MSFT, NVDA all count 2; the boundary cut is alphabetical and deterministic.
    text = result.items[0].text
    assert "AAPL mentioned in 2 posts, MSFT in 2." in text
    assert "NVDA" not in text
    assert "GME" not in text


# --------------------------------------------------------------------------- #
# FR-50 — quiet vs broken, no third state
# --------------------------------------------------------------------------- #


def test_a_zero_match_night_says_so_with_the_scanned_total(tmp_path) -> None:
    result, trace, _ = _run(
        tmp_path, routes=_routes(Route(FEED_URL, fixture="feed_wsb_nomatch.xml"))
    )

    assert result.available
    assert len(result.items) == 1
    assert result.items[0].text == (
        "No ticker mentions counted on r/wallstreetbets' hot page tonight "
        "(2 posts scanned)."
    )
    assert result.items[0].fields["as_of"] == "2026-08-28"
    assert len(_decisions(trace, "wsb_no_mentions")) == 1
    assert not _decisions(trace, "wsb_counts")


def test_a_parsed_to_zero_entries_feed_is_quiet_not_broken(tmp_path) -> None:
    result, trace, _ = _run(
        tmp_path, routes=_routes(Route(FEED_URL, fixture="feed_wsb_empty.xml"))
    )

    assert result.available
    assert "(0 posts scanned)" in result.items[0].text
    assert len(_decisions(trace, "wsb_no_mentions")) == 1


def test_a_429_is_the_fr18_shape_and_the_adapter_is_called_exactly_once(tmp_path) -> None:
    result, trace, recorder = _run(
        tmp_path, routes=_routes(Route(FEED_URL, text="Too Many Requests", status=429))
    )

    assert not result.available
    assert result.error is not None and "429" in result.error
    assert result.checkable_fields == {}
    assert result.items == []
    assert len(recorder.requests) == 1, "one request is the budget, even when refused"
    assert len(_decisions(trace, "source_unavailable")) == 1
    assert not _decisions(trace, "wsb_no_mentions", "wsb_counts")


def test_no_run_records_both_a_quiet_decision_and_an_outage(tmp_path) -> None:
    """Metric (b)'s no-third-state rule, at the unit level, across all three paths."""
    for index, (route, expected) in enumerate(
        (
            (Route(FEED_URL, fixture="feed_wsb.xml"), {"wsb_counts"}),
            (Route(FEED_URL, fixture="feed_wsb_nomatch.xml"), {"wsb_no_mentions"}),
            (Route(FEED_URL, text="nope", status=503), {"source_unavailable"}),
        )
    ):
        _, trace, _ = _run(tmp_path, routes=_routes(route), run_id=f"wsb-{index}")
        seen = {
            record["decision"]
            for record in _decisions(
                trace, "wsb_counts", "wsb_no_mentions", "source_unavailable"
            )
        }
        assert seen == expected


# --------------------------------------------------------------------------- #
# FR-49 — drops labeled honestly; disabling restores the prior shape
# --------------------------------------------------------------------------- #


def test_dropped_entries_are_labeled_wsb_and_excluded_from_the_post_total(tmp_path) -> None:
    result, trace, _ = _run(
        tmp_path,
        routes=[Route(r"malformed\.test/feed", fixture="feed_malformed.xml")],
        config=make_config(
            beats={"wsb": True},
            wsb={**WSB_CONFIG, "feed_url": "https://malformed.test/feed"},
        ),
    )

    drops = _decisions(trace, "feed_entry_dropped")
    assert drops, "the malformed fixture must produce drops"
    assert {record["beat"] for record in drops} == {"wsb"}
    # One survivor of four: the post total counts survivors only.
    assert result.checkable_fields["wsb:post_total"] == 1


def test_disabling_the_beat_returns_the_digest_to_its_prior_shape() -> None:
    from forecaster.beats.base import get_beats
    from forecaster.config import enabled_beats

    on = make_config(beats={"wsb": True}, wsb=WSB_CONFIG)
    off = make_config(beats={"wsb": False}, wsb=WSB_CONFIG)
    assert "wsb" in enabled_beats(on)
    assert "wsb" not in enabled_beats(off)
    assert "wsb" not in [beat.name for beat in get_beats(off)]


def test_the_count_observation_carries_the_full_table_and_post_total(tmp_path) -> None:
    """§6 trace contract: FR-52's hop two audits the payload, so it must be complete."""
    _, trace, _ = _run(tmp_path)

    payload = _count_observation(trace)["payload"]
    assert payload["post_total"] == 25
    for ticker, record in payload["tickers"].items():
        assert record["count"] == len(record["post_urls"])

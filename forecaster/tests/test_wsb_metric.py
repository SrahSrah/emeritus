"""Step 55 — FR-52: one fixture trace per failing condition.

Condition (c) — politeness held — is the one this beat adds to the project: the first
beat whose source enforces a request budget, audited so a retry can never creep in.
"""

from __future__ import annotations

from pathlib import Path

from forecaster.trace import Trace
from forecaster.wsb_metric import check_wsb_metric

FEED_URL = "https://www.reddit.com/r/wallstreetbets/.rss"
POSTS = [
    "https://www.reddit.com/r/wallstreetbets/comments/a/",
    "https://www.reddit.com/r/wallstreetbets/comments/b/",
]


def _write_trace(
    directory: Path,
    run_id: str,
    *,
    include_beat: bool = True,
    decision: str | None = "wsb_counts",
    available: bool = True,
    orphan_url: bool = False,
    miscount: bool = False,
    extra_reddit_fetch: bool = False,
    delivered: bool = True,
) -> Path:
    trace = Trace(run_id, directory=directory)
    trace.run_start(auth_mode="subscription_oauth", config_digest="test")

    if include_beat:
        fetch_id = trace.tool_call(
            beat="wsb", adapter="feeds.fetch_feed", arguments={"feed": "r/wallstreetbets", "url": FEED_URL}
        )
        trace.observation(
            fetch_id,
            payload={
                "feed": "r/wallstreetbets",
                "entries": [{"url": url, "headline": "$NVDA", "summary": ""} for url in POSTS],
            },
        )
        if extra_reddit_fetch:
            second = trace.tool_call(
                beat="wsb", adapter="feeds.fetch_feed", arguments={"feed": "retry", "url": FEED_URL}
            )
            trace.observation(second, error="429")

        post_urls = list(POSTS)
        if orphan_url:
            post_urls[1] = "https://www.reddit.com/r/wallstreetbets/comments/ghost/"
        count = 3 if miscount else len(post_urls)
        count_id = trace.tool_call(
            beat="wsb", adapter="wsb.count_mentions", arguments={"posts": 2, "stoplist_size": 0}
        )
        trace.observation(
            count_id,
            payload={"tickers": {"NVDA": {"count": count, "post_urls": post_urls}}, "post_total": 2},
        )
        if decision:
            trace.decision(beat="wsb", decision=decision, reason="fixture", post_total=2)
        trace._write(  # noqa: SLF001 - hand-building the record a beat would emit
            "beat_result",
            beat="wsb",
            items=[]
            if not available
            else [
                {
                    "beat": "wsb",
                    "text": "On r/wallstreetbets' hot page tonight (2 posts): NVDA mentioned in 2 posts.",
                    "fields": {"as_of": "2026-08-28", "post_total": 2},
                    "observations": [],
                }
            ],
            checkable_fields={} if not available else {"wsb:NVDA": 2, "wsb:post_total": 2},
            available=available,
            error=None if available else "couldn't read r/wallstreetbets tonight (429)",
            escalation_candidate=False,
            escalation_reason=None,
            escalation_signals={},
            observations=[],
        )
        trace.decision(
            beat="synthesizer", decision="provenance_checked", reason="checked", violations=[]
        )
        if delivered:
            trace.delivery(
                deliverer="FakeDeliverer", target="t@example.test", success=True, error=None
            )

    trace.close()
    return trace.path


def test_a_healthy_trace_passes_all_three_conditions(tmp_path: Path) -> None:
    path = _write_trace(tmp_path, "healthy")
    report = check_wsb_metric([path])

    assert report.runs_examined == 1
    assert report.ok, report.summary()


def test_an_orphaned_contributing_url_fails_condition_a(tmp_path: Path) -> None:
    path = _write_trace(tmp_path, "orphan", orphan_url=True)
    report = check_wsb_metric([path])

    assert not report.condition("count_provenance").passed
    assert report.condition("quiet_is_not_broken").passed
    assert report.condition("politeness_held").passed


def test_a_count_disagreeing_with_its_urls_fails_condition_a(tmp_path: Path) -> None:
    report = check_wsb_metric([_write_trace(tmp_path, "miscount", miscount=True)])
    assert not report.condition("count_provenance").passed


def test_a_run_with_no_state_fails_condition_b(tmp_path: Path) -> None:
    path = _write_trace(tmp_path, "silent", decision=None)
    report = check_wsb_metric([path])

    assert not report.condition("quiet_is_not_broken").passed
    assert report.condition("count_provenance").passed
    assert report.condition("politeness_held").passed


def test_an_unavailable_run_with_no_decision_is_one_honest_state(tmp_path: Path) -> None:
    """The FR-18 shape alone is a valid state — broken, said loudly, exactly once."""
    path = _write_trace(tmp_path, "outage", decision=None, available=False)
    report = check_wsb_metric([path])
    assert report.condition("quiet_is_not_broken").passed


def test_two_reddit_fetches_in_one_run_fail_condition_c(tmp_path: Path) -> None:
    path = _write_trace(tmp_path, "retry", extra_reddit_fetch=True)
    report = check_wsb_metric([path])

    assert not report.condition("politeness_held").passed
    assert report.condition("quiet_is_not_broken").passed


def test_a_trace_without_the_beat_reports_na_not_pass(tmp_path: Path) -> None:
    path = _write_trace(tmp_path, "disabled", include_beat=False)
    report = check_wsb_metric([path])

    assert report.runs_examined == 0
    for condition in report.conditions:
        assert not condition.applicable
        assert "no examined run" in condition.detail
    assert report.ok, "n/a is not a failure — but it is asserted as not-applicable"


def test_the_summary_names_each_failing_condition(tmp_path: Path) -> None:
    paths = [
        _write_trace(tmp_path, "bad-a", orphan_url=True),
        _write_trace(tmp_path, "bad-b", decision=None),
        _write_trace(tmp_path, "bad-c", extra_reddit_fetch=True),
    ]
    report = check_wsb_metric(paths)
    summary = report.summary()

    assert "FAIL" in summary
    assert "ghost" in summary or "absent from tonight's fetch" in summary
    assert "exactly one" in summary
    assert "one request per night" in summary

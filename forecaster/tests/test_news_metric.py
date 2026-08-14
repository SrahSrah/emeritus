"""Step 34 — FR-29: PRD §2's four news conditions, computed from traces alone.

One fixture trace per condition, each violating exactly one, so a failure names the thing
that actually broke rather than "the metric is red".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.news_metric import TARGET_NIGHTS, check_news_metric, trace_files
from forecaster.trace import Trace

CHUNK = "Anthropic said the model scored 71.5 on the benchmark, up from 64."


def _write_trace(
    directory: Path,
    run_id: str,
    *,
    items: list[dict] | None = None,
    dedup: list[tuple[str, str]] | None = None,
    preference: int = 0,
    violations: list[str] | None = None,
    at: str | None = None,
    delivered: bool = True,
) -> Path:
    """One synthetic news run. Everything the checker reads and nothing else."""
    trace = Trace(run_id, directory=directory)
    trace.run_start(auth_mode="subscription_oauth", config_digest="test")

    observation_id = trace.tool_call(
        beat="news", adapter="corpus.retrieve_for_topic", arguments={"topic": "claude"}
    )
    trace.observation(observation_id, payload=CHUNK)

    resolved = []
    for item in items if items is not None else [{"text": "Per Ars: 71.5.", "linked": True}]:
        resolved.append(
            {
                "beat": "news",
                "text": item["text"],
                "fields": {"topic": "claude", "text_origin": "synthesized"},
                "observations": [observation_id] if item.get("linked", True) else
                (["obs-9999"] if item.get("dangling") else []),
            }
        )

    trace._write(  # noqa: SLF001 - hand-building the record a beat would emit
        "beat_result",
        beat="news",
        items=resolved,
        checkable_fields={},
        available=True,
        error=None,
        escalation_candidate=False,
        escalation_reason=None,
        escalation_signals={},
        observations=[],
    )

    for action, reason in dedup or []:
        trace.decision(beat="news", decision=f"dedup_{action}", reason=reason)
    for index in range(preference):
        trace.decision(
            beat="news", decision="item_suppressed", reason=f"rule {index} fired"
        )

    trace.decision(
        beat="synthesizer",
        decision="provenance_checked",
        reason="checked",
        violations=violations or [],
    )
    # A run that reached delivery. Condition (a) only looks at delivered runs, because
    # §2(a) is about claims that appear in a digest and an undelivered run produced none.
    if delivered:
        trace.delivery(
            deliverer="FakeDeliverer", target="x@y.z", success=True, error=None
        )
    trace.digest("Per Ars: 71.5.", order=["news"])
    trace.close()

    if at is not None:
        # Rewrite the run_start timestamp so a test can simulate separate nights.
        text = trace.path.read_text(encoding="utf-8").splitlines()
        text[0] = text[0].replace(text[0].split('"at": "')[1].split('"')[0], at)
        trace.path.write_text("\n".join(text) + "\n", encoding="utf-8")
    return trace.path


def _healthy(directory: Path, run_id: str = "run-1", **overrides) -> Path:
    settings: dict = {
        "items": [{"text": "Per Ars: 71.5.", "linked": True}],
        "dedup": [("include", "new information")],
    }
    settings.update(overrides)
    return _write_trace(directory, run_id, **settings)


# --------------------------------------------------------------------------- #
# All four pass
# --------------------------------------------------------------------------- #


def test_a_healthy_run_passes_a_b_and_d(tmp_path: Path) -> None:
    report = check_news_metric([_healthy(tmp_path)])

    assert report.condition("grounded_prose").passed
    assert report.condition("attribution").passed
    assert report.condition("no_silent_loss").passed
    assert report.runs_examined == 1


# --------------------------------------------------------------------------- #
# One fixture per condition, each violating exactly one
# --------------------------------------------------------------------------- #


def test_an_ungrounded_number_fails_only_condition_a(tmp_path: Path) -> None:
    path = _healthy(
        tmp_path, violations=["[ungrounded_number] news.text: value '99.9' not in any passage"]
    )
    report = check_news_metric([path])

    assert not report.condition("grounded_prose").passed
    assert report.condition("attribution").passed
    assert report.condition("no_silent_loss").passed


def test_an_unattributed_item_fails_only_condition_b(tmp_path: Path) -> None:
    path = _healthy(tmp_path, items=[{"text": "Something happened.", "linked": False}])
    report = check_news_metric([path])

    assert not report.condition("attribution").passed
    assert report.condition("grounded_prose").passed


def test_a_dangling_observation_id_also_fails_condition_b(tmp_path: Path) -> None:
    """Pointing at an observation that is not in the trace is not attribution."""
    path = _healthy(
        tmp_path, items=[{"text": "Something happened.", "linked": False, "dangling": True}]
    )
    report = check_news_metric([path])

    assert not report.condition("attribution").passed
    assert "unresolvable" in report.condition("attribution").detail


def test_an_unaccounted_item_fails_only_condition_d(tmp_path: Path) -> None:
    """Two items produced, one outcome recorded — one vanished without a reason."""
    path = _healthy(
        tmp_path,
        items=[
            {"text": "Per Ars: 71.5.", "linked": True},
            {"text": "Per Verge: 64.", "linked": True},
        ],
        dedup=[("include", "new information")],
    )
    report = check_news_metric([path])

    assert not report.condition("no_silent_loss").passed
    assert "2 item(s) produced but 1 outcome(s)" in report.condition("no_silent_loss").detail
    assert report.condition("grounded_prose").passed
    assert report.condition("attribution").passed


def test_a_suppression_with_no_reason_fails_condition_d(tmp_path: Path) -> None:
    path = _healthy(tmp_path, dedup=[("suppress", "   ")])
    report = check_news_metric([path])

    assert not report.condition("no_silent_loss").passed
    assert "no reason" in report.condition("no_silent_loss").detail


# --------------------------------------------------------------------------- #
# (c) — the condition that cannot be met by a single run
# --------------------------------------------------------------------------- #


def test_condition_c_reports_progress_and_never_claims_it_early(tmp_path: Path) -> None:
    path = _healthy(tmp_path, dedup=[("suppress", "you were told this last night")])
    report = check_news_metric([path])

    condition = report.condition("organic_dedup")
    assert f"1 of {TARGET_NIGHTS} night(s)" in condition.detail
    assert "1 suppression(s)/reframe(s)" in condition.detail
    # TARGET_NIGHTS was lowered to 1 on 2026-08-13 so the condition can be exercised at
    # all — see DIVERGENCES row 9. One night plus one suppression now satisfies it, which
    # is a far weaker claim than the fourteen nights parent §2(c) asks for.
    assert condition.passed is (report.nights_accumulated >= TARGET_NIGHTS)


def test_condition_c_needs_both_the_nights_and_a_suppression(tmp_path: Path) -> None:
    """Fourteen quiet nights are not evidence that dedup does anything."""
    paths = [
        _healthy(tmp_path, f"run-{index}", at=f"2026-07-{index + 1:02d}T19:00:00+00:00")
        for index in range(TARGET_NIGHTS)
    ]
    report = check_news_metric(paths)

    assert report.nights_accumulated == TARGET_NIGHTS
    assert not report.condition("organic_dedup").passed, "no suppression ever happened"


def test_condition_c_always_carries_the_organic_caveat(tmp_path: Path) -> None:
    """The checker cannot see where the ledger's rows came from, and says so."""
    report = check_news_metric([_healthy(tmp_path)])

    assert any("ORGANIC" in caveat for caveat in report.caveats)
    assert any("DIVERGENCES row 4" in caveat for caveat in report.caveats)


# --------------------------------------------------------------------------- #
# Edges
# --------------------------------------------------------------------------- #


def test_no_traces_at_all_does_not_error(tmp_path: Path) -> None:
    report = check_news_metric(trace_files(tmp_path / "nothing-here"))

    assert report.runs_examined == 0
    assert report.summary()


def test_a_run_with_no_news_beat_is_skipped(tmp_path: Path) -> None:
    trace = Trace("no-news", directory=tmp_path)
    trace.run_start(auth_mode="subscription_oauth", config_digest="test")
    trace.digest("Astros won.", order=["astros"])
    trace.close()

    report = check_news_metric([trace.path])

    assert report.runs_examined == 0


def test_condition_d_is_not_applicable_when_retrieval_was_off(tmp_path: Path) -> None:
    """An `n/a` is not a pass — a run that assessed nothing proves nothing."""
    path = _healthy(tmp_path, dedup=[])
    report = check_news_metric([path])

    condition = report.condition("no_silent_loss")
    assert condition.applicable is False
    assert condition.status == "n/a"
    assert "retrieval was off" in condition.detail


def test_an_unreadable_trace_is_a_caveat_not_a_crash(tmp_path: Path) -> None:
    broken = tmp_path / "broken.jsonl"
    broken.write_text("{not json at all\n", encoding="utf-8")

    report = check_news_metric([_healthy(tmp_path), broken])

    assert report.runs_examined == 1
    assert any("broken.jsonl" in caveat for caveat in report.caveats)


def test_the_report_summary_names_every_condition(tmp_path: Path) -> None:
    summary = check_news_metric([_healthy(tmp_path)]).summary()

    for fragment in ("(a) grounded prose", "(b) retrieval attribution",
                     "(c) organic dedup", "(d) no silent loss"):
        assert fragment in summary


# --------------------------------------------------------------------------- #
# (a) reads the FINAL verdict, and only from runs that delivered
# --------------------------------------------------------------------------- #
#
# Found 2026-08-13. FR-30 changed what a violation means: the item is withheld and the
# run recomposes, so the first `provenance_checked` record is a superseded answer by
# construction. Reading it reported FAIL against three runs that delivered nothing and
# one item that was withheld exactly as designed.


def _verdict_trace(
    tmp_path: Path,
    *,
    checked: list[str],
    rechecked: list[str] | None = None,
    delivered: bool | None = True,
    name: str = "verdict",
) -> Path:
    """A news run with a chosen provenance history and delivery outcome."""
    trace = Trace(name, directory=tmp_path)
    trace.run_start(auth_mode="subscription_oauth", config_digest="t")
    observation_id = trace.tool_call(
        beat="news", adapter="corpus.retrieve_for_topic", arguments={"topic": "t"}
    )
    trace.observation(observation_id, payload="a passage")
    trace._write(  # noqa: SLF001
        "beat_result",
        beat="news",
        items=[
            {
                "beat": "news",
                "text": "a line",
                "fields": {"topic": "t", "text_origin": "synthesized"},
                "observations": [observation_id],
            }
        ],
        checkable_fields={},
        available=True,
        error=None,
        escalation_candidate=False,
        escalation_reason=None,
        escalation_signals={},
        observations=[observation_id],
    )
    trace.decision(
        beat="synthesizer", decision="provenance_checked", reason="r", violations=checked
    )
    if rechecked is not None:
        trace.decision(
            beat="synthesizer",
            decision="provenance_rechecked",
            reason="r",
            violations=rechecked,
        )
    if delivered is not None:
        trace.delivery(
            deliverer="FakeDeliverer", target="x@y.z", success=delivered, error=None
        )
    trace.digest("a line", order=["news"])
    trace.close()
    return trace.path


VIOLATION = "[ungrounded_number] news.text: item text states '99.9', which appears in none"


def test_an_undelivered_run_contributes_nothing_to_a(tmp_path: Path) -> None:
    """Three real runs on 2026-08-04 failed provenance and sent nothing at all."""
    path = _verdict_trace(tmp_path, checked=[VIOLATION], delivered=None)

    assert check_news_metric([path]).condition("grounded_prose").passed


def test_a_withheld_item_contributes_nothing_to_a(tmp_path: Path) -> None:
    """The core case: FR-30 caught it, withheld it, and the digest went out clean.

    This fires every time the guard works as designed, which is far more often than a
    fatal violation.
    """
    path = _verdict_trace(tmp_path, checked=[VIOLATION], rechecked=[])

    assert check_news_metric([path]).condition("grounded_prose").passed


def test_a_delivered_ungrounded_claim_still_fails_a(tmp_path: Path) -> None:
    """The requirement is unchanged. Only its scope moved."""
    path = _verdict_trace(tmp_path, checked=[VIOLATION])

    report = check_news_metric([path])

    assert not report.condition("grounded_prose").passed
    assert "99.9" in report.condition("grounded_prose").detail


def test_a_failed_delivery_contributes_nothing_to_a(tmp_path: Path) -> None:
    path = _verdict_trace(tmp_path, checked=[VIOLATION], delivered=False)

    assert check_news_metric([path]).condition("grounded_prose").passed


def test_a_quarantine_does_not_break_condition_d(tmp_path: Path) -> None:
    """Pinning a non-bug, because the reasoning is easy to get backwards.

    While speccing this I concluded FR-30 had broken (d) — it counts outcomes as
    `dedup_* + item_suppressed` and FR-30 added `item_quarantined`. Measuring it showed
    otherwise: **dedup runs before the provenance check**, so a quarantined item already
    carries a `dedup_include` and `accounted == produced` still holds. Do not "fix" it.
    """
    trace = Trace("quarantine-d", directory=tmp_path)
    trace.run_start(auth_mode="subscription_oauth", config_digest="t")
    observation_id = trace.tool_call(beat="news", adapter="corpus", arguments={})
    trace.observation(observation_id, payload="a passage")
    trace._write(  # noqa: SLF001
        "beat_result",
        beat="news",
        items=[
            {
                "beat": "news",
                "text": f"line {index}",
                "fields": {"topic": str(index), "text_origin": "synthesized"},
                "observations": [observation_id],
            }
            for index in range(2)
        ],
        checkable_fields={},
        available=True,
        error=None,
        escalation_candidate=False,
        escalation_reason=None,
        escalation_signals={},
        observations=[observation_id],
    )
    for index in range(2):
        trace.decision(beat="news", decision="dedup_include", reason=f"new {index}")
    trace.decision(beat="news", decision="item_quarantined", reason="withheld")
    trace.decision(beat="synthesizer", decision="provenance_rechecked", reason="ok", violations=[])
    trace.delivery(deliverer="FakeDeliverer", target="x@y.z", success=True, error=None)
    trace.digest("line 0", order=["news"])
    trace.close()

    report = check_news_metric([trace.path])

    assert report.condition("no_silent_loss").passed, report.condition("no_silent_loss").detail

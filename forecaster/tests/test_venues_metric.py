"""Step 44 — FR-46: one fixture trace per failing condition.

Condition (b) — never suppressed — is the one this beat adds to the project: the
inverse of every other beat's dedup expectations, auditing the repeats-are-deliberate
requirement instead of hoping about it.
"""

from __future__ import annotations

from pathlib import Path

from forecaster.trace import Trace
from forecaster.venues_metric import check_venues_metric


def _write_trace(
    directory: Path,
    run_id: str,
    *,
    include_beat: bool = True,
    items: int = 2,
    available: bool = True,
    decision: str = "venue_listed",
    dedup_ran: bool = True,
    exempt_records: int | None = None,
    suppress_a_venue_item: bool = False,
    provenance_violations: list[str] | None = None,
    delivered: bool = True,
) -> Path:
    trace = Trace(run_id, directory=directory)
    trace.run_start(auth_mode="subscription_oauth", config_digest="test")

    if include_beat:
        listing = {
            "beat": "venues",
            "text": 'At ZACH Theatre: "Sally and Tom" — dates on the venue site.',
            "fields": {"venue": "ZACH Theatre", "as_of": "2026-08-16"},
            "observations": [],
        }
        trace._write(  # noqa: SLF001 - hand-building the record a beat would emit
            "beat_result",
            beat="venues",
            items=[dict(listing) for _ in range(items)],
            checkable_fields={},
            available=available,
            error=None if available else "every configured venue failed",
            escalation_candidate=False,
            escalation_reason=None,
            escalation_signals={},
            observations=[],
        )
        if available and decision:
            trace.decision(
                beat="venues", decision=decision, reason="fixture", venue="ZACH Theatre"
            )
        if dedup_ran:
            count = items if exempt_records is None else exempt_records
            for _ in range(count):
                trace.decision(
                    beat="venues",
                    decision="dedup_exempt",
                    reason="beat opts out by config; repeats are deliberate",
                    forced=True,
                )
            trace.decision(beat="news", decision="dedup_include", reason="fixture")
        if suppress_a_venue_item:
            trace.decision(
                beat="venues", decision="dedup_suppress", reason="should never happen"
            )
        trace.decision(
            beat="synthesizer",
            decision="provenance_checked",
            reason="checked",
            violations=provenance_violations or [],
        )
        if delivered:
            trace.delivery(
                deliverer="FakeDeliverer", target="t@example.test", success=True, error=None
            )

    trace.close()
    return trace.path


def test_all_three_conditions_pass_over_a_clean_run(tmp_path) -> None:
    report = check_venues_metric([_write_trace(tmp_path, "good")])
    assert report.ok and report.runs_examined == 1
    for key in ("listing_provenance", "never_suppressed", "quiet_is_explicit"):
        assert report.condition(key).passed


def test_a_suppressed_venue_item_fails_condition_b(tmp_path) -> None:
    path = _write_trace(tmp_path, "suppressed", suppress_a_venue_item=True)
    report = check_venues_metric([path])
    condition = report.condition("never_suppressed")
    assert not condition.passed
    assert "dedup_suppress" in condition.detail
    assert report.condition("quiet_is_explicit").passed, "only (b) may fail here"


def test_a_repeat_without_its_exempt_record_fails_condition_b(tmp_path) -> None:
    """Repeats must be deliberate, on the record — not a dedup outage that happens to repeat."""
    path = _write_trace(tmp_path, "unrecorded", exempt_records=0)
    report = check_venues_metric([path])
    assert not report.condition("never_suppressed").passed
    assert "deliberate" in report.condition("never_suppressed").detail


def test_a_venue_provenance_violation_fails_condition_a(tmp_path) -> None:
    path = _write_trace(
        tmp_path,
        "tampered",
        provenance_violations=["unsupported_claim: venues.ZACH Theatre:0:dates"],
    )
    report = check_venues_metric([path])
    assert not report.condition("listing_provenance").passed
    assert report.condition("never_suppressed").passed, "only (a) may fail here"


def test_an_available_run_with_nothing_to_say_fails_condition_c(tmp_path) -> None:
    """The collapsed state FR-45 forbids: available, itemless, decisionless."""
    path = _write_trace(tmp_path, "silent", items=0, decision="", dedup_ran=False)
    report = check_venues_metric([path])
    condition = report.condition("quiet_is_explicit")
    assert not condition.passed
    assert "collapsed" in condition.detail


def test_an_unavailable_run_is_accounted_by_the_fr18_shape(tmp_path) -> None:
    path = _write_trace(tmp_path, "outage", available=False, decision="", dedup_ran=False)
    report = check_venues_metric([path])
    assert report.condition("quiet_is_explicit").passed


def test_a_run_without_the_beat_reports_not_applicable(tmp_path) -> None:
    path = _write_trace(tmp_path, "absent", include_beat=False)
    report = check_venues_metric([path])
    assert report.runs_examined == 0
    for condition in report.conditions:
        assert condition.applicable is False and condition.status == "n/a"
    assert report.ok


def test_the_cli_flag_reports_and_exits_cleanly(tmp_path, monkeypatch, capsys) -> None:
    import forecaster.trace as trace_module
    from forecaster.cli import main

    monkeypatch.setattr(trace_module, "DEFAULT_RUN_DIR", tmp_path)
    _write_trace(tmp_path, "cli-run")

    assert main(["--venues-metric"]) == 0
    out = capsys.readouterr().out
    assert "venues metric" in out
    assert "never suppressed" in out

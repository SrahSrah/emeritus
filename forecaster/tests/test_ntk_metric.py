"""Step 39 — FR-35: the observation metric, one fixture trace per failing condition.

The checker's whole job is telling a quiet beat from a broken one, so the fixtures are
built in pairs: the same run shape with and without its accounting.
"""

from __future__ import annotations

from pathlib import Path

from forecaster.ntk_metric import TARGET_NIGHTS, check_ntk_metric
from forecaster.trace import Trace


def _write_trace(
    directory: Path,
    run_id: str,
    *,
    candidates: list[dict] | None = None,
    quiet_decisions: int = 0,
    available: bool = True,
    include_beat: bool = True,
    break_count: bool = False,
    dangling_observation: bool = False,
    at: str = "2026-08-16T19:00:00+00:00",
) -> Path:
    """One synthetic need-to-know run. Everything the checker reads and nothing else.

    ``at`` pins the night — `_write` lets an explicit timestamp override its stamp — so
    the two-night gate (TARGET_NIGHTS, Sarah's 2026-08-16 call) is testable without two
    real evenings.
    """
    trace = Trace(run_id, directory=directory)
    trace.run_start(auth_mode="subscription_oauth", config_digest="test", at=at)

    if include_beat:
        for candidate in candidates or []:
            observation_id = trace.tool_call(
                beat="need_to_know",
                adapter="corpus.corroborating_sources",
                arguments={"url": candidate["url"]},
            )
            corroborators = {
                source: [{"source": source, "chunk_id": 1, "url": "https://x.test", "similarity": 0.9}]
                for source in candidate.get("sources", [])
            }
            trace.observation(
                observation_id,
                payload={
                    "url": candidate["url"],
                    "source": candidate.get("source", "BBC World"),
                    "text_source": candidate.get("text_source", "article"),
                    "corroborators": corroborators,
                },
            )
            trace.decision(
                beat="need_to_know",
                decision="corroboration_observed",
                reason="observed",
                url=candidate["url"],
                source=candidate.get("source", "BBC World"),
                count=(
                    len(corroborators) + 1 if break_count else len(corroborators)
                ),
                sources=sorted(corroborators),
                observation="obs-9999" if dangling_observation else observation_id,
            )

        for _ in range(quiet_decisions):
            trace.decision(
                beat="need_to_know",
                decision="no_candidates",
                reason="a quiet night, recorded rather than filled",
            )

        trace._write(  # noqa: SLF001 - hand-building the record a beat would emit
            "beat_result",
            beat="need_to_know",
            items=[],
            checkable_fields={},
            available=available,
            error=None if available else "every configured need-to-know source failed",
            escalation_candidate=False,
            escalation_reason=None,
            escalation_signals={},
            observations=[],
        )

    trace.close()
    return trace.path


CANDIDATE = {"url": "https://bbc.test/story", "sources": ["NPR News", "Texas Tribune"]}


def test_all_three_conditions_pass_over_two_accounted_nights(tmp_path) -> None:
    """TARGET_NIGHTS is 2 (Sarah, 2026-08-16), so the pass case needs two nights."""
    first = _write_trace(
        tmp_path, "night-one", candidates=[CANDIDATE], at="2026-08-15T19:00:00+00:00"
    )
    second = _write_trace(
        tmp_path, "night-two", candidates=[CANDIDATE], at="2026-08-16T19:00:00+00:00"
    )
    report = check_ntk_metric([first, second])

    assert report.ok
    assert report.runs_examined == 2
    assert report.nights_accumulated == 2
    assert report.condition("silence_accounted").passed
    assert report.condition("count_provenance").passed
    assert report.condition("evidence_accumulates").passed


def test_one_night_is_not_yet_evidence(tmp_path) -> None:
    """The gate has a point: a single evening must report itself as short."""
    path = _write_trace(tmp_path, "good", candidates=[CANDIDATE])
    report = check_ntk_metric([path])

    assert report.condition("silence_accounted").passed
    assert report.condition("count_provenance").passed
    condition = report.condition("evidence_accumulates")
    assert not condition.passed
    assert f"1 of {TARGET_NIGHTS}" in condition.detail


def test_a_quiet_night_with_its_decision_passes(tmp_path) -> None:
    path = _write_trace(tmp_path, "quiet", quiet_decisions=1)
    report = check_ntk_metric([path])

    assert report.condition("silence_accounted").passed
    # No candidates means no distribution night — (c) reports honestly short.
    assert report.condition("evidence_accumulates").passed is (TARGET_NIGHTS == 0)


def test_unaccounted_silence_fails_condition_a(tmp_path) -> None:
    """The broken-vs-quiet discriminator: available, but the trace proves nothing."""
    path = _write_trace(tmp_path, "silent")
    report = check_ntk_metric([path])

    condition = report.condition("silence_accounted")
    assert condition.applicable and not condition.passed
    assert "unaccounted" in condition.detail
    assert report.condition("count_provenance").passed, "only (a) may fail here"


def test_an_unavailable_run_is_accounted_by_the_fr18_shape(tmp_path) -> None:
    path = _write_trace(tmp_path, "outage", available=False)
    report = check_ntk_metric([path])
    assert report.condition("silence_accounted").passed


def test_a_count_that_disagrees_with_its_observation_fails_condition_b(tmp_path) -> None:
    path = _write_trace(tmp_path, "bad-count", candidates=[CANDIDATE], break_count=True)
    report = check_ntk_metric([path])

    condition = report.condition("count_provenance")
    assert not condition.passed
    assert "count=" in condition.detail
    assert report.condition("silence_accounted").passed, "only (b) may fail here"


def test_a_dangling_observation_fails_condition_b(tmp_path) -> None:
    path = _write_trace(
        tmp_path, "dangling", candidates=[CANDIDATE], dangling_observation=True
    )
    report = check_ntk_metric([path])
    assert not report.condition("count_provenance").passed
    assert "no observation" in report.condition("count_provenance").detail


def test_a_run_without_the_beat_reports_not_applicable(tmp_path) -> None:
    """A disabled beat proves nothing either way — n/a, never pass."""
    path = _write_trace(tmp_path, "absent", include_beat=False)
    report = check_ntk_metric([path])

    assert report.runs_examined == 0
    for condition in report.conditions:
        assert condition.applicable is False
        assert condition.status == "n/a"
    assert report.ok, "n/a conditions cannot fail a report that examined nothing"


def test_the_distribution_and_text_source_split_are_reported(tmp_path) -> None:
    path = _write_trace(
        tmp_path,
        "dist",
        candidates=[
            CANDIDATE,
            {"url": "https://tt.test/story", "source": "Texas Tribune", "sources": [], "text_source": "summary"},
        ],
    )
    report = check_ntk_metric([path])

    (night,) = report.distribution
    assert sorted(report.distribution[night]) == [0, 2]
    assert report.text_sources["BBC World"] == {"article": 1}
    assert report.text_sources["Texas Tribune"] == {"summary": 1}
    summary = report.summary()
    assert "not a result" in summary
    assert "DIVERGENCES row 9" in summary


def test_the_cli_flag_reports_and_exits_cleanly(tmp_path, monkeypatch, capsys) -> None:
    import forecaster.trace as trace_module
    from forecaster.cli import main

    monkeypatch.setattr(trace_module, "DEFAULT_RUN_DIR", tmp_path)
    _write_trace(tmp_path, "cli-run", candidates=[CANDIDATE])

    assert main(["--ntk-metric"]) == 0
    out = capsys.readouterr().out
    assert "need-to-know metric" in out
    assert "corroboration distribution" in out

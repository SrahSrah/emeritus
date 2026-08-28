"""Step 18 — the three end-to-end acceptance criteria: FR-1, FR-2, FR-13.

Everything runs off recorded fixtures with `FakeDeliverer` and `FakeAgentClient`. The
suite makes no network call and no model call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.agent import FakeAgentClient
from forecaster.beats.base import (
    BeatContext,
    BeatItem,
    BeatResult,
    load_builtin_beats,
    register_beat,
    unregister_beat,
)
from forecaster.cli import build_parser, main, run_pipeline
from forecaster.delivery.base import FakeDeliverer
from forecaster.memory.ledger import all_rows
from forecaster.memory.preferences import parse_preferences
from forecaster.trace import check_provenance, read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import (
    HOURLY_URL,
    NOW,
    POINTS_URL,
    SCHEDULE_URL,
    make_config,
)

load_builtin_beats()

PREFS = parse_preferences({"topics": {"astros": 1.0, "weather": 1.0}})

HAPPY_ROUTES = [
    Route(r"date=2026-07-27", fixture="mlb_final"),
    Route(r"startDate=", fixture="mlb_preview"),
    Route(POINTS_URL, fixture="nws_points_austin"),
    Route(HOURLY_URL, fixture="nws_hourly_austin"),
]


def _run(tmp_path: Path, *, config=None, routes=None, beats=None, prefs=None):
    client, recorder = fixture_client(routes if routes is not None else HAPPY_ROUTES)
    deliverer = FakeDeliverer(target="nobody@example.test")
    agent = FakeAgentClient()
    with client:
        report = run_pipeline(
            config or make_config(),
            prefs or PREFS,
            agent_client=agent,
            deliverer=deliverer,
            http_client=client,
            now=NOW,
            trace_dir=tmp_path / "runs",
            ledger_path=tmp_path / "ledger.db",
            beats=beats,
        )
    return report, deliverer, agent, recorder


# --------------------------------------------------------------------------- #
# FR-1 — config alone decides which beats execute
# --------------------------------------------------------------------------- #


def test_running_the_pipeline_twice_with_two_configs_executes_different_beat_sets(
    tmp_path: Path,
) -> None:
    both, _, _, _ = _run(tmp_path, config=make_config())
    astros_only, _, _, _ = _run(
        tmp_path, config=make_config(beats={"astros": True, "weather": False})
    )

    assert both.executed_beats == ["astros", "weather"]
    assert astros_only.executed_beats == ["astros"]
    assert both.executed_beats != astros_only.executed_beats

    # And the difference shows up in what was delivered, not just in bookkeeping.
    assert "Run window" in both.text
    assert "Run window" not in astros_only.text


# --------------------------------------------------------------------------- #
# FR-2 — a dummy beat is visible in the output, with zero edits elsewhere
# --------------------------------------------------------------------------- #


class DummyBeat:
    """One class. The only other change is one line in `[beats]`."""

    name = "dummy"
    completion_criterion = "dummy said its piece"

    def should_run(self, context: BeatContext) -> bool:
        return bool(context.config.beats.get(self.name, False))

    def run(self, context: BeatContext) -> BeatResult:
        observation_id = context.trace.tool_call(
            beat=self.name, adapter="dummy.source", arguments={}
        )
        context.trace.observation(observation_id, payload={"headline": "dummy reporting in"})
        return BeatResult(
            beat=self.name,
            items=[BeatItem(beat=self.name, text="dummy reporting in")],
        )


def test_a_dummy_beat_appears_in_the_delivered_digest(tmp_path: Path) -> None:
    register_beat(DummyBeat)
    try:
        report, deliverer, _, _ = _run(
            tmp_path,
            config=make_config(beats={"astros": False, "weather": False, "dummy": True}),
            routes=HAPPY_ROUTES,
            prefs=parse_preferences({"topics": {"dummy": 1.0}}),
        )
    finally:
        unregister_beat("dummy")

    assert report.executed_beats == ["dummy"]
    assert "dummy reporting in" in report.text
    assert "dummy reporting in" in (deliverer.last_text or "")


def test_adding_the_dummy_beat_required_no_edit_to_planner_synthesizer_or_delivery() -> None:
    """The claim, checked mechanically: none of the three names a concrete beat."""
    import ast

    package = Path(__file__).resolve().parent.parent / "forecaster"
    for relative in ("planner.py", "synthesizer.py", "delivery/base.py", "delivery/email.py"):
        tree = ast.parse((package / relative).read_text(encoding="utf-8"))
        modules: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
            elif isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
        assert not any(
            name in module for module in modules for name in ("astros", "weather", "dummy", "wsb")
        ), f"{relative} names a concrete beat"


# --------------------------------------------------------------------------- #
# FR-13 — the §2 metric computes from the trace file and nothing else
# --------------------------------------------------------------------------- #


def test_a_completed_run_produces_a_trace_the_metric_computes_from_alone(
    tmp_path: Path,
) -> None:
    report, _, _, _ = _run(tmp_path)

    assert report.trace_path.exists()

    # No digest argument: the trace records its own digest.
    result = check_provenance(report.trace_path)

    assert result.ok, result.summary()
    assert result.checked_fields > 0

    records = read_trace(report.trace_path)
    kinds = {record["type"] for record in records}
    assert {"run_start", "plan", "tool_call", "observation", "beat_result", "digest",
            "delivery", "run_end"} <= kinds

    start = next(records_of(records, "run_start"))
    assert start["auth_mode"] == "subscription_oauth"
    end = next(records_of(records, "run_end"))
    assert end["status"] == "ok"
    assert end["duration_ms"] >= 0


# --------------------------------------------------------------------------- #
# Failure still delivers, still traces, still writes the ledger
# --------------------------------------------------------------------------- #


def test_one_beat_failing_still_delivers_traces_and_writes_ledger_rows(
    tmp_path: Path,
) -> None:
    routes = [
        Route(SCHEDULE_URL, json_body={"detail": "boom"}, status=500),
        Route(POINTS_URL, fixture="nws_points_austin"),
        Route(HOURLY_URL, fixture="nws_hourly_austin"),
    ]
    report, deliverer, _, _ = _run(tmp_path, routes=routes)

    assert report.executed_beats == ["astros", "weather"]
    assert "Couldn't reach astros tonight" in report.text
    assert "Run window" in report.text
    assert deliverer.sent
    assert check_provenance(report.trace_path).ok
    assert report.ledger_rows >= 1

    rows = all_rows(path=tmp_path / "ledger.db")
    assert rows
    assert all(row.run_id == report.run_id for row in rows)


# --------------------------------------------------------------------------- #
# FR-9b through the real runner — two nights, one ledger
# --------------------------------------------------------------------------- #


def test_two_consecutive_runs_dedup_against_the_ledger_the_second_night(
    tmp_path: Path,
) -> None:
    """The full pipeline, twice, against one ledger file.

    Night one writes its items and indexes their vectors; night two retrieves them
    before composing. Nothing is stubbed but the embedder (offline) and the model.
    """
    from forecaster.agent import AgentResponse
    from forecaster.memory.retrieval import HashingEmbedder

    class SuppressingClient(FakeAgentClient):
        def complete(self, prompt, *, structured=None, system=None, effort="low"):
            if structured and "candidate" in structured:
                return AgentResponse(
                    text="SUPPRESS you were told this last night",
                    input_tokens=0,
                    output_tokens=0,
                )
            return super().complete(
                prompt, structured=structured, system=system, effort=effort
            )

    config = make_config(retrieval={"enabled": True})
    ledger = tmp_path / "ledger.db"
    embedder = HashingEmbedder()

    def one_night(run_dir: str):
        client, _ = fixture_client(HAPPY_ROUTES)
        with client:
            return run_pipeline(
                config,
                PREFS,
                agent_client=SuppressingClient(),
                deliverer=FakeDeliverer(),
                http_client=client,
                now=NOW,
                trace_dir=tmp_path / run_dir,
                ledger_path=ledger,
                embedder=embedder,
            )

    first = one_night("runs1")
    second = one_night("runs2")

    # Night one has an empty ledger, so nothing can be suppressed.
    assert set(first.dedup_actions) == {"include"}
    assert first.ledger_rows == len(first.dedup_actions)
    assert "Run window" in first.text

    # Night two retrieves night one's rows. Identical input, so every line is a repeat.
    assert set(second.dedup_actions) == {"suppress"}
    assert len(second.dedup_actions) == len(first.dedup_actions)
    assert "Run window" not in second.text

    # The decisions and their reasons are in the trace, per FR-9b's acceptance.
    decisions = [
        record
        for record in records_of(read_trace(second.trace_path), "decision")
        if str(record.get("decision", "")).startswith("dedup_")
    ]
    assert len(decisions) == len(second.dedup_actions)
    assert all(record["neighbours"] for record in decisions)
    assert all(record["top_similarity"] > 0.9 for record in decisions)
    assert all(record["reason"] for record in decisions)


def test_retrieval_stays_off_when_config_disables_it(tmp_path: Path) -> None:
    """FR-1 still holds: one config key turns the whole layer off."""
    from forecaster.memory.retrieval import HashingEmbedder

    ledger = tmp_path / "ledger.db"
    for run_dir in ("runs1", "runs2"):
        client, _ = fixture_client(HAPPY_ROUTES)
        with client:
            report = run_pipeline(
                make_config(retrieval={"enabled": False}),
                PREFS,
                agent_client=FakeAgentClient(),
                deliverer=FakeDeliverer(),
                http_client=client,
                now=NOW,
                trace_dir=tmp_path / run_dir,
                ledger_path=ledger,
                embedder=HashingEmbedder(),
            )

    assert report.dedup_actions == []
    assert "Run window" in report.text, "the repeat survives when retrieval is off"


# --------------------------------------------------------------------------- #
# Wiring details
# --------------------------------------------------------------------------- #


def test_ledger_rows_are_written_only_after_a_successful_delivery(
    tmp_path: Path,
) -> None:
    class FailingDeliverer(FakeDeliverer):
        def send(self, digest):
            result = super().send(digest)
            return type(result)(
                deliverer=self.name,
                target=self.target,
                success=False,
                sent_at=result.sent_at,
                error="smtp said no",
            )

    client, _ = fixture_client(HAPPY_ROUTES)
    with client:
        report = run_pipeline(
            make_config(),
            PREFS,
            agent_client=FakeAgentClient(),
            deliverer=FailingDeliverer(),
            http_client=client,
            now=NOW,
            trace_dir=tmp_path / "runs",
            ledger_path=tmp_path / "ledger.db",
        )

    assert report.ledger_rows == 0
    assert all_rows(path=tmp_path / "ledger.db") == []

    delivery = next(records_of(read_trace(report.trace_path), "delivery"))
    assert delivery["success"] is False
    assert delivery["error"] == "smtp said no"


def test_each_beat_gets_a_fresh_scratchpad(tmp_path: Path) -> None:
    """Two beats calling the same adapter must not share each other's cache."""
    report, _, _, recorder = _run(tmp_path)

    # astros: today + look-ahead = 2; weather: points + hourly = 2
    assert len(recorder.requests) == 4
    assert report.executed_beats == ["astros", "weather"]


def test_the_run_refuses_to_start_when_the_api_key_is_set(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-be-here")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-whatever")

    exit_code = main(["--dry-run"])

    assert exit_code == 2
    captured = capsys.readouterr()
    assert "refusing to start" in captured.err
    assert "ANTHROPIC_API_KEY" in captured.err
    assert "shadow" in captured.err.lower()


def test_the_run_refuses_to_start_with_no_oauth_token(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setattr("forecaster.cli.load_env", lambda *a, **k: None)

    exit_code = main(["--dry-run"])

    assert exit_code == 2
    assert "CLAUDE_CODE_OAUTH_TOKEN" in capsys.readouterr().err


def test_the_parser_exposes_the_four_documented_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(["--dry-run"])
    assert args.dry_run is True
    assert args.send_test is False
    assert args.config
    assert args.preferences

    assert parser.parse_args(["--send-test"]).send_test is True


def test_a_provenance_failure_fails_the_run_and_is_recorded(tmp_path: Path) -> None:
    from forecaster.synthesizer import ProvenanceError

    class FabricatingClient(FakeAgentClient):
        def complete(self, prompt, **kwargs):
            response = super().complete(prompt, **kwargs)
            return type(response)(
                text=response.text.replace("Astros 3", "Astros 8"),
                input_tokens=0,
                output_tokens=0,
            )

    client, _ = fixture_client(HAPPY_ROUTES)
    with client, pytest.raises(ProvenanceError):
        run_pipeline(
            make_config(),
            PREFS,
            agent_client=FabricatingClient(),
            deliverer=FakeDeliverer(),
            http_client=client,
            now=NOW,
            trace_dir=tmp_path / "runs",
            ledger_path=tmp_path / "ledger.db",
        )

    trace_path = next((tmp_path / "runs").glob("*.jsonl"))
    end = next(records_of(read_trace(trace_path), "run_end"))
    assert end["status"] == "provenance_failed"
    assert all_rows(path=tmp_path / "ledger.db") == [], "nothing ships on a failed check"

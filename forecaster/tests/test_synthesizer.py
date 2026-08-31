"""Step 14 — the provenance guarantee, green and red, plus FR-15's suppression.

Every test here injects `FakeAgentClient`. No test makes a real model call: the socket
guard would fail it, and it would draw down subscription usage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from forecaster.agent import FakeAgentClient
from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.memory.preferences import parse_preferences
from forecaster.synthesizer import Digest, ProvenanceError, synthesize
from forecaster.trace import Trace, check_provenance, read_trace, records_of
from tests.helpers import make_config, trace_in

CONFIG = make_config()

MLB_PAYLOAD = [
    {
        "game_pk": 824572,
        "abstract_game_state": "Final",
        "home_team": "Chicago White Sox",
        "away_team": "Houston Astros",
        "home_score": 12,
        "away_score": 3,
    }
]
WX_PAYLOAD = {
    "grid": "EWX 156,91",
    "periods": [
        {"temperature": 76.0, "windSpeed": "5 mph", "probabilityOfPrecipitation": 0}
    ],
}


def _seed(trace: Trace, *, freezing: bool = False, astros_text: str | None = None):
    """Write the observations and beat results a real run would have written."""
    mlb_obs = trace.tool_call(beat="astros", adapter="mlb.fetch_schedule", arguments={})
    trace.observation(mlb_obs, payload=MLB_PAYLOAD)
    astros = BeatResult(
        beat="astros",
        items=[
            BeatItem(
                beat="astros",
                text=astros_text or "Final: Houston Astros 3, Chicago White Sox 12.",
                observations=[ObservationRef(mlb_obs, "mlb.fetch_schedule")],
            )
        ],
        checkable_fields={
            "final_score": "Houston Astros 3, Chicago White Sox 12",
            "game_state": "Final",
        },
        observations=[ObservationRef(mlb_obs, "mlb.fetch_schedule")],
    )

    wx_obs = trace.tool_call(
        beat="weather", adapter="weather.fetch_hourly_forecast", arguments={}
    )
    trace.observation(wx_obs, payload=WX_PAYLOAD)
    weather = BeatResult(
        beat="weather",
        items=[
            BeatItem(
                beat="weather",
                text="Run window 05:00-08:00: 76.0-76.0F, 5 mph S, 0% chance of precipitation.",
                fields={"precip_probability_pct": 0},
                observations=[ObservationRef(wx_obs, "weather.fetch_hourly_forecast")],
            )
        ],
        checkable_fields={
            "run_window_low_f": 76.0,
            "precip_probability_pct": 0,
            "wind_speed": "5 mph",
        },
        escalation_candidate=freezing,
        escalation_reason="run-window low is at or below the threshold" if freezing else None,
        observations=[ObservationRef(wx_obs, "weather.fetch_hourly_forecast")],
    )

    trace.beat_result(astros)
    trace.beat_result(weather)
    return [astros, weather]


def _prefs(**kwargs):
    data = {"topics": {"astros": 1.0, "weather": 1.0}}
    data.update(kwargs)
    return parse_preferences(data)


# --------------------------------------------------------------------------- #
# FR-11 — the provenance test, green and red
# --------------------------------------------------------------------------- #


def test_a_full_synthetic_run_passes_the_provenance_check(tmp_path: Path) -> None:
    agent = FakeAgentClient()
    trace = trace_in(tmp_path, "clean-run")
    with trace:
        results = _seed(trace)
        digest = synthesize(results, CONFIG, _prefs(), trace, agent_client=agent)

    assert isinstance(digest, Digest)
    assert digest.provenance is not None
    assert digest.provenance.ok, digest.provenance.summary()
    assert "Houston Astros 3, Chicago White Sox 12" in digest.text
    assert agent.call_count == 1


def test_a_digest_with_a_score_changed_by_one_fails_the_check(tmp_path: Path) -> None:
    """The red half. The check must catch what a prompt instruction cannot."""
    trace = trace_in(tmp_path, "tampered-run")
    with trace:
        results = _seed(trace)
        digest = synthesize(
            results, CONFIG, _prefs(), trace, agent_client=FakeAgentClient()
        )
        tampered = digest.text.replace(
            "Houston Astros 3, Chicago White Sox 12",
            "Houston Astros 4, Chicago White Sox 12",
        )
        report = check_provenance(trace.path, tampered)

    assert not report.ok
    assert any(v.kind == "altered_claim" for v in report.violations)


def test_a_fabricating_client_fails_the_run_rather_than_warning(tmp_path: Path) -> None:
    """A failed provenance check fails the run — it does not degrade to a warning."""

    class FabricatingClient(FakeAgentClient):
        def complete(self, prompt, **kwargs):
            response = super().complete(prompt, **kwargs)
            return type(response)(
                text=response.text.replace("Astros 3", "Astros 7"),
                input_tokens=0,
                output_tokens=0,
            )

    trace = trace_in(tmp_path, "fabricating-run")
    with trace:
        results = _seed(trace)
        with pytest.raises(ProvenanceError) as excinfo:
            synthesize(results, CONFIG, _prefs(), trace, agent_client=FabricatingClient())

    assert any(v.kind == "altered_claim" for v in excinfo.value.report.violations)

    decisions = [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record["decision"] == "provenance_checked"
    ]
    assert decisions and decisions[-1]["violations"]


def test_the_model_phrases_and_never_originates(tmp_path: Path) -> None:
    """Everything the client was handed came from a BeatResult, not from the model."""
    agent = FakeAgentClient()
    trace = trace_in(tmp_path, "phrasing-run")
    with trace:
        results = _seed(trace)
        synthesize(results, CONFIG, _prefs(), trace, agent_client=agent)

    call = agent.calls[0]
    assert call.system and "phrase" in call.system.lower()
    assert set(call.structured) == {"lines"}
    for line in call.structured["lines"]:
        assert any(
            line == item.text for result in results for item in result.items
        ), f"the model was handed {line!r}, which no beat produced"


# --------------------------------------------------------------------------- #
# FR-15 — a suppression rule removes an item from the digest
# --------------------------------------------------------------------------- #


def test_adding_a_suppression_rule_removes_the_matching_item(tmp_path: Path) -> None:
    without_rule = _prefs()
    with_rule = _prefs(
        suppressions=[
            {
                "id": "no-blowouts",
                "beat": "astros",
                "contains": "White Sox 12",
                "reason": "A 12-3 loss is not worth reading about.",
            }
        ]
    )

    trace_a = trace_in(tmp_path, "prefs-off")
    with trace_a:
        digest_off = synthesize(
            _seed(trace_a), CONFIG, without_rule, trace_a, agent_client=FakeAgentClient()
        )

    trace_b = trace_in(tmp_path, "prefs-on")
    with trace_b:
        digest_on = synthesize(
            _seed(trace_b), CONFIG, with_rule, trace_b, agent_client=FakeAgentClient()
        )

    assert "Chicago White Sox 12" in digest_off.text
    assert "Chicago White Sox 12" not in digest_on.text
    assert digest_on.provenance is not None and digest_on.provenance.ok


def test_the_trace_names_the_rule_that_suppressed(tmp_path: Path) -> None:
    prefs = _prefs(
        suppressions=[
            {
                "id": "no-blowouts",
                "beat": "astros",
                "contains": "White Sox 12",
                "reason": "A 12-3 loss is not worth reading about.",
            }
        ]
    )
    trace = trace_in(tmp_path, "suppression-run")
    with trace:
        digest = synthesize(
            _seed(trace), CONFIG, prefs, trace, agent_client=FakeAgentClient()
        )

    assert [rule.rule_id for _, rule in digest.suppressed] == ["no-blowouts"]

    suppressions = [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record["decision"] == "item_suppressed"
    ]
    assert suppressions
    assert suppressions[0]["rule"] == "no-blowouts"
    assert "not worth reading about" in suppressions[0]["reason"]


# --------------------------------------------------------------------------- #
# FR-10 re-checked at digest level
# --------------------------------------------------------------------------- #


def test_escalated_items_appear_first_in_the_rendered_output(tmp_path: Path) -> None:
    agent = FakeAgentClient()
    trace = trace_in(tmp_path, "escalated-run")
    with trace:
        results = _seed(trace, freezing=True)
        digest = synthesize(results, CONFIG, _prefs(), trace, agent_client=agent)

    assert digest.beat_order[0] == "weather"
    weather_at = digest.text.index("Run window")
    astros_at = digest.text.index("Houston Astros 3")
    assert weather_at < astros_at


def test_without_an_escalation_the_base_order_is_kept(tmp_path: Path) -> None:
    trace = trace_in(tmp_path, "plain-run")
    with trace:
        digest = synthesize(
            _seed(trace), CONFIG, _prefs(), trace, agent_client=FakeAgentClient()
        )

    assert digest.beat_order == ["astros", "weather"]


# --------------------------------------------------------------------------- #
# Guardrails
# --------------------------------------------------------------------------- #


def test_the_synthesizer_does_not_read_the_ledger(tmp_path: Path) -> None:
    """Still true after FR-9b landed, and still worth enforcing.

    The synthesizer applies the ledger check through an **injected** retriever, so it
    never opens a database, never names a table, and stays testable with no ledger at
    all. `retriever=None` is exactly the v1 pipeline.
    """
    import ast

    path = Path(__file__).resolve().parent.parent / "forecaster" / "synthesizer.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))

    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            imported.extend(alias.name for alias in node.names)
    assert not any("ledger" in name.lower() for name in imported)

    # And no ledger name is referenced anywhere in the code (docstrings excluded —
    # the module explains *why* it doesn't read the ledger, which is the point).
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    } | {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    assert not any("ledger" in name.lower() for name in names)


def test_the_synthesizer_does_not_construct_a_client_inline() -> None:
    source = (
        Path(__file__).resolve().parent.parent / "forecaster" / "synthesizer.py"
    ).read_text(encoding="utf-8")
    assert "ClaudeAgentClient(" not in source

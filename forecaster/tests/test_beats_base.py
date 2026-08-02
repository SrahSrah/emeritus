"""Step 5 — the contract: one class + one config entry is the whole cost of a beat."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Iterator

import pytest

from forecaster.beats.base import (
    Beat,
    BeatContext,
    BeatItem,
    BeatResult,
    ObservationRef,
    get_beats,
    register_beat,
    registered_beats,
    unregister_beat,
)
from forecaster.config import parse_config
from forecaster.memory.preferences import parse_preferences

BASE_CONFIG = {
    "run": {
        "send_time": "19:00",
        "timezone": "America/Chicago",
        "run_window_start": "05:00",
        "run_window_end": "08:00",
    },
    "beats": {"dummy": True},
    "location": {
        "city": "Austin",
        "state": "TX",
        "latitude": 30.2672,
        "longitude": -97.7431,
        "timezone": "America/Chicago",
    },
    "delivery": {"kind": "fake", "target": "nobody@example.test"},
    "escalation": {
        "rules": ["freeze_alert"],
        "freeze_threshold_f": 32.0,
        "freeze_horizon_days": 1,
        "watched_players": [],
    },
    "team": {"mlb_team_id": 117, "name": "Astros"},
    "retrieval": {
        "enabled": False,
        "model": "test-hashing-embedder",
        "k": 5,
        "similarity_floor": 0.60,
        "window_days": 14,
    },
}


class DummyBeat:
    """A whole beat. This is the entire cost of adding one."""

    name = "dummy"

    def should_run(self, context: BeatContext) -> bool:
        return True

    def run(self, context: BeatContext) -> BeatResult:
        return BeatResult(
            beat=self.name,
            items=[BeatItem(beat=self.name, text="dummy says hello")],
        )


@pytest.fixture
def dummy_registered() -> Iterator[None]:
    register_beat(DummyBeat)
    try:
        yield
    finally:
        unregister_beat(DummyBeat.name)


def _config(beats: dict[str, bool]) -> object:
    data = {**BASE_CONFIG, "beats": beats}
    return parse_config(data)


def test_one_class_plus_one_config_entry_gets_a_beat_into_get_beats(
    dummy_registered: None,
) -> None:
    beats = get_beats(_config({"dummy": True}))

    assert [beat.name for beat in beats] == ["dummy"]
    assert isinstance(beats[0], Beat)


def test_disabling_the_beat_in_config_removes_it(dummy_registered: None) -> None:
    assert get_beats(_config({"dummy": False})) == []


def test_get_beats_preserves_config_declaration_order(dummy_registered: None) -> None:
    class SecondBeat(DummyBeat):
        name = "second"

    register_beat(SecondBeat)
    try:
        ordered = get_beats(_config({"second": True, "dummy": True}))
        assert [beat.name for beat in ordered] == ["second", "dummy"]
    finally:
        unregister_beat("second")


def test_enabling_an_unregistered_beat_is_an_error_not_a_silent_skip() -> None:
    with pytest.raises(LookupError, match="not registered"):
        get_beats(_config({"nobody-wrote-this": True}))


def test_registering_a_different_class_under_a_taken_name_raises(
    dummy_registered: None,
) -> None:
    class Impostor:
        name = "dummy"

    with pytest.raises(ValueError, match="already registered"):
        register_beat(Impostor)


def test_registering_a_class_without_a_name_raises() -> None:
    class Nameless:
        pass

    with pytest.raises(ValueError, match="non-empty class-level `name`"):
        register_beat(Nameless)


def test_registered_beats_returns_a_copy(dummy_registered: None) -> None:
    snapshot = registered_beats()
    snapshot.clear()
    assert "dummy" in registered_beats()


# --------------------------------------------------------------------------- #
# BeatResult invariants
# --------------------------------------------------------------------------- #


def test_checkable_fields_defaults_to_empty_not_none() -> None:
    result = BeatResult(beat="dummy")
    assert result.checkable_fields == {}
    assert result.checkable_fields is not None
    assert result.escalation_signals == {}
    assert result.observations == []


def test_unavailable_result_requires_a_non_empty_error() -> None:
    with pytest.raises(ValueError, match="carries no error"):
        BeatResult(beat="dummy", available=False)
    with pytest.raises(ValueError, match="carries no error"):
        BeatResult(beat="dummy", available=False, error="")


def test_available_result_may_not_carry_an_error() -> None:
    with pytest.raises(ValueError, match="pick one"):
        BeatResult(beat="dummy", available=True, error="boom")


def test_unavailable_helper_builds_the_fr18_shape() -> None:
    result = BeatResult.unavailable("dummy", "MLB Stats API returned 500")

    assert result.available is False
    assert "500" in (result.error or "")
    assert result.checkable_fields == {}


def test_unavailable_result_may_not_declare_checkable_fields() -> None:
    with pytest.raises(ValueError, match="nothing to state as fact"):
        BeatResult(
            beat="dummy",
            available=False,
            error="timeout",
            checkable_fields={"score": "Astros 5"},
        )


def test_escalation_candidate_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="no reason"):
        BeatResult(beat="dummy", escalation_candidate=True)

    ok = BeatResult(
        beat="dummy", escalation_candidate=True, escalation_reason="run-window low 28F"
    )
    assert ok.escalation_reason


def test_beat_item_requires_a_beat() -> None:
    with pytest.raises(ValueError, match="BeatItem.beat"):
        BeatItem(beat="", text="orphan")


def test_observation_ref_links_a_value_to_its_trace_record() -> None:
    ref = ObservationRef(observation_id="obs-1", adapter="mlb.fetch_schedule")
    result = BeatResult(
        beat="dummy",
        checkable_fields={"score": "Astros 5, Rangers 3"},
        observations=[ref],
    )
    assert result.observations[0].observation_id == "obs-1"


def test_beat_context_carries_the_collaborators_not_globals() -> None:
    prefs = parse_preferences({"topics": {"dummy": 1.0}})
    context = BeatContext(
        config=_config({"dummy": True}),
        preferences=prefs,
        now=datetime(2026, 7, 27, 19, 0),
        scratchpad=object(),
        trace=object(),
    )
    assert context.now.hour == 19
    assert context.preferences.weight_for("dummy") == 1.0


def test_base_module_does_not_import_a_concrete_beat_at_module_scope() -> None:
    """The seam only holds if base.py stays ignorant of astros/weather."""
    source = (
        Path(__file__).resolve().parent.parent / "forecaster" / "beats" / "base.py"
    ).read_text(encoding="utf-8")
    module_scope = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from ")) and "beats." in line
    ]
    assert module_scope == []

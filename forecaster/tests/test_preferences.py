"""Step 4 — the preference profile loads, and a suppression can explain itself."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

import pytest

from forecaster.memory.preferences import (
    Preferences,
    PreferencesError,
    SuppressionDecision,
    load_preferences,
    suppression_match,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REAL_PREFERENCES = PROJECT_ROOT / "preferences.toml"


@dataclass
class StubItem:
    """Stands in for the BeatItem that Step 5 defines."""

    beat: str
    text: str
    fields: Mapping[str, Any] = field(default_factory=dict)


def _write(tmp_path: Path, body: str, name: str = "preferences.toml") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def test_real_preferences_file_loads() -> None:
    prefs = load_preferences(REAL_PREFERENCES)

    assert isinstance(prefs, Preferences)
    assert prefs.topics["astros"] > 0
    assert prefs.weight_for("weather") > 0
    assert prefs.weight_for("a-beat-with-no-entry") == 1.0
    assert "Yordan Alvarez" in prefs.watched_players
    assert {rule.id for rule in prefs.suppressions} >= {"no-spring-training"}
    assert all(rule.reason for rule in prefs.suppressions)


def test_matching_item_returns_a_decision_naming_the_rule() -> None:
    prefs = load_preferences(REAL_PREFERENCES)
    item = StubItem(beat="astros", text="Spring Training: Astros 4, Mets 2")

    decision = suppression_match(item, prefs)

    assert isinstance(decision, SuppressionDecision)
    assert decision.rule_id == "no-spring-training"
    assert "no-spring-training" in decision.reason
    assert "Exhibition results" in decision.reason


def test_field_equals_rule_matches_on_structured_value() -> None:
    prefs = load_preferences(REAL_PREFERENCES)
    item = StubItem(
        beat="weather",
        text="Low 68F, no rain expected.",
        fields={"precip_probability_pct": 0},
    )

    decision = suppression_match(item, prefs)

    assert decision is not None
    assert decision.rule_id == "no-trivial-precip"


def test_non_matching_item_returns_none() -> None:
    prefs = load_preferences(REAL_PREFERENCES)
    item = StubItem(beat="astros", text="Final: Astros 5, Rangers 3")

    assert suppression_match(item, prefs) is None


def test_rule_scoped_to_a_beat_does_not_fire_on_another_beat() -> None:
    prefs = load_preferences(REAL_PREFERENCES)
    item = StubItem(beat="weather", text="Spring Training", fields={})

    assert suppression_match(item, prefs) is None


def test_missing_file_fails_clearly_rather_than_defaulting(tmp_path: Path) -> None:
    with pytest.raises(PreferencesError, match="No preference file"):
        load_preferences(tmp_path / "nope.toml")


def test_rule_without_a_reason_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[topics]
astros = 1.0

[[suppressions]]
id = "silent"
beat = "astros"
""",
    )
    with pytest.raises(PreferencesError, match="reason"):
        load_preferences(path)


def test_rule_with_no_criteria_is_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[suppressions]]
id = "catch-all"
reason = "would eat the whole digest"
""",
    )
    with pytest.raises(PreferencesError, match="no match criteria"):
        load_preferences(path)


def test_duplicate_rule_ids_are_rejected(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[suppressions]]
id = "dupe"
beat = "astros"
reason = "first"

[[suppressions]]
id = "dupe"
beat = "weather"
reason = "second"
""",
    )
    with pytest.raises(PreferencesError, match="duplicate suppression id"):
        load_preferences(path)


def test_malformed_toml_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "[topics\nastros = ")
    with pytest.raises(PreferencesError, match="not valid TOML"):
        load_preferences(path)


def test_first_matching_rule_wins_deterministically(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[suppressions]]
id = "first"
beat = "astros"
contains = "rain"
reason = "earlier rule"

[[suppressions]]
id = "second"
beat = "astros"
contains = "rain"
reason = "later rule"
""",
    )
    prefs = load_preferences(path)
    decision = suppression_match(StubItem(beat="astros", text="rained out"), prefs)

    assert decision is not None
    assert decision.rule_id == "first"

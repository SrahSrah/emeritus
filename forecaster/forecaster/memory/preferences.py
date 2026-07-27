"""The human-edited preference profile (FR-15).

Topic weights, watched players, and suppression rules. Read-only in v1: writing rules
from replies is FR-16 and is deferred. Nothing here learns, weights by history, or
embeds anything — PRD §4 rules that out explicitly.

Matching is deterministic and explainable on purpose. A suppression that fires returns
the rule that fired and a sentence saying why, because Step 6's trace records the reason
and Step 14 has to be able to show its work.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, runtime_checkable

DEFAULT_PREFERENCES_PATH = Path(__file__).resolve().parent.parent.parent / "preferences.toml"


class PreferencesError(ValueError):
    """The preference file is missing, malformed, or has an unusable rule."""


@runtime_checkable
class SuppressibleItem(Protocol):
    """The shape a suppression rule matches against.

    Structural on purpose: ``beats/base.py`` defines the real ``BeatItem`` (Step 5) and
    this module must not import it — preferences load before any beat exists.
    """

    beat: str
    text: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class SuppressionRule:
    """One human-written rule. At least one of the match criteria must be present."""

    id: str
    reason: str
    beat: str | None = None
    contains: str | None = None
    field_name: str | None = None
    equals: Any = None

    def describe(self) -> str:
        parts: list[str] = []
        if self.beat:
            parts.append(f"beat == {self.beat!r}")
        if self.contains:
            parts.append(f"text contains {self.contains!r}")
        if self.field_name is not None:
            parts.append(f"{self.field_name} == {self.equals!r}")
        return " and ".join(parts) or "matches everything"


@dataclass(frozen=True)
class SuppressionDecision:
    """Why an item was dropped, in terms a human can check."""

    rule: SuppressionRule
    reason: str

    @property
    def rule_id(self) -> str:
        return self.rule.id


@dataclass(frozen=True)
class Preferences:
    topics: dict[str, float] = field(default_factory=dict)
    watched_players: list[str] = field(default_factory=list)
    suppressions: list[SuppressionRule] = field(default_factory=list)
    source_path: Path | None = None

    def weight_for(self, beat: str) -> float:
        """Topic weight for a beat. Absent means neutral, not zero."""
        return float(self.topics.get(beat, 1.0))


def _parse_suppression(raw: Any, index: int) -> SuppressionRule:
    if not isinstance(raw, Mapping):
        raise PreferencesError(
            f"preferences.toml: [[suppressions]] #{index} must be a table"
        )
    rule_id = raw.get("id")
    if not isinstance(rule_id, str) or not rule_id:
        raise PreferencesError(
            f"preferences.toml: [[suppressions]] #{index} needs a non-empty string `id` "
            "so the trace can name which rule fired"
        )
    reason = raw.get("reason")
    if not isinstance(reason, str) or not reason:
        raise PreferencesError(
            f"preferences.toml: suppression {rule_id!r} needs a `reason` — a rule that "
            "cannot explain itself is not auditable"
        )

    beat = raw.get("beat")
    contains = raw.get("contains")
    field_name = raw.get("field")
    has_equals = "equals" in raw
    equals = raw.get("equals")

    if beat is not None and not isinstance(beat, str):
        raise PreferencesError(f"preferences.toml: suppression {rule_id!r} `beat` must be a string")
    if contains is not None and not isinstance(contains, str):
        raise PreferencesError(
            f"preferences.toml: suppression {rule_id!r} `contains` must be a string"
        )
    if field_name is not None and not isinstance(field_name, str):
        raise PreferencesError(
            f"preferences.toml: suppression {rule_id!r} `field` must be a string"
        )
    if (field_name is None) != (not has_equals):
        raise PreferencesError(
            f"preferences.toml: suppression {rule_id!r} must set `field` and `equals` "
            "together, or neither"
        )
    if beat is None and contains is None and field_name is None:
        raise PreferencesError(
            f"preferences.toml: suppression {rule_id!r} has no match criteria — it would "
            "suppress every item"
        )

    return SuppressionRule(
        id=rule_id,
        reason=reason,
        beat=beat,
        contains=contains,
        field_name=field_name,
        equals=equals,
    )


def parse_preferences(data: Mapping[str, Any], source_path: Path | None = None) -> Preferences:
    topics_raw = data.get("topics", {})
    if not isinstance(topics_raw, Mapping):
        raise PreferencesError("preferences.toml: [topics] must be a table")
    topics: dict[str, float] = {}
    for name, weight in topics_raw.items():
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise PreferencesError(
                f"preferences.toml: [topics].{name} must be a number, got {weight!r}"
            )
        topics[name] = float(weight)

    players_raw = data.get("watched_players", [])
    if not isinstance(players_raw, list) or not all(
        isinstance(item, str) for item in players_raw
    ):
        raise PreferencesError("preferences.toml: watched_players must be a list of strings")

    suppressions_raw = data.get("suppressions", [])
    if not isinstance(suppressions_raw, list):
        raise PreferencesError("preferences.toml: suppressions must be a list of tables")
    suppressions = [
        _parse_suppression(raw, index) for index, raw in enumerate(suppressions_raw)
    ]

    seen: set[str] = set()
    for rule in suppressions:
        if rule.id in seen:
            raise PreferencesError(
                f"preferences.toml: duplicate suppression id {rule.id!r} — ids must be "
                "unique so a trace entry is unambiguous"
            )
        seen.add(rule.id)

    return Preferences(
        topics=topics,
        watched_players=list(players_raw),
        suppressions=suppressions,
        source_path=source_path,
    )


def load_preferences(path: str | Path | None = None) -> Preferences:
    """Read and validate ``preferences.toml``. A missing file is an error, not a default."""
    prefs_path = Path(path) if path is not None else DEFAULT_PREFERENCES_PATH
    if not prefs_path.exists():
        raise PreferencesError(
            f"No preference file at {prefs_path}. The profile is required — running with "
            "no preferences would silently change what the digest contains."
        )
    try:
        data = tomllib.loads(prefs_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise PreferencesError(f"{prefs_path} is not valid TOML: {exc}") from exc
    return parse_preferences(data, source_path=prefs_path)


def _item_beat(item: Any) -> str | None:
    if isinstance(item, Mapping):
        value = item.get("beat")
    else:
        value = getattr(item, "beat", None)
    return value if isinstance(value, str) else None


def _item_text(item: Any) -> str:
    if isinstance(item, Mapping):
        value = item.get("text", "")
    else:
        value = getattr(item, "text", "")
    return value if isinstance(value, str) else ""


def _item_fields(item: Any) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        value = item.get("fields", {})
    else:
        value = getattr(item, "fields", {})
    return value if isinstance(value, Mapping) else {}


def rule_matches(item: Any, rule: SuppressionRule) -> bool:
    if rule.beat is not None and _item_beat(item) != rule.beat:
        return False
    if rule.contains is not None and rule.contains.lower() not in _item_text(item).lower():
        return False
    if rule.field_name is not None:
        fields = _item_fields(item)
        if rule.field_name not in fields:
            return False
        if fields[rule.field_name] != rule.equals:
            return False
    return True


def suppression_match(item: Any, preferences: Preferences) -> SuppressionDecision | None:
    """First rule that matches, with a human-readable reason. ``None`` if none do."""
    for rule in preferences.suppressions:
        if rule_matches(item, rule):
            return SuppressionDecision(
                rule=rule,
                reason=(
                    f"suppressed by rule {rule.id!r} ({rule.describe()}): {rule.reason}"
                ),
            )
    return None


__all__ = [
    "DEFAULT_PREFERENCES_PATH",
    "Preferences",
    "PreferencesError",
    "SuppressibleItem",
    "SuppressionDecision",
    "SuppressionRule",
    "load_preferences",
    "parse_preferences",
    "rule_matches",
    "suppression_match",
]

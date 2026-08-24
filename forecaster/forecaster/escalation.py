"""Deterministic escalation rules over `BeatResult`s (FR-10).

Pure functions, no model call, no judgment. Same inputs, same output, every time.

PRD §9 **Q2 — rules vs judgment for escalation — is open by design.** If a rule here
starts wanting a judgment call, that is a decision for Sarah, not something to settle in
this module.

PRD §8 warns that escalating everything is the same as escalating nothing. So every rule
evaluation is written to the trace whether it fired or not, which makes "these rules fire
most nights" observable in the first two weeks instead of a surprise later.

## The two v1 rules, and the honest state of each

- **`freeze_alert`** — fires when a beat reports the run-window low at or below the
  configured threshold. `freeze_horizon_days` is read from config and recorded, but the
  rule can only apply over **the horizon the data actually covers**, which in v1 is the
  next morning's window (FR-6). A multi-day horizon needs a forecast-range decision first.
- **`watched_player_injury`** — implemented and correct, but **dormant**. It reads
  `escalation_signals["injuries"]`, and no v1 beat populates that key: the MLB adapter
  returns schedule, state, score, and game ID only. Adding an injury feed is new scope.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

FREEZE_ALERT = "freeze_alert"
WATCHED_PLAYER_INJURY = "watched_player_injury"
NEED_TO_KNOW_WATCHLIST = "need_to_know_watchlist"


@dataclass(frozen=True)
class RuleOutcome:
    """One rule's verdict on one beat result."""

    rule: str
    beat: str
    fired: bool
    reason: str


@dataclass(frozen=True)
class OrderedItem:
    """One item in the digest's final order, with its promotion recorded."""

    beat: str
    item: Any
    promoted: bool = False
    rule: str | None = None
    reason: str | None = None


@dataclass
class OrderedItems:
    """The ordered digest structure plus every rule evaluation behind it."""

    items: list[OrderedItem] = field(default_factory=list)
    outcomes: list[RuleOutcome] = field(default_factory=list)
    unavailable: list[Any] = field(default_factory=list)

    @property
    def beat_order(self) -> list[str]:
        return [entry.beat for entry in self.items]

    @property
    def promoted(self) -> list[OrderedItem]:
        return [entry for entry in self.items if entry.promoted]

    def fired(self) -> list[RuleOutcome]:
        return [outcome for outcome in self.outcomes if outcome.fired]


# --------------------------------------------------------------------------- #
# The rules
# --------------------------------------------------------------------------- #


def _freeze_alert(result: Any, config: Any) -> RuleOutcome:
    """Promote a run-window low at or below the configured freeze threshold."""
    beat = getattr(result, "beat", "")
    threshold = config.escalation.freeze_threshold_f
    horizon = config.escalation.freeze_horizon_days

    if not getattr(result, "available", True):
        return RuleOutcome(
            rule=FREEZE_ALERT,
            beat=beat,
            fired=False,
            reason=f"{beat} is unavailable, so there is no forecast to compare",
        )

    if getattr(result, "escalation_candidate", False):
        return RuleOutcome(
            rule=FREEZE_ALERT,
            beat=beat,
            fired=True,
            reason=(
                getattr(result, "escalation_reason", None)
                or f"{beat} flagged the run-window low at or below {threshold}"
            )
            + f" (horizon {horizon}d, evaluated over the fetched run window)",
        )

    return RuleOutcome(
        rule=FREEZE_ALERT,
        beat=beat,
        fired=False,
        reason=f"{beat} did not flag a run-window low at or below {threshold}",
    )


def _watched_player_injury(result: Any, config: Any) -> RuleOutcome:
    """Promote an injury to a configured watched player. **Dormant in v1** — no feed."""
    beat = getattr(result, "beat", "")
    watched = [name.lower() for name in config.escalation.watched_players]
    signals = getattr(result, "escalation_signals", {}) or {}
    injuries = signals.get("injuries")

    if not injuries:
        return RuleOutcome(
            rule=WATCHED_PLAYER_INJURY,
            beat=beat,
            fired=False,
            reason=(
                f"{beat} reported no injury signal (no v1 beat populates one — the rule "
                "is implemented but dormant)"
            ),
        )

    hits = [
        name
        for name in _injury_names(injuries)
        if any(watch in name.lower() for watch in watched)
    ]
    if hits:
        return RuleOutcome(
            rule=WATCHED_PLAYER_INJURY,
            beat=beat,
            fired=True,
            reason=f"injury reported for watched player(s): {', '.join(hits)}",
        )
    return RuleOutcome(
        rule=WATCHED_PLAYER_INJURY,
        beat=beat,
        fired=False,
        reason=f"{beat} reported injuries, but none to a configured watched player",
    )


def _injury_names(injuries: Any) -> list[str]:
    names: list[str] = []
    for entry in injuries if isinstance(injuries, (list, tuple)) else [injuries]:
        if isinstance(entry, str):
            names.append(entry)
        elif isinstance(entry, Mapping):
            name = entry.get("player") or entry.get("name")
            if isinstance(name, str):
                names.append(name)
    return names


def _need_to_know_watchlist(result: Any, config: Any) -> RuleOutcome:
    """Promote a need-to-know item that matched a configured watchlist term (FR-38).

    Deterministic on purpose: the carve-out is what bounds the bar's suppress-when-unsure
    judgment, so no model opinion may decide whether it fires. Reads the beat-agnostic
    `escalation_signals["watchlist"]` bag per the base-contract rule (no beat-specific
    column on the universal contract). Registered in Step 45 **dormant** — nothing
    populates the signal until the beat's watchlist pass lands in Step 46 — which is the
    same landing pattern as the injury rule, minus the missing data source.
    """
    beat = getattr(result, "beat", "")
    if not getattr(result, "available", True):
        return RuleOutcome(
            rule=NEED_TO_KNOW_WATCHLIST,
            beat=beat,
            fired=False,
            reason=f"{beat} is unavailable, so no watchlist match is possible",
        )

    signals = getattr(result, "escalation_signals", {}) or {}
    hits = signals.get("watchlist") or []
    if hits:
        terms = ", ".join(str(hit) for hit in hits[:3])
        more = "" if len(hits) <= 3 else f" (and {len(hits) - 3} more)"
        return RuleOutcome(
            rule=NEED_TO_KNOW_WATCHLIST,
            beat=beat,
            fired=True,
            reason=f"watchlist term(s) matched: {terms}{more}",
        )
    return RuleOutcome(
        rule=NEED_TO_KNOW_WATCHLIST,
        beat=beat,
        fired=False,
        reason=f"{beat} reported no watchlist match",
    )


RULES: dict[str, Callable[[Any, Any], RuleOutcome]] = {
    FREEZE_ALERT: _freeze_alert,
    WATCHED_PLAYER_INJURY: _watched_player_injury,
    NEED_TO_KNOW_WATCHLIST: _need_to_know_watchlist,
}


# --------------------------------------------------------------------------- #
# The engine
# --------------------------------------------------------------------------- #


def apply_escalation(
    results: Sequence[Any], config: Any, *, trace: Any = None
) -> OrderedItems:
    """Order the digest's items, promoting whatever the configured rules match.

    Deterministic: promotions are ordered by the **config's `[escalation].rules` list**
    (priority order), then by the order the beats ran. Unpromoted items keep their base
    order. Nothing is dropped.
    """
    rule_names = list(config.escalation.rules)
    unknown = [name for name in rule_names if name not in RULES]
    if unknown:
        raise LookupError(
            f"config.toml [escalation].rules names unknown rule(s) {unknown}. "
            f"Known rules: {sorted(RULES)}."
        )

    ordered = OrderedItems()
    promotions: list[tuple[int, int, OrderedItem]] = []
    base: list[OrderedItem] = []

    for beat_index, result in enumerate(results):
        beat = getattr(result, "beat", "")

        if not getattr(result, "available", True):
            ordered.unavailable.append(result)

        winning: tuple[int, RuleOutcome] | None = None
        for rule_index, rule_name in enumerate(rule_names):
            outcome = RULES[rule_name](result, config)
            ordered.outcomes.append(outcome)
            if trace is not None:
                trace.escalation(
                    rule=outcome.rule,
                    fired=outcome.fired,
                    reason=outcome.reason,
                    beat=outcome.beat,
                )
            if outcome.fired and winning is None:
                winning = (rule_index, outcome)

        for item in getattr(result, "items", []) or []:
            if winning is not None:
                rule_index, outcome = winning
                promotions.append(
                    (
                        rule_index,
                        beat_index,
                        OrderedItem(
                            beat=beat,
                            item=item,
                            promoted=True,
                            rule=outcome.rule,
                            reason=outcome.reason,
                        ),
                    )
                )
            else:
                base.append(OrderedItem(beat=beat, item=item))

    promotions.sort(key=lambda entry: (entry[0], entry[1]))
    ordered.items = [entry[2] for entry in promotions] + base
    return ordered


def escalation_summary(ordered: OrderedItems) -> dict[str, Any]:
    """A compact record for the trace / STATUS reporting."""
    return {
        "promoted": [
            {"beat": entry.beat, "rule": entry.rule, "reason": entry.reason}
            for entry in ordered.promoted
        ],
        "evaluations": len(ordered.outcomes),
        "fired": len(ordered.fired()),
    }


__all__ = [
    "FREEZE_ALERT",
    "NEED_TO_KNOW_WATCHLIST",
    "RULES",
    "WATCHED_PLAYER_INJURY",
    "OrderedItem",
    "OrderedItems",
    "RuleOutcome",
    "apply_escalation",
    "escalation_summary",
]

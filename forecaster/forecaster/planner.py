"""Planner — which beats run tonight, and what "done" means for each (FR-7).

Reads the date, the day of week, and the preference profile, and emits a plan. It
**performs no research itself**: no adapter, no network, no model call. A test asserts
that, because a planner that quietly fetches something is a planner that has stopped
being a plan.

It imports the `Beat` protocol and the registry, never `beats/astros.py` or
`beats/weather.py` — that is FR-2's seam, and the planner is the first place it would be
tempting to break.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Sequence

from forecaster.beats.base import Beat, BeatContext, get_beats
from forecaster.config import Config
from forecaster.memory.preferences import Preferences

#: What "done" means when a beat doesn't say for itself.
GENERIC_CRITERION = "reported for tonight, or explicitly marked unavailable with a reason"


@dataclass(frozen=True)
class PlanEntry:
    """One beat's line in the plan."""

    beat: str
    criterion: str
    weight: float = 1.0

    def as_record(self) -> dict[str, Any]:
        return {"beat": self.beat, "criterion": self.criterion, "weight": self.weight}


@dataclass
class RunPlan:
    """What tonight's run intends to do, decided before anything is fetched."""

    date: str
    day_of_week: str
    entries: list[PlanEntry] = field(default_factory=list)
    skipped: dict[str, str] = field(default_factory=dict)

    @property
    def beat_names(self) -> list[str]:
        return [entry.beat for entry in self.entries]

    def criterion_for(self, beat: str) -> str | None:
        for entry in self.entries:
            if entry.beat == beat:
                return entry.criterion
        return None

    def as_records(self) -> list[dict[str, Any]]:
        return [entry.as_record() for entry in self.entries]


def completion_criterion(beat: Beat) -> str:
    """Ask the beat what "done" means; fall back to the generic contract.

    Asking rather than switching on the name is what keeps the Astros/weather specifics
    out of this module.
    """
    declared = getattr(beat, "completion_criterion", None)
    if callable(declared):
        declared = declared()
    if isinstance(declared, str) and declared.strip():
        return declared.strip()
    return GENERIC_CRITERION


def plan_run(
    config: Config,
    preferences: Preferences,
    now: datetime,
    *,
    trace: Any = None,
    scratchpad: Any = None,
    beats: Sequence[Beat] | None = None,
) -> RunPlan:
    """Decide tonight's beats and their completion criteria. No tool calls.

    ``beats`` is injectable so a test can plan over a dummy beat; by default the plan
    covers whatever the config enables in the registry.
    """
    candidates = list(beats) if beats is not None else get_beats(config)

    plan = RunPlan(
        date=now.date().isoformat(),
        day_of_week=now.strftime("%A"),
    )

    context = BeatContext(
        config=config,
        preferences=preferences,
        now=now,
        scratchpad=scratchpad,
        trace=trace,
    )

    for beat in candidates:
        if not beat.should_run(context):
            plan.skipped[beat.name] = "beat.should_run(context) returned False"
            continue
        weight = preferences.weight_for(beat.name)
        if weight <= 0:
            plan.skipped[beat.name] = f"preference weight for {beat.name!r} is {weight}"
            continue
        plan.entries.append(
            PlanEntry(
                beat=beat.name,
                criterion=completion_criterion(beat),
                weight=weight,
            )
        )

    # Higher-weighted topics are planned first; ties keep config order.
    plan.entries.sort(key=lambda entry: -entry.weight)

    if trace is not None:
        trace.plan(plan.as_records())
        for name, reason in plan.skipped.items():
            trace.decision(beat=name, decision="beat_skipped", reason=reason)

    return plan


__all__ = ["GENERIC_CRITERION", "PlanEntry", "RunPlan", "completion_criterion", "plan_run"]

"""Synthesizer — composes the digest, and guarantees its provenance (FR-11).

Three steps, in order:

1. apply the preference profile's suppression rules, recording each with its reason;
2. apply Step 13's escalation ordering;
3. compose the message through the **injected** agent client — the model receives the
   structured values and *phrases* them. It is never asked to supply a number, a score, or
   a state.

Then the part that makes step 3 a guarantee rather than a hope: after composition the
digest is checked against the run's own trace with :func:`forecaster.trace.check_provenance`,
and a violation **fails the run**, loudly, into the trace. A prompt instruction is not a
guarantee; the check is.

## Scope correction — read before adding anything

FR-11's prose says the synthesizer "applies the ledger check". The ledger check **is
FR-9b**, which is `[Later]` and blocked on PRD §9 Q3 (item identity), and FR-9 states
plainly that nothing reads the ledger to make decisions in v1. So this module applies
**escalation ordering and preference suppression only**. It does not read the ledger and
does not invent an identity or dedup key.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from forecaster.agent import AgentClientLike, AgentResponse, DEFAULT_EFFORT
from forecaster.escalation import OrderedItems, apply_escalation
from forecaster.memory.preferences import Preferences, SuppressionDecision, suppression_match
from forecaster.trace import ProvenanceReport, check_provenance

SYSTEM_PROMPT = (
    "You write a short nightly digest. You are given structured values that were already "
    "verified against tool observations. Your only job is to phrase them. "
    "Never add, change, round, estimate, or infer a number, score, or state. "
    "If a value is absent, say it is absent — do not fill the gap."
)

PROMPT = (
    "Write tonight's digest from the values below, in the order given. "
    "Keep every number, score, and state exactly as written."
)


class ProvenanceError(RuntimeError):
    """The composed digest states something the trace cannot back. The run fails."""

    def __init__(self, report: ProvenanceReport) -> None:
        super().__init__(report.summary())
        self.report = report


@dataclass
class Digest:
    """The rendered message plus everything needed to explain how it got that way."""

    text: str
    ordered: OrderedItems
    suppressed: list[tuple[str, SuppressionDecision]] = field(default_factory=list)
    unavailable_lines: list[str] = field(default_factory=list)
    provenance: ProvenanceReport | None = None
    usage: AgentResponse | None = None

    @property
    def beat_order(self) -> list[str]:
        return self.ordered.beat_order

    def delivered_items(self) -> list[Any]:
        return [entry.item for entry in self.ordered.items]


def unavailability_line(beat: str, error: str | None) -> str:
    """The FR-18 line. Names the beat, so the provenance check can find it."""
    reason = f" ({error})" if error else ""
    return f"Couldn't reach {beat} tonight{reason}."


def _filter_suppressed(
    results: Sequence[Any], preferences: Preferences, trace: Any
) -> tuple[list[Any], list[tuple[str, SuppressionDecision]]]:
    """Drop items a suppression rule matches, recording each drop and its reason."""
    kept: list[Any] = []
    suppressed: list[tuple[str, SuppressionDecision]] = []

    for result in results:
        surviving = []
        for item in getattr(result, "items", []) or []:
            decision = suppression_match(item, preferences)
            if decision is None:
                surviving.append(item)
                continue
            suppressed.append((getattr(result, "beat", ""), decision))
            if trace is not None:
                trace.decision(
                    beat=getattr(result, "beat", ""),
                    decision="item_suppressed",
                    reason=decision.reason,
                    rule=decision.rule_id,
                )
        result.items = surviving
        kept.append(result)

    return kept, suppressed


def _structured_payload(
    ordered: OrderedItems, unavailable_lines: Sequence[str]
) -> dict[str, Any]:
    """Exactly the values the model may phrase — nothing else reaches it."""
    return {
        "lines": [
            getattr(entry.item, "text", str(entry.item)) for entry in ordered.items
        ],
        "unavailable": list(unavailable_lines),
    }


def synthesize(
    results: Sequence[Any],
    config: Any,
    preferences: Preferences,
    trace: Any,
    *,
    agent_client: AgentClientLike,
    effort: str = DEFAULT_EFFORT,
    enforce_provenance: bool = True,
) -> Digest:
    """Compose the digest. Raises :class:`ProvenanceError` if it cannot be backed."""
    kept, suppressed = _filter_suppressed(list(results), preferences, trace)
    ordered = apply_escalation(kept, config, trace=trace)

    unavailable_lines = [
        unavailability_line(
            getattr(result, "beat", ""), getattr(result, "error", None)
        )
        for result in ordered.unavailable
    ]

    structured = _structured_payload(ordered, unavailable_lines)
    response = agent_client.complete(
        PROMPT, structured=structured, system=SYSTEM_PROMPT, effort=effort
    )
    text = response.text

    # A failed beat must never silently drop out, whatever the model wrote.
    for line in unavailable_lines:
        if line not in text:
            text = f"{text}\n{line}" if text else line

    digest = Digest(
        text=text,
        ordered=ordered,
        suppressed=suppressed,
        unavailable_lines=unavailable_lines,
        usage=response,
    )

    if trace is not None:
        trace.digest(text, order=ordered.beat_order)
        report = check_provenance(trace.path, text)
        digest.provenance = report
        trace.decision(
            beat="synthesizer",
            decision="provenance_checked",
            reason=report.summary(),
            violations=[str(violation) for violation in report.violations],
        )
        if enforce_provenance and not report.ok:
            raise ProvenanceError(report)

    return digest


__all__ = [
    "PROMPT",
    "SYSTEM_PROMPT",
    "Digest",
    "ProvenanceError",
    "synthesize",
    "unavailability_line",
]

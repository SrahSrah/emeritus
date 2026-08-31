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

## The ledger check (FR-9b) — unblocked 2026-08-02

FR-11's prose always said the synthesizer "applies the ledger check". Through v1 it did
not, because that check *is* FR-9b and FR-9b was blocked on PRD §9 Q3 (item identity).
Q3 is answered, so the check now runs, as step 2 of four:

1. preference suppression;
2. **retrieval-backed dedup** — for each surviving item, search the sent-item ledger for
   near neighbours — plus, since FR-37, the items already kept in this run, same beat —
   and decide include / reframe / suppress;
3. escalation ordering;
4. composition through the injected client, then the provenance check.

Dedup sits **before** escalation on purpose: escalation decides what leads, and it should
rank what is actually going to be said. The safety invariants that keep step 2 from
silencing a real fact live in `forecaster.memory.dedup` — in particular, an item whose
checkable value differs from its nearest neighbour's can be reframed but never suppressed.

Passing `retriever=None` disables step 2 entirely and restores exactly the v1 behaviour.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from forecaster.agent import AgentClientLike, AgentResponse, DEFAULT_EFFORT
from forecaster.escalation import OrderedItems, apply_escalation
from forecaster.memory.dedup import DedupDecision, assess_item
from forecaster.memory.retrieval import SAME_RUN_SENT_ITEM_ID

#: FR-40 — one-way cross-beat deferral. Beats named here additionally compare their
#: cleared candidates against the run's already-kept items from OTHER beats, and a
#: suppression driven by such a neighbour is recorded as a deferral naming the covering
#: beat. Dedup policy, not beat registration: adding a beat still edits nothing here,
#: and no other beat ever sees a deferring beat's candidates as neighbours.
CROSS_BEAT_DEFER = ("need_to_know",)
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


#: What the reader is told, per violation kind. Deliberately does **not** echo the
#: offending text: repeating an ungrounded phrase inside the notice that withholds it
#: would put the unverifiable words in front of the reader anyway, which is the one thing
#: the withholding exists to prevent. The full detail goes to the trace.
QUARANTINE_REASONS = {
    "ungrounded_number": "a figure in it could not be traced to a retrieved passage",
    "ungrounded_quote": "a quoted phrase in it could not be traced to a retrieved passage",
    "ungrounded_item": "it pointed at no retrieved passage",
}


def quarantine_line(beat: str, kind: str) -> str:
    """The FR-30 line. Names the beat and the kind of failure, never the failing words."""
    reason = QUARANTINE_REASONS.get(kind, "it failed the provenance check")
    return f"One {beat} item was withheld: {reason}."


@dataclass
class Digest:
    """The rendered message plus everything needed to explain how it got that way."""

    text: str
    ordered: OrderedItems
    suppressed: list[tuple[str, SuppressionDecision]] = field(default_factory=list)
    unavailable_lines: list[str] = field(default_factory=list)
    provenance: ProvenanceReport | None = None
    usage: AgentResponse | None = None
    dedup: list[tuple[str, DedupDecision]] = field(default_factory=list)
    quarantined: list[tuple[str, str]] = field(default_factory=list)
    #: Each beat's declared checkable facts, carried to the ledger write so a delivered
    #: row records them alongside `fields`. FR-19's disjoint-key clause is only as good
    #: as the neighbour's recorded keys — a row without them reads as "never told".
    checkable_by_beat: dict[str, dict[str, Any]] = field(default_factory=dict)

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


def _apply_dedup(
    results: Sequence[Any],
    retriever: Any,
    trace: Any,
    *,
    agent_client: AgentClientLike,
    now: Any = None,
    effort: str = DEFAULT_EFFORT,
    exempt_beats: Sequence[str] = (),
) -> list[tuple[str, DedupDecision]]:
    """FR-9b, plus FR-37, minus FR-44's exempt beats. Mutates items in place.

    An unavailable beat is skipped entirely — it has no items, and FR-18's "couldn't
    reach X tonight" line is generated later and is never a dedup candidate.

    FR-37: each candidate is also compared against the items already **kept in this
    run**, same beat only, handed to `assess_item` as ordinary neighbours. Two topics
    writing up one story used to survive because the stored index only knows previous
    nights — and the model would note the duplication in prose, which is a guard's job
    done in prose. Every FR-19 invariant applies to a same-run neighbour unchanged.

    FR-44: a beat named in ``exempt_beats`` bypasses all of it — no retrieval, no
    same-run neighbours, no judgment — with an explicit ``dedup_exempt`` record per
    item. This is a bypass *around* the machinery, not a change to it: Sarah's venue
    listings should repeat nightly while she decides (2026-08-16), and repetition on
    purpose must cost zero embedder and zero model work. Exempt items also never join
    the same-run pool: nothing may defer to, or be reframed against, a standing listing.
    """
    decisions: list[tuple[str, DedupDecision]] = []
    kept_this_run: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    exempt = set(exempt_beats)

    for result in results:
        beat = getattr(result, "beat", "")
        if not getattr(result, "available", True):
            continue

        if beat in exempt:
            for item in getattr(result, "items", []) or []:
                decision = DedupDecision(
                    "include",
                    "beat opts out by config; repeats are deliberate",
                    forced=True,
                )
                decisions.append((beat, decision))
                if trace is not None:
                    trace.decision(
                        beat=beat,
                        decision="dedup_exempt",
                        reason=decision.reason,
                        **decision.as_record(),
                    )
            continue

        prior = kept_this_run.setdefault(beat, [])
        surviving: list[Any] = []
        # The beat-declared checkable facts ride along on both sides of FR-19's first
        # invariant: as the candidate's `result_checkable`, and merged into the surface
        # a kept item presents as a same-run neighbour. A wsb ticker count lives only
        # here, not in `BeatItem.fields` — comparing `fields` alone is the measured
        # 2026-08-31 gap (one wsb line suppressed against disjoint facts).
        declared = dict(getattr(result, "checkable_fields", None) or {})
        for item in getattr(result, "items", []) or []:
            text = getattr(item, "text", str(item))
            try:
                neighbours = retriever.neighbours_for(text, beat=beat, now=now)
                same_run = getattr(retriever, "same_run_neighbours", None)
                if same_run is not None and prior:
                    neighbours = [*neighbours, *same_run(text, prior, beat=beat)]
                # FR-40: a deferring beat also sees the other beats' kept items —
                # stamped with their source beat, so a deferral can name its cover.
                if same_run is not None and beat in CROSS_BEAT_DEFER:
                    for other_beat, other_prior in kept_this_run.items():
                        if other_beat == beat or not other_prior:
                            continue
                        neighbours = [
                            *neighbours,
                            *same_run(text, other_prior, beat=other_beat),
                        ]
                neighbours = sorted(
                    neighbours,
                    key=lambda neighbour: neighbour.similarity,
                    reverse=True,
                )
            except Exception as exc:  # noqa: BLE001 - invariant 4: never silence a digest
                neighbours = []
                if trace is not None:
                    trace.decision(
                        beat=beat,
                        decision="retrieval_failed",
                        reason=f"{type(exc).__name__}: {exc}; including the item unchecked",
                    )
                surviving.append(item)
                prior.append(
                    (text, {**declared, **dict(getattr(item, "fields", None) or {})})
                )
                continue

            decision = assess_item(
                item,
                neighbours,
                agent_client=agent_client,
                beat=beat,
                escalation_candidate=bool(getattr(result, "escalation_candidate", False)),
                effort=effort,
                result_checkable=declared,
            )
            decisions.append((beat, decision))

            # FR-40: a suppression whose strongest same-run neighbour lives in another
            # beat is a deferral, and the trace names the cover — "already told, by the
            # beat whose job that story was" is a different fact from "adds nothing".
            covering_beat: str | None = None
            if decision.action == "suppress" and beat in CROSS_BEAT_DEFER:
                for neighbour in decision.neighbours:
                    if (
                        neighbour.sent_item_id == SAME_RUN_SENT_ITEM_ID
                        and neighbour.beat != beat
                    ):
                        covering_beat = neighbour.beat
                        break

            if trace is not None:
                if covering_beat is not None:
                    trace.decision(
                        beat=beat,
                        decision="ntk_deferred",
                        reason=f"already covered by the {covering_beat} beat this run: "
                        + decision.reason,
                        covering_beat=covering_beat,
                        **decision.as_record(),
                    )
                else:
                    trace.decision(
                        beat=beat,
                        decision=f"dedup_{decision.action}",
                        reason=decision.reason,
                        **decision.as_record(),
                    )

            if decision.action == "suppress":
                continue
            if decision.action == "reframe" and decision.reframed_text:
                # Reframing may re-order a sentence; it may never restate a value. The
                # FR-11 provenance check still runs over the final text and would fail
                # the run if a number moved.
                item.text = decision.reframed_text
            surviving.append(item)
            # The delivered text (post-reframe) is what later candidates compare against.
            prior.append(
                (
                    getattr(item, "text", str(item)),
                    {**declared, **dict(getattr(item, "fields", None) or {})},
                )
            )

        result.items = surviving

    return decisions


def _structured_payload(ordered: OrderedItems) -> dict[str, Any]:
    """Exactly the values the model may phrase — nothing else reaches it.

    FR-18 and FR-30 lines are deliberately absent: both are code-assembled after
    composition, because a line the model is handed is a line the model may reword —
    and then a verbatim safety-net append tells the reader twice.
    """
    return {
        "lines": [
            getattr(entry.item, "text", str(entry.item)) for entry in ordered.items
        ],
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
    retriever: Any = None,
    now: Any = None,
) -> Digest:
    """Compose the digest. Raises :class:`ProvenanceError` if it cannot be backed."""
    kept, suppressed = _filter_suppressed(list(results), preferences, trace)

    dedup_decisions: list[tuple[str, DedupDecision]] = []
    if retriever is not None:
        dedup_decisions = _apply_dedup(
            kept,
            retriever,
            trace,
            agent_client=agent_client,
            now=now,
            effort=effort,
            exempt_beats=getattr(
                getattr(config, "retrieval", None), "exempt_beats", []
            )
            or [],
        )

    ordered = apply_escalation(kept, config, trace=trace)

    unavailable_lines = [
        unavailability_line(
            getattr(result, "beat", ""), getattr(result, "error", None)
        )
        for result in ordered.unavailable
    ]

    structured = _structured_payload(ordered)
    response = agent_client.complete(
        PROMPT, structured=structured, system=SYSTEM_PROMPT, effort=effort
    )
    text = response.text

    # The FR-18 line never reaches the model, for the FR-30 reason: handed over as a
    # value to phrase, the model may reword it — and then a verbatim `in` check misses
    # and appends the canonical line too, telling the reader twice. Code-assembled only.
    # The provenance check stays satisfied: it requires the digest to *name* the failed
    # beat, and unavailability_line always does.
    for line in unavailable_lines:
        text = f"{text}\n{line}" if text else line

    digest = Digest(
        text=text,
        ordered=ordered,
        suppressed=suppressed,
        unavailable_lines=unavailable_lines,
        usage=response,
        dedup=dedup_decisions,
        checkable_by_beat={
            getattr(result, "beat", ""): dict(getattr(result, "checkable_fields", None) or {})
            for result in results
            if getattr(result, "available", True)
        },
    )

    if trace is None:
        return digest

    trace.digest(text, order=ordered.beat_order)
    report = check_provenance(trace.path, text)
    trace.decision(
        beat="synthesizer",
        decision="provenance_checked",
        reason=report.summary(),
        violations=[str(violation) for violation in report.violations],
    )

    # FR-30. A violation the checker can pin to one item costs that item, not the night.
    # Failing the whole run over one ungrounded sentence means no Astros score, no
    # forecast, and an empty inbox at 7 pm — which is the quietest failure there is, and
    # FR-18's whole position is that going quiet is worse than saying less.
    if not report.ok and report.item_violations and not report.fatal_violations:
        text, report = _quarantine_and_recompose(
            digest,
            report,
            ordered,
            unavailable_lines,
            trace,
            agent_client=agent_client,
            effort=effort,
        )

    digest.provenance = report
    if enforce_provenance and not report.ok:
        raise ProvenanceError(report)

    return digest


def _quarantine_and_recompose(
    digest: Digest,
    report: ProvenanceReport,
    ordered: OrderedItems,
    unavailable_lines: Sequence[str],
    trace: Any,
    *,
    agent_client: AgentClientLike,
    effort: str,
) -> tuple[str, ProvenanceReport]:
    """Drop the items the checker pinned, recompose once, and re-check.

    Exactly one retry. If the recomposed digest still fails, the run fails — a loop that
    kept dropping items until something passed would be a machine for producing an empty,
    confident digest, which is the opposite of the point.
    """
    doomed = set(report.quarantinable_texts())
    kinds = {
        violation.item_text: violation.kind
        for violation in report.item_violations
        if violation.item_text
    }
    details = {
        violation.item_text: violation.detail
        for violation in report.item_violations
        if violation.item_text
    }

    kept = [entry for entry in ordered.items if getattr(entry.item, "text", "") not in doomed]
    if len(kept) == len(ordered.items):
        return digest.text, report

    for entry in ordered.items:
        item_text = getattr(entry.item, "text", "")
        if item_text not in doomed:
            continue
        beat = getattr(entry, "beat", "") or getattr(entry.item, "beat", "")
        kind = kinds.get(item_text, "")
        digest.quarantined.append((beat, kind))
        trace.decision(
            beat=beat,
            decision="item_quarantined",
            reason=f"withheld from the digest: {details.get(item_text, kind)}",
            kind=kind,
            item_text=item_text,
        )

    ordered.items = kept
    quarantine_lines = [quarantine_line(beat, kind) for beat, kind in digest.quarantined]

    # Neither the FR-30 notice nor the FR-18 line reaches the model. Handed over as a
    # value to phrase, the model may paraphrase either — and then a verbatim safety-net
    # append fires anyway, telling the reader twice (run 20260828T202927). Both are
    # code-assembled only.
    structured = _structured_payload(ordered)
    response = agent_client.complete(
        PROMPT, structured=structured, system=SYSTEM_PROMPT, effort=effort
    )
    text = response.text
    for line in list(unavailable_lines) + quarantine_lines:
        text = f"{text}\n{line}" if text else line

    digest.text = text
    digest.usage = response
    trace.digest(text, order=ordered.beat_order)
    recheck = check_provenance(trace.path, text, excluded_items=doomed)
    trace.decision(
        beat="synthesizer",
        decision="provenance_rechecked",
        reason=recheck.summary(),
        violations=[str(violation) for violation in recheck.violations],
        quarantined=len(digest.quarantined),
    )
    return text, recheck


__all__ = [
    "PROMPT",
    "SYSTEM_PROMPT",
    "Digest",
    "ProvenanceError",
    "synthesize",
    "unavailability_line",
]

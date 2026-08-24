"""The need-to-know beat's v4 metric, computed from run traces (FR-35).

PRD §2 names three conditions for the observation increment. Each is computable from
``data/runs/*.jsonl`` and nothing else — the same standard as ``news_metric``, whose
shape this module copies deliberately.

    (a) silence accounted    every available run records observations or no_candidates
    (b) count provenance     every count matches its resolvable observation's payload
    (c) evidence accumulates nights with distribution records vs TARGET_NIGHTS

The hard problem this metric exists for: **a beat that correctly stays silent looks
identical in the inbox to one that broke.** So nothing here counts deliveries — v4
delivers nothing by design. What it measures is the *accounting for silence*, and what
it additionally prints — the corroboration distribution — is the evidence §9 Q1/Q2 need
before any bar value can honestly be called measured.

This module reports; it gates nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any, Iterable, Mapping, Sequence

from forecaster.news_metric import Condition
from forecaster.trace import read_trace, records_of

#: §2(c) is measured across this many nights.
#:
#: **The parent PRD says fourteen. This is two — Sarah's call, 2026-08-16**, replacing
#: the initial one-night development concession: two nights of corroboration
#: distribution is the gate she set before building the bar (v5, FR-36/FR-38…FR-41).
#: It is still a divergence from fourteen, in the DIVERGENCES row 9 posture — a
#: checkpoint must not present a two-night result as the fourteen-night one.
TARGET_NIGHTS = 2

NTK_BEAT = "need_to_know"


@dataclass
class NtkMetricReport:
    conditions: list[Condition] = field(default_factory=list)
    runs_examined: int = 0
    nights_accumulated: int = 0
    #: night (YYYY-MM-DD) → list of corroboration counts observed that night.
    distribution: dict[str, list[int]] = field(default_factory=dict)
    #: night → candidates that cleared the mechanical gate (count >= min_sources).
    #: Only nights whose decisions carry `min_sources` (v5 onward) appear here —
    #: pre-v5 history is not recomputed under a config it never ran with.
    gate_passes: dict[str, int] = field(default_factory=dict)
    #: night → True when at least one story item delivered (bar or watchlist).
    delivering_nights: dict[str, bool] = field(default_factory=dict)
    #: source name → {"article": n, "summary": n} — §8's fetch-degradation watch.
    text_sources: dict[str, dict[str, int]] = field(default_factory=dict)
    caveats: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Only applicable conditions can fail. An `n/a` is not a pass."""
        return all(c.passed for c in self.conditions if c.applicable)

    def condition(self, key: str) -> Condition:
        for item in self.conditions:
            if item.key == key:
                return item
        raise KeyError(key)

    def summary(self) -> str:
        lines = [
            f"need-to-know metric over {self.runs_examined} run(s), "
            f"{self.nights_accumulated} night(s) accumulated:"
        ]
        for condition in self.conditions:
            lines.append(f"  [{condition.status:>4}] {condition.title} — {condition.detail}")
        if self.distribution:
            lines.append(
                "  corroboration distribution (evidence for tuning Q1/Q2 — not a result):"
            )
            for night in sorted(self.distribution):
                counts = self.distribution[night]
                gate = (
                    f", gate-pass {self.gate_passes[night]}"
                    if night in self.gate_passes
                    else ", gate-pass n/a (pre-v5 trace)"
                )
                lines.append(
                    f"    {night}: {len(counts)} candidate(s), "
                    f"max {max(counts)}, median {median(counts):g}{gate}"
                )
        if self.text_sources:
            lines.append("  text sources (a thinning corpus shows up here first):")
            for source in sorted(self.text_sources):
                split = self.text_sources[source]
                lines.append(
                    f"    {source}: {split.get('article', 0)} article, "
                    f"{split.get('summary', 0)} summary"
                )
        lines.extend(f"  note: {caveat}" for caveat in self.caveats)
        return "\n".join(lines)


def _ntk_results(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records_of(records, "beat_result")
        if record.get("beat") == NTK_BEAT
    ]


def _ntk_decisions(
    records: Sequence[Mapping[str, Any]], kind: str
) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records_of(records, "decision")
        if record.get("beat") == NTK_BEAT and record.get("decision") == kind
    ]


def check_ntk_metric(trace_paths: Iterable[str | Path]) -> NtkMetricReport:
    """Compute PRD §2's three v4 conditions over one or more traces."""
    report = NtkMetricReport()

    unaccounted: list[str] = []
    provenance_failures: list[str] = []
    judgment_unaccounted: list[str] = []
    carveout_violations: list[str] = []
    bar_ran_anywhere = False
    nights: set[str] = set()

    for path in (Path(item) for item in trace_paths):
        try:
            records = read_trace(path)
        except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
            report.caveats.append(f"{path.name} could not be read ({exc})")
            continue

        results = _ntk_results(records)
        if not results:
            continue
        report.runs_examined += 1

        night = ""
        for record in records_of(records, "run_start"):
            night = str(record.get("at", ""))[:10]
            break
        if night:
            nights.add(night)

        observed = _ntk_decisions(records, "corroboration_observed")
        quiet = _ntk_decisions(records, "no_candidates")
        available = all(bool(result.get("available")) for result in results)

        # (a) — an available run must positively account for its silence. An unavailable
        # one is accounted by the FR-18 shape itself.
        if available and not observed and len(quiet) != 1:
            unaccounted.append(
                f"{path.name}: available, but no corroboration_observed and "
                f"{len(quiet)} no_candidates decision(s) — silence unaccounted"
            )

        # (b) — every count traces to a resolvable observation whose payload agrees.
        observations = {
            str(record.get("observation_id")): record
            for record in records_of(records, "observation")
        }
        for decision in observed:
            label = f"{path.name}: {str(decision.get('url', '?'))[:60]}"
            record = observations.get(str(decision.get("observation")))
            if record is None:
                provenance_failures.append(f"{label} points at no observation")
                continue
            payload = record.get("payload") or {}
            corroborators = payload.get("corroborators")
            if not isinstance(corroborators, dict):
                provenance_failures.append(f"{label} observation carries no corroborators")
                continue
            count = decision.get("count")
            if count != len(corroborators) or sorted(corroborators) != list(
                decision.get("sources") or []
            ):
                provenance_failures.append(
                    f"{label} says count={count!r} but the observation holds "
                    f"{len(corroborators)} source(s)"
                )
            source = str(payload.get("source", "?"))
            text_source = str(payload.get("text_source", "?"))
            split = report.text_sources.setdefault(source, {})
            split[text_source] = split.get(text_source, 0) + 1

        if observed and night:
            report.distribution.setdefault(night, []).extend(
                int(decision.get("count") or 0) for decision in observed
            )

        # ---- v5, FR-41: the bar phase ---------------------------------------- #
        watchlist_hits = _ntk_decisions(records, "watchlist_hit")
        delivered = _ntk_decisions(records, "ntk_delivered")
        suppressed = _ntk_decisions(records, "ntk_suppressed")
        deferred = _ntk_decisions(records, "ntk_deferred")
        abstentions = _ntk_decisions(records, "ntk_judgment_unavailable")
        v5_run = any(
            decision.get("min_sources") is not None for decision in observed
        ) or bool(watchlist_hits or delivered or suppressed or abstentions)
        if not v5_run:
            continue
        bar_ran_anywhere = True

        hit_urls = {str(record.get("url")) for record in watchlist_hits}
        gate_passers = [
            decision
            for decision in observed
            if decision.get("min_sources") is not None
            and int(decision.get("count") or 0) >= int(decision.get("min_sources"))
            and str(decision.get("url")) not in hit_urls
        ]
        if night:
            report.gate_passes[night] = len(gate_passers)
            report.delivering_nights[night] = bool(delivered or watchlist_hits)

        # (d) — every gate-passing candidate ends in exactly one recorded outcome,
        # and the pulse line's declared counts match the tally.
        unassessed = sum(int(record.get("unassessed") or 0) for record in abstentions)
        accounted = len(delivered) + len(suppressed) + unassessed
        if accounted != len(gate_passers):
            judgment_unaccounted.append(
                f"{path.name}: {len(gate_passers)} gate-passing candidate(s) but "
                f"{accounted} outcome(s) recorded"
            )
        for result in results:
            checkable = dict(result.get("checkable_fields") or {})
            if "ntk_watched" in checkable and checkable["ntk_watched"] != len(observed):
                judgment_unaccounted.append(
                    f"{path.name}: pulse claims {checkable['ntk_watched']} watched but "
                    f"{len(observed)} were observed"
                )
            if "ntk_unassessed" in checkable and checkable["ntk_unassessed"] != unassessed:
                judgment_unaccounted.append(
                    f"{path.name}: pulse claims {checkable['ntk_unassessed']} unassessed "
                    f"but the abstention records tally {unassessed}"
                )

        # (e) — the carve-out held. A watchlist hit may never be suppressed, and a
        # watchlist night can never defer at all: the escalated result skips the
        # dedup judgment wholesale (FR-19 invariant 2), so any deferral alongside a
        # hit means the invariant broke somewhere.
        suppressed_hit_urls = hit_urls & {
            str(record.get("url")) for record in suppressed
        }
        for url in sorted(suppressed_hit_urls):
            carveout_violations.append(f"{path.name}: watchlist hit suppressed: {url}")
        if hit_urls and deferred:
            carveout_violations.append(
                f"{path.name}: {len(deferred)} deferral(s) on a watchlist night — "
                "invariant 2 should have made the result untouchable"
            )

    report.nights_accumulated = len(nights)

    report.conditions.append(
        Condition(
            key="silence_accounted",
            title="(a) silence is accounted",
            passed=not unaccounted,
            applicable=report.runs_examined > 0,
            detail=(
                "every available run records candidates or an explicit no_candidates"
                if report.runs_examined and not unaccounted
                else "; ".join(unaccounted[:3])
                if unaccounted
                else "the beat appears in no examined run"
            ),
        )
    )

    report.conditions.append(
        Condition(
            key="count_provenance",
            title="(b) corroboration provenance",
            passed=not provenance_failures,
            applicable=report.runs_examined > 0,
            detail=(
                "every count matches its resolvable observation"
                if report.runs_examined and not provenance_failures
                else "; ".join(provenance_failures[:3])
                if provenance_failures
                else "the beat appears in no examined run"
            ),
        )
    )

    nights_with_evidence = len(report.distribution)
    evidence_met = nights_with_evidence >= TARGET_NIGHTS
    report.conditions.append(
        Condition(
            key="evidence_accumulates",
            title="(c) evidence accumulates",
            passed=evidence_met,
            applicable=report.runs_examined > 0,
            detail=(
                f"{nights_with_evidence} of {TARGET_NIGHTS} night(s) carry "
                "distribution records"
            ),
        )
    )
    report.conditions.append(
        Condition(
            key="judgment_accounted",
            title="(d) no unaccounted judgment",
            passed=not judgment_unaccounted,
            applicable=bar_ran_anywhere,
            detail=(
                "every gate-passing candidate ended in exactly one recorded outcome"
                if bar_ran_anywhere and not judgment_unaccounted
                else "; ".join(judgment_unaccounted[:3])
                if judgment_unaccounted
                else "no run examined carries bar decisions (pre-v5 traces)"
            ),
        )
    )
    report.conditions.append(
        Condition(
            key="carveout_held",
            title="(e) the carve-out held",
            passed=not carveout_violations,
            applicable=bar_ran_anywhere,
            detail=(
                "zero watchlist hits suppressed or deferred"
                if bar_ran_anywhere and not carveout_violations
                else "; ".join(carveout_violations[:3])
                if carveout_violations
                else "no run examined carries bar decisions (pre-v5 traces)"
            ),
        )
    )
    if bar_ran_anywhere:
        delivering = sum(1 for value in report.delivering_nights.values() if value)
        window = len(report.delivering_nights)
        report.conditions.append(
            Condition(
                key="calibration_band",
                title="(f) calibration band (report-only)",
                passed=True,  # never pass/fail: a loud or quiet fortnight is reality
                applicable=True,
                detail=(
                    f"{delivering} delivering night(s) over {window} bar night(s) "
                    "accumulated; Sarah's target is 2–3 per 14 — drift is a retuning "
                    "signal, not a failure"
                ),
            )
        )

    report.caveats.append(
        "(c) counts nights with distribution records, not real scheduled nights — a "
        f"trace cannot tell a 7 pm run from a development rerun. TARGET_NIGHTS is "
        f"{TARGET_NIGHTS} (Sarah's gate, 2026-08-16, DIVERGENCES row 9 posture); the "
        "parent PRD says 14."
    )
    report.caveats.append(
        "the distribution is evidence for tuning the corroboration floor, window, and "
        "any future bar (§9 Q1/Q2) — it validates nothing by existing."
    )

    return report


__all__ = [
    "NTK_BEAT",
    "TARGET_NIGHTS",
    "NtkMetricReport",
    "check_ntk_metric",
]

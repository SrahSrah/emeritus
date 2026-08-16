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
                lines.append(
                    f"    {night}: {len(counts)} candidate(s), "
                    f"max {max(counts)}, median {median(counts):g}"
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
    report.caveats.append(
        "(c) counts nights with distribution records, not real scheduled nights — a "
        "trace cannot tell a 7 pm run from a development rerun. TARGET_NIGHTS is 1, a "
        "recorded development concession (DIVERGENCES row 9); the parent PRD says 14."
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

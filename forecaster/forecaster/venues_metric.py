"""The venue-listings beat's metric, computed from run traces (FR-46).

PRD §2 names three conditions. The load-bearing one is **(b) never suppressed** — the
inverse of every other beat's dedup expectations. Sarah's requirement is that a standing
listing repeats nightly while she decides; this checker is what turns "it should repeat"
into something the ledger can prove. A single suppression or reframe of a venue item
fails the metric, and on any run where the dedup pass ran, every delivered venue item
must carry its explicit ``dedup_exempt`` record — repeats by design, not by outage.

Same posture as the sibling checkers: report-only, trace-only, and n/a is not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from forecaster.news_metric import Condition
from forecaster.trace import read_trace, records_of

VENUES_BEAT = "venues"


@dataclass
class VenuesMetricReport:
    conditions: list[Condition] = field(default_factory=list)
    runs_examined: int = 0
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
        lines = [f"venues metric over {self.runs_examined} run(s):"]
        for condition in self.conditions:
            lines.append(f"  [{condition.status:>4}] {condition.title} — {condition.detail}")
        lines.extend(f"  note: {caveat}" for caveat in self.caveats)
        return "\n".join(lines)


def _venue_results(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records_of(records, "beat_result")
        if record.get("beat") == VENUES_BEAT
    ]


def _decisions_of(
    records: Sequence[Mapping[str, Any]], *names: str
) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records_of(records, "decision")
        if record.get("beat") == VENUES_BEAT and record.get("decision") in names
    ]


def check_venues_metric(trace_paths: Iterable[str | Path]) -> VenuesMetricReport:
    """Compute PRD §2's three conditions over one or more traces."""
    report = VenuesMetricReport()

    provenance_failures: list[str] = []
    suppressions: list[str] = []
    unaccounted_exempt: list[str] = []
    silent_runs: list[str] = []

    for path in (Path(item) for item in trace_paths):
        try:
            records = read_trace(path)
        except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
            report.caveats.append(f"{path.name} could not be read ({exc})")
            continue

        results = _venue_results(records)
        if not results:
            continue
        report.runs_examined += 1

        # (a) — the final provenance verdict of a delivered run, scoped to this beat.
        # The FIRST verdict can be superseded by an FR-30 recheck, exactly as the news
        # metric learned on 2026-08-04.
        delivered = any(
            bool(record.get("success")) for record in records_of(records, "delivery")
        )
        if delivered:
            verdicts = [
                record
                for record in records_of(records, "decision")
                if record.get("decision")
                in ("provenance_checked", "provenance_rechecked")
            ]
            if verdicts:
                for violation in verdicts[-1].get("violations") or []:
                    if VENUES_BEAT in str(violation):
                        provenance_failures.append(f"{path.name}: {violation}")

        # (b) — never suppressed, and every delivered item's repeat is deliberate.
        for record in records_of(records, "decision"):
            if record.get("decision") not in ("dedup_suppress", "dedup_reframe"):
                continue
            if record.get("beat") == VENUES_BEAT:
                suppressions.append(f"{path.name}: {record.get('decision')}")
        dedup_ran = any(
            str(record.get("decision", "")).startswith("dedup_")
            for record in records_of(records, "decision")
        )
        if dedup_ran:
            item_count = sum(
                len(result.get("items") or [])
                for result in results
                if result.get("available")
            )
            exempt_count = len(_decisions_of(records, "dedup_exempt"))
            if item_count != exempt_count:
                unaccounted_exempt.append(
                    f"{path.name}: {item_count} venue item(s) but {exempt_count} "
                    "dedup_exempt record(s) — a repeat must be deliberate, on the record"
                )

        # (c) — quiet is explicit: an available run always says something per venue.
        for result in results:
            if not result.get("available"):
                continue  # broken is the FR-18 shape, accounted by itself
            has_items = bool(result.get("items"))
            has_decisions = bool(
                _decisions_of(records, "venue_listed", "venue_quiet", "venue_unavailable")
            )
            if not has_items or not has_decisions:
                silent_runs.append(
                    f"{path.name}: available but "
                    f"{'no items' if not has_items else 'no venue decisions'} — "
                    "quiet and broken have collapsed"
                )

    applicable = report.runs_examined > 0
    na = "the beat appears in no examined run"

    report.conditions.append(
        Condition(
            key="listing_provenance",
            title="(a) listing provenance",
            passed=not provenance_failures,
            applicable=applicable,
            detail=(
                "no venue claim failed the final provenance verdict"
                if applicable and not provenance_failures
                else "; ".join(provenance_failures[:3]) if provenance_failures else na
            ),
        )
    )
    report.conditions.append(
        Condition(
            key="never_suppressed",
            title="(b) never suppressed",
            passed=not suppressions and not unaccounted_exempt,
            applicable=applicable,
            detail=(
                "zero suppressions or reframes; every repeat is on the record"
                if applicable and not suppressions and not unaccounted_exempt
                else "; ".join((suppressions + unaccounted_exempt)[:3])
                if suppressions or unaccounted_exempt
                else na
            ),
        )
    )
    report.conditions.append(
        Condition(
            key="quiet_is_explicit",
            title="(c) quiet is explicit",
            passed=not silent_runs,
            applicable=applicable,
            detail=(
                "every available run states listings, a quiet line, or a named outage"
                if applicable and not silent_runs
                else "; ".join(silent_runs[:3]) if silent_runs else na
            ),
        )
    )
    report.caveats.append(
        "condition (b) is the inverse of every other beat's dedup expectation — it "
        "audits Sarah's repeats-are-deliberate requirement (2026-08-16), and it holds "
        "only while [retrieval].exempt_beats keeps naming this beat."
    )
    return report


__all__ = ["VENUES_BEAT", "VenuesMetricReport", "check_venues_metric"]

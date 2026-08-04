"""The news beat's success metric, computed from run traces (FR-29).

PRD §2 names four conditions. Each is computable from ``data/runs/*.jsonl`` and nothing
else, which is the same standard the parent PRD's §2(a) set: a metric that needs a human
to interpret it is an opinion wearing a number.

    (a) grounded prose        zero ungrounded_number / ungrounded_quote, ever
    (b) attribution           every delivered news item points at a resolvable chunk
    (c) organic dedup         at least one suppression or reframe on unseeded history
    (d) no silent loss        every produced item ends in a recorded outcome

This module reports; it gates nothing. A failing metric is something to read, not
something that stops tonight's digest.

## What (c) cannot know, and says so

§2(c) requires the suppression to have happened against **organically accumulated**
history rather than a hand-seeded ledger — that is what retires DIVERGENCES row 4. The
traces record what each run did; they do not record where the ledger's rows came from. So
this checker reports the evidence it has (how many nights, how many suppressions) and
states plainly that organic-vs-seeded is not determinable from traces alone. Claiming
otherwise would be exactly the kind of unearned confidence the whole project is against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from forecaster.trace import read_trace, records_of

#: §2(c) is measured across this many consecutive nights.
TARGET_NIGHTS = 14

NEWS_BEAT = "news"


@dataclass
class Condition:
    """One of §2's four conditions, and whether the traces satisfy it."""

    key: str
    title: str
    passed: bool
    detail: str
    applicable: bool = True

    @property
    def status(self) -> str:
        if not self.applicable:
            return "n/a"
        return "pass" if self.passed else "FAIL"


@dataclass
class NewsMetricReport:
    conditions: list[Condition] = field(default_factory=list)
    runs_examined: int = 0
    nights_accumulated: int = 0
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
            f"news metric over {self.runs_examined} run(s), "
            f"{self.nights_accumulated} night(s) accumulated:"
        ]
        for condition in self.conditions:
            lines.append(f"  [{condition.status:>4}] {condition.title} — {condition.detail}")
        lines.extend(f"  note: {caveat}" for caveat in self.caveats)
        return "\n".join(lines)


def _news_results(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records_of(records, "beat_result")
        if record.get("beat") == NEWS_BEAT
    ]


def _news_decisions(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records_of(records, "decision")
        if record.get("beat") == NEWS_BEAT
    ]


def check_news_metric(trace_paths: Iterable[str | Path]) -> NewsMetricReport:
    """Compute PRD §2's four conditions over one or more traces."""
    paths = [Path(path) for path in trace_paths]
    report = NewsMetricReport()

    ungrounded: list[str] = []
    orphan_items: list[str] = []
    attributed = 0
    suppressions_or_reframes = 0
    unaccounted: list[str] = []
    dedup_ran_anywhere = False
    nights: set[str] = set()

    for path in paths:
        try:
            records = read_trace(path)
        except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
            report.caveats.append(f"{path.name} could not be read ({exc})")
            continue

        results = _news_results(records)
        if not results:
            continue

        report.runs_examined += 1
        for record in records_of(records, "run_start"):
            stamp = str(record.get("at", ""))
            if stamp:
                nights.add(stamp[:10])
            break

        observations = {
            str(record.get("observation_id")): record
            for record in records_of(records, "observation")
        }

        # (a) — reuse the provenance checker's own verdict rather than re-deriving it.
        for record in records_of(records, "decision"):
            if record.get("decision") != "provenance_checked":
                continue
            for violation in record.get("violations") or []:
                text = str(violation)
                if "ungrounded_number" in text or "ungrounded_quote" in text:
                    ungrounded.append(f"{path.name}: {text}")

        decisions = _news_decisions(records)

        for result in results:
            produced = list(result.get("items") or [])

            # (b) — attribution. Unavailability lines are not retrieved from anything and
            # are exempt; they are policed by FR-28 instead.
            for item in produced:
                fields = dict(item.get("fields") or {})
                if fields.get("text_origin") is None:
                    continue
                linked = [str(oid) for oid in (item.get("observations") or [])]
                if not linked:
                    orphan_items.append(f"{path.name}: {item.get('text', '')[:60]!r}")
                    continue
                missing = [oid for oid in linked if oid not in observations]
                if missing:
                    orphan_items.append(
                        f"{path.name}: {item.get('text', '')[:60]!r} points at "
                        f"unresolvable {missing}"
                    )
                    continue
                attributed += 1

            # (d) — every produced item ends in exactly one recorded outcome.
            dedup = [d for d in decisions if str(d.get("decision", "")).startswith("dedup_")]
            preference = [d for d in decisions if d.get("decision") == "item_suppressed"]
            if dedup:
                dedup_ran_anywhere = True
                accounted = len(dedup) + len(preference)
                if accounted != len(produced):
                    unaccounted.append(
                        f"{path.name}: {len(produced)} item(s) produced but "
                        f"{accounted} outcome(s) recorded"
                    )
                for decision in dedup + preference:
                    if not str(decision.get("reason", "")).strip():
                        unaccounted.append(
                            f"{path.name}: a {decision.get('decision')} carries no reason"
                        )

            # (c) — evidence of dedup doing something.
            suppressions_or_reframes += sum(
                1
                for d in decisions
                if d.get("decision") in ("dedup_suppress", "dedup_reframe")
            )

    report.nights_accumulated = len(nights)

    report.conditions.append(
        Condition(
            key="grounded_prose",
            title="(a) grounded prose",
            passed=not ungrounded,
            detail=(
                "no ungrounded number or quotation in any run"
                if not ungrounded
                else f"{len(ungrounded)} violation(s): " + "; ".join(ungrounded[:3])
            ),
        )
    )

    report.conditions.append(
        Condition(
            key="attribution",
            title="(b) retrieval attribution",
            passed=not orphan_items,
            detail=(
                f"{attributed} delivered item(s), each pointing at a resolvable passage"
                if not orphan_items
                else f"{len(orphan_items)} unattributed: " + "; ".join(orphan_items[:3])
            ),
        )
    )

    organic_met = suppressions_or_reframes > 0 and report.nights_accumulated >= TARGET_NIGHTS
    report.conditions.append(
        Condition(
            key="organic_dedup",
            title="(c) organic dedup evidence",
            passed=organic_met,
            detail=(
                f"{suppressions_or_reframes} suppression(s)/reframe(s) over "
                f"{report.nights_accumulated} of {TARGET_NIGHTS} night(s)"
            ),
        )
    )
    if not organic_met:
        report.caveats.append(
            f"(c) needs {TARGET_NIGHTS} consecutive nights and at least one suppression "
            f"or reframe; {report.nights_accumulated} night(s) so far. It cannot be met "
            "by a single run, and it is what retires DIVERGENCES row 4."
        )
    report.caveats.append(
        "(c) cannot be verified as ORGANIC from traces alone — a trace records what a run "
        "did, not where the ledger's rows came from. If the ledger was ever hand-seeded, "
        "this condition is not yet evidence, whatever the count above says."
    )

    report.conditions.append(
        Condition(
            key="no_silent_loss",
            title="(d) no silent loss",
            passed=not unaccounted,
            applicable=dedup_ran_anywhere,
            detail=(
                "every produced item ended in a recorded outcome"
                if dedup_ran_anywhere and not unaccounted
                else "; ".join(unaccounted[:3])
                if unaccounted
                else "retrieval was off in every run examined, so nothing was assessed"
            ),
        )
    )

    return report


def trace_files(directory: str | Path) -> list[Path]:
    path = Path(directory)
    return sorted(path.glob("*.jsonl")) if path.exists() else []


__all__ = [
    "NEWS_BEAT",
    "TARGET_NIGHTS",
    "Condition",
    "NewsMetricReport",
    "check_news_metric",
    "trace_files",
]

"""The WSB beat's metric, computed from run traces (FR-52).

PRD §2 names three conditions. The one this beat adds to the project is **(c) politeness
held** — it is the first beat whose *source* enforces a budget (a second request 12 s
after the first drew a 429 when measured), so the metric proves we honored it: at most
one Reddit-host fetch per run, ever, including runs that got refused. A retry can never
creep in as a "fix" without failing here.

(a) is the two-hop count provenance chain: hop one is the existing FR-11 verdict over
the delivered checkable counts; hop two audits the count observation itself — every
ticker's count equals its distinct contributing urls, and every contributing url
resolves into the same run's fetch observation. Zero orphans, zero counts from anywhere
but tonight's fetch.

Same posture as the sibling checkers: report-only, trace-only, and n/a is not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse

from forecaster.news_metric import Condition
from forecaster.trace import read_trace, records_of

WSB_BEAT = "wsb"
COUNT_ADAPTER = "wsb.count_mentions"
FETCH_ADAPTER = "feeds.fetch_feed"


@dataclass
class WsbMetricReport:
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
        lines = [f"wsb metric over {self.runs_examined} run(s):"]
        for condition in self.conditions:
            lines.append(f"  [{condition.status:>4}] {condition.title} — {condition.detail}")
        lines.extend(f"  note: {caveat}" for caveat in self.caveats)
        return "\n".join(lines)


def _is_reddit_host(url: str) -> bool:
    host = (urlparse(str(url)).hostname or "").lower()
    return host == "reddit.com" or host.endswith(".reddit.com")


def _wsb_results(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records_of(records, "beat_result")
        if record.get("beat") == WSB_BEAT
    ]


def _observations_by_id(records: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {
        str(record.get("observation_id")): record
        for record in records_of(records, "observation")
    }


def _wsb_tool_calls(
    records: Sequence[Mapping[str, Any]], adapter: str
) -> list[Mapping[str, Any]]:
    return [
        record
        for record in records_of(records, "tool_call")
        if record.get("beat") == WSB_BEAT and record.get("adapter") == adapter
    ]


def check_wsb_metric(trace_paths: Iterable[str | Path]) -> WsbMetricReport:
    """Compute PRD §2's three conditions over one or more traces."""
    report = WsbMetricReport()

    provenance_failures: list[str] = []
    state_failures: list[str] = []
    politeness_failures: list[str] = []

    for path in (Path(item) for item in trace_paths):
        try:
            records = read_trace(path)
        except Exception as exc:  # noqa: BLE001 - one bad file must not hide the rest
            report.caveats.append(f"{path.name} could not be read ({exc})")
            continue

        results = _wsb_results(records)
        if not results:
            continue
        report.runs_examined += 1

        observations = _observations_by_id(records)

        # (a) hop one — the final provenance verdict of a delivered run, scoped to this
        # beat. The FIRST verdict can be superseded by an FR-30 recheck.
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
                    if WSB_BEAT in str(violation):
                        provenance_failures.append(f"{path.name}: {violation}")

        # (a) hop two — inside the count observation: every ticker's count equals its
        # distinct contributing urls, and every url resolves into the fetch observation.
        fetch_urls: set[str] = set()
        for call in _wsb_tool_calls(records, FETCH_ADAPTER):
            payload = (observations.get(str(call.get("observation_id"))) or {}).get(
                "payload"
            ) or {}
            for entry in payload.get("entries") or []:
                fetch_urls.add(str(entry.get("url")))
        for call in _wsb_tool_calls(records, COUNT_ADAPTER):
            payload = (observations.get(str(call.get("observation_id"))) or {}).get(
                "payload"
            ) or {}
            for ticker, record in (payload.get("tickers") or {}).items():
                urls = [str(url) for url in record.get("post_urls") or []]
                if record.get("count") != len(set(urls)):
                    provenance_failures.append(
                        f"{path.name}: {ticker} counts {record.get('count')} but "
                        f"contributes {len(set(urls))} distinct url(s)"
                    )
                orphans = [url for url in urls if url not in fetch_urls]
                if orphans:
                    provenance_failures.append(
                        f"{path.name}: {ticker} cites url(s) absent from tonight's "
                        f"fetch observation ({orphans[0]}…)"
                    )

        # (b) — exactly one state per run: counts, an explicit no-mentions, or the
        # FR-18 unavailable shape. No third state, no silent night.
        has_counts = any(
            record.get("decision") == "wsb_counts" and record.get("beat") == WSB_BEAT
            for record in records_of(records, "decision")
        )
        has_quiet = any(
            record.get("decision") == "wsb_no_mentions" and record.get("beat") == WSB_BEAT
            for record in records_of(records, "decision")
        )
        has_unavailable = any(not record.get("available", True) for record in results)
        states = sum((has_counts, has_quiet, has_unavailable))
        if states != 1:
            state_failures.append(
                f"{path.name}: {states} state(s) recorded "
                f"(counts={has_counts}, quiet={has_quiet}, unavailable={has_unavailable}) "
                "— the beat must record exactly one"
            )

        # (c) — politeness held: at most one Reddit-host fetch per run, ever.
        reddit_fetches = [
            record
            for record in records_of(records, "tool_call")
            if _is_reddit_host((record.get("arguments") or {}).get("url", ""))
        ]
        if len(reddit_fetches) > 1:
            politeness_failures.append(
                f"{path.name}: {len(reddit_fetches)} Reddit-host fetches in one run — "
                "the budget is one request per night, including refused ones"
            )

    applicable = report.runs_examined > 0
    na = "the beat appears in no examined run"

    report.conditions.append(
        Condition(
            key="count_provenance",
            title="(a) count provenance, both hops",
            passed=not provenance_failures,
            applicable=applicable,
            detail=(
                "every delivered count matches its observation, and every observation "
                "url resolves into tonight's fetch"
                if applicable and not provenance_failures
                else "; ".join(provenance_failures[:3]) if provenance_failures else na
            ),
        )
    )
    report.conditions.append(
        Condition(
            key="quiet_is_not_broken",
            title="(b) exactly one state per run",
            passed=not state_failures,
            applicable=applicable,
            detail=(
                "every run records counts, an explicit no-mentions, or a named outage"
                if applicable and not state_failures
                else "; ".join(state_failures[:3]) if state_failures else na
            ),
        )
    )
    report.conditions.append(
        Condition(
            key="politeness_held",
            title="(c) politeness held",
            passed=not politeness_failures,
            applicable=applicable,
            detail=(
                "at most one Reddit-host fetch per run, refused nights included"
                if applicable and not politeness_failures
                else "; ".join(politeness_failures[:3]) if politeness_failures else na
            ),
        )
    )
    report.caveats.append(
        "trace files cannot tell real nights from dev reruns — whether these runs are "
        "the scheduled kind is a judgment the checker does not make."
    )
    return report


__all__ = ["WSB_BEAT", "WsbMetricReport", "check_wsb_metric"]

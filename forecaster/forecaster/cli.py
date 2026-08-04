"""Runner entry point — wires the pipeline end to end.

Order, per PRD §4: planner → per-beat ReAct workers → synthesizer → delivery → ledger
write. Each beat gets a **fresh scratchpad** and runs behind Step 15's failure wrapper, so
one broken beat cannot take the run down or vanish from the digest.

`assert_subscription_auth()` runs before anything else: the run **refuses to start** if
`ANTHROPIC_API_KEY` is set.

Everything the pipeline talks to — the agent client, the deliverer, the HTTP client — is
injected. `main()` constructs the real ones; the integration tests pass fakes and make no
network call and no model call.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Sequence

import httpx

from forecaster.agent import (
    ClaudeAgentClient,
    FakeAgentClient,
    assert_subscription_auth,
    load_env,
)
from forecaster.beats.base import BeatContext, get_beats, load_builtin_beats, run_beat_safely
from forecaster.config import DEFAULT_CONFIG_PATH, Config, config_digest, load_config
from forecaster.delivery.base import FakeDeliverer
from forecaster.delivery.email import make_deliverer
from forecaster.memory.ledger import connect as connect_ledger, record_delivered_items
from forecaster.memory.preferences import (
    DEFAULT_PREFERENCES_PATH,
    Preferences,
    load_preferences,
)
from forecaster.memory.scratchpad import Scratchpad
from forecaster.planner import plan_run
from forecaster.synthesizer import Digest, ProvenanceError, synthesize
from forecaster.trace import Trace


def last_run_at(trace_dir: str | Path | None = None) -> datetime | None:
    """Timestamp of the newest trace's `run_start`, or None if there isn't one."""
    from forecaster.trace import DEFAULT_RUN_DIR, read_trace, records_of

    directory = Path(trace_dir) if trace_dir is not None else DEFAULT_RUN_DIR
    if not directory.exists():
        return None
    traces = sorted(directory.glob("*.jsonl"))
    for path in reversed(traces):
        try:
            for record in records_of(read_trace(path), "run_start"):
                stamp = record.get("at")
                if isinstance(stamp, str):
                    return datetime.fromisoformat(stamp)
        except Exception:  # noqa: BLE001 - a corrupt old trace must not block tonight
            continue
    return None


def missed_slots(
    since: datetime | None, now: datetime, send_time: Any, *, limit: int = 30
) -> list[datetime]:
    """Nightly slots between the last run and now that produced no run.

    PRD §8: a laptop asleep at 7 pm means no digest **and no error**. Counting those
    separately from failures is what keeps §2's delivery metric honest — the two have
    different fixes.
    """
    from datetime import timedelta

    if since is None:
        return []

    reference = since
    if reference.tzinfo is not None and now.tzinfo is None:
        reference = reference.replace(tzinfo=None)

    slots: list[datetime] = []
    day = reference.date()
    while len(slots) < limit:
        day = day + timedelta(days=1)
        slot = datetime.combine(day, send_time)
        if slot >= now:
            break
        slots.append(slot)
    return slots


@dataclass
class RunReport:
    """Everything a caller (or a test) needs to know about one run."""

    run_id: str
    trace_path: Path
    executed_beats: list[str] = field(default_factory=list)
    digest: Digest | None = None
    delivery: Any = None
    ledger_rows: int = 0
    missed_runs: int = 0
    error: str | None = None
    dedup_actions: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def text(self) -> str:
        return self.digest.text if self.digest is not None else ""


def run_pipeline(
    config: Config,
    preferences: Preferences,
    *,
    agent_client: Any,
    deliverer: Any,
    http_client: httpx.Client | None = None,
    now: datetime | None = None,
    trace_dir: str | Path | None = None,
    ledger_path: str | Path | None = None,
    beats: Sequence[Any] | None = None,
    auth_mode: str | None = None,
    write_ledger: bool = True,
    embedder: Any = None,
    corpus_path: str | Path | None = None,
) -> RunReport:
    """One complete run. Returns a report; raises only on a provenance failure.

    `embedder` is injected so the tests never download model weights — the pipeline is
    otherwise identical. When retrieval is enabled and no embedder is supplied, the real
    `StaticEmbedder` is constructed here.
    """
    started = time.monotonic()
    moment = now or datetime.now()
    owns_client = http_client is None
    client = http_client or httpx.Client(timeout=30.0)

    # One ledger connection for the run: FR-9b reads it before composing, and the write
    # path indexes into it afterwards. Opening it twice would mean two vector schemas.
    ledger_conn = None
    retriever = None
    corpus_conn = None
    if config.retrieval.enabled:
        try:
            from forecaster.memory.retrieval import LedgerRetriever, StaticEmbedder

            if embedder is None:
                embedder = StaticEmbedder(config.retrieval.model)
            ledger_conn = connect_ledger(ledger_path)
            retriever = LedgerRetriever(
                connection=ledger_conn,
                embedder=embedder,
                k=config.retrieval.k,
                similarity_floor=config.retrieval.similarity_floor,
                window_days=config.retrieval.window_days,
            )
        except Exception as exc:  # noqa: BLE001 - retrieval is never load-bearing
            retriever = None
            print(
                f"retrieval unavailable ({exc}); running without the ledger check",
                file=sys.stderr,
            )

    # FR-23. A **separate** file from the ledger, opened only when the news beat is on.
    # It shares the run's one embedder, so the model loads once.
    if config.news is not None and config.beats.get("news", False):
        try:
            from forecaster.memory import corpus as corpus_module
            from forecaster.memory.retrieval import StaticEmbedder

            if embedder is None:
                embedder = StaticEmbedder(config.retrieval.model)
            corpus_conn = corpus_module.connect(corpus_path or config.news.corpus.path)
        except Exception as exc:  # noqa: BLE001 - FR-18 turns this into an honest line
            corpus_conn = None
            print(f"news corpus unavailable ({exc})", file=sys.stderr)

    # Computed before the trace is opened, so tonight's own file isn't "the last run".
    skipped = missed_slots(last_run_at(trace_dir), moment, config.run.send_time)

    trace = Trace(directory=trace_dir)
    report = RunReport(run_id=trace.run_id, trace_path=trace.path)

    try:
        trace.run_start(
            auth_mode=auth_mode or getattr(agent_client, "auth_mode", "unknown"),
            config_digest=config_digest(config),
            config_path=str(config.source_path) if config.source_path else None,
            preferences_path=(
                str(preferences.source_path) if preferences.source_path else None
            ),
        )

        for slot in skipped:
            trace.missed_run(
                expected_at=slot.isoformat(),
                reason=(
                    "no run recorded for this nightly slot — counted as missed, not as a "
                    "delivery failure (PRD §8: a sleeping laptop produces neither)"
                ),
            )
        report.missed_runs = len(skipped)

        candidates = list(beats) if beats is not None else get_beats(config)
        by_name = {beat.name: beat for beat in candidates}

        plan = plan_run(
            config, preferences, moment, trace=trace, beats=candidates
        )

        results = []
        for entry in plan.entries:
            beat = by_name[entry.beat]
            context = BeatContext(
                config=config,
                preferences=preferences,
                now=moment,
                scratchpad=Scratchpad(trace=trace),  # a fresh one per beat
                trace=trace,
                http_client=client,
                embedder=embedder,
                corpus=corpus_conn,
                agent_client=agent_client,
            )
            result = run_beat_safely(beat, context)
            trace.beat_result(result)
            results.append(result)
            report.executed_beats.append(entry.beat)

        digest = synthesize(
            results,
            config,
            preferences,
            trace,
            agent_client=agent_client,
            retriever=retriever,
            now=moment,
        )
        report.digest = digest
        report.dedup_actions = [decision.action for _, decision in digest.dedup]

        delivery = deliverer.send(digest)
        report.delivery = delivery
        trace.delivery(
            deliverer=getattr(delivery, "deliverer", type(deliverer).__name__),
            target=getattr(delivery, "target", ""),
            success=bool(getattr(delivery, "success", False)),
            error=getattr(delivery, "error", None),
        )

        if write_ledger and getattr(delivery, "success", False):
            report.ledger_rows = record_delivered_items(
                digest,
                trace.run_id,
                path=ledger_path,
                connection=ledger_conn,
                embedder=embedder if retriever is not None else None,
            )

        usage = digest.usage
        trace.run_end(
            duration_ms=int((time.monotonic() - started) * 1000),
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            status="ok" if report.ok else "error",
            beats=report.executed_beats,
            ledger_rows=report.ledger_rows,
        )
    except ProvenanceError as exc:
        report.error = str(exc)
        trace.run_end(
            duration_ms=int((time.monotonic() - started) * 1000),
            status="provenance_failed",
            error=str(exc),
        )
        trace.close()
        if owns_client:
            client.close()
        raise
    finally:
        if not trace._closed:  # noqa: SLF001 - the trace owns its own handle
            trace.close()
        if owns_client:
            client.close()
        if ledger_conn is not None:
            ledger_conn.close()
        if corpus_conn is not None:
            corpus_conn.close()

    return report


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m forecaster.cli",
        description="Run the nightly Forecaster digest.",
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--preferences", default=str(DEFAULT_PREFERENCES_PATH))
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Use the fake deliverer (nothing is sent) but a real agent client and the "
            "live APIs. Still writes the trace."
        ),
    )
    parser.add_argument(
        "--send-test",
        action="store_true",
        help="Send one real digest to the configured address. Sarah runs this, not the agent.",
    )
    parser.add_argument(
        "--news-metric",
        action="store_true",
        help=(
            "Report PRD §2's four news-beat conditions over the traces in data/runs/ "
            "and exit. Reads only; runs nothing."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.news_metric:
        # Reporting only: no auth, no config, no run. Reads the traces and exits.
        from forecaster.news_metric import check_news_metric, trace_files
        from forecaster.trace import DEFAULT_RUN_DIR

        report = check_news_metric(trace_files(DEFAULT_RUN_DIR))
        print(report.summary())
        return 0

    load_env()
    try:
        auth_mode = assert_subscription_auth()
    except RuntimeError as exc:
        print(f"refusing to start: {exc}", file=sys.stderr)
        return 2

    config = load_config(args.config)
    preferences = load_preferences(args.preferences)
    load_builtin_beats()

    agent_client = ClaudeAgentClient()
    if args.dry_run and not args.send_test:
        deliverer: Any = FakeDeliverer(target=config.delivery.target)
    else:
        deliverer = make_deliverer(config)

    try:
        report = run_pipeline(
            config,
            preferences,
            agent_client=agent_client,
            deliverer=deliverer,
            auth_mode=auth_mode,
        )
    except ProvenanceError as exc:
        print(f"run failed the provenance check:\n{exc}", file=sys.stderr)
        return 3

    print(report.text)
    print(
        f"\n[run {report.run_id}] beats={report.executed_beats} "
        f"delivered={getattr(report.delivery, 'success', False)} "
        f"ledger_rows={report.ledger_rows}\ntrace: {report.trace_path}",
        file=sys.stderr,
    )
    return 0 if getattr(report.delivery, "success", False) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = [
    "RunReport",
    "build_parser",
    "last_run_at",
    "main",
    "missed_slots",
    "run_pipeline",
]

"""FR-19's disjoint-key clause, end to end — the 2026-08-31 suppression, reproduced.

Run 20260831T200550-b5e8543f: a same-night wsb rerun's line — new tickers, nothing in
common with its neighbour but the post total — was dedup-suppressed at cosine 0.8180.
The invariant compared values on shared keys only, and the ticker counts live in the
beat's declared `checkable_fields`, which never reached the comparison on either side.

This file drives the fixed path the way the live pipeline does: run A delivers and is
recorded to a real ledger (whose rows now carry the declared facts), run B retrieves
run A's line as a neighbour and must come out reframe-only. No network, no model:
`HashingEmbedder` for vectors, a scripted client for verdicts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from forecaster.agent import AgentResponse
from forecaster.beats.base import BeatItem, BeatResult, ObservationRef
from forecaster.memory.ledger import record_delivered_items, rows_for_run
from forecaster.synthesizer import synthesize
from tests.helpers import make_config, make_preferences, make_retriever, trace_in

CONFIG = make_config()

EARLIER_LINE = (
    "On r/wallstreetbets' hot page tonight (25 posts): EV mentioned in 2 posts, "
    "GPU in 2, AGI in 1, API in 1, CI in 1. https://www.reddit.test/r/wallstreetbets/"
)
EARLIER_TABLE = {"EV": 2, "GPU": 2, "AGI": 1, "API": 1, "CI": 1}
LATER_LINE = (
    "On r/wallstreetbets' hot page tonight (25 posts): FWRG mentioned in 1 post, "
    "HIMS in 1, VSXY in 1. https://www.reddit.test/r/wallstreetbets/"
)
LATER_TABLE = {"FWRG": 1, "HIMS": 1, "VSXY": 1}


class ScriptedClient:
    """Concatenates lines like `FakeAgentClient`, but answers dedup prompts with a
    fixed verdict. Never calls a model."""

    auth_mode = "subscription_oauth"

    def __init__(self, verdict: str = "SUPPRESS the reader was already told this") -> None:
        self.verdict = verdict
        self.dedup_calls = 0

    def complete(self, prompt: str, *, structured=None, system=None, effort="low"):
        if structured and "candidate" in structured:
            self.dedup_calls += 1
            return AgentResponse(text=self.verdict, input_tokens=0, output_tokens=0)
        lines = list((structured or {}).get("lines", [])) + list(
            (structured or {}).get("unavailable", [])
        )
        return AgentResponse(text="\n".join(lines), input_tokens=0, output_tokens=0)


def _wsb_result(trace, text: str, table: dict[str, int]) -> BeatResult:
    """A wsb-shaped BeatResult with the beat's real trace contract, so the counts
    survive the provenance check exactly as they do live."""
    count_id = trace.tool_call(
        beat="wsb",
        adapter="wsb.count_mentions",
        arguments={"posts": 25, "stoplist_size": 0},
    )
    trace.observation(
        count_id,
        payload={
            "tickers": {
                ticker: {"count": count, "post_urls": [f"https://p.test/{ticker}"]}
                for ticker, count in table.items()
            },
            "post_total": 25,
        },
    )
    ref = ObservationRef(count_id, "wsb.count_mentions")
    checkable: dict[str, Any] = {"wsb:post_total": 25}
    for ticker, count in table.items():
        checkable[f"wsb:{ticker}"] = count
    return BeatResult(
        beat="wsb",
        items=[
            BeatItem(
                beat="wsb",
                text=text,
                fields={"as_of": "2026-08-31", "post_total": 25},
                observations=[ref],
            )
        ],
        checkable_fields=checkable,
        observations=[ref],
    )


def _synthesize(trace, result: BeatResult, retriever):
    client = ScriptedClient()
    trace.beat_result(result)
    digest = synthesize(
        [result],
        CONFIG,
        make_preferences(topics={"astros": 1.0, "weather": 1.0, "wsb": 1.0}),
        trace,
        agent_client=client,
        retriever=retriever,
    )
    trace.close()
    return digest, client


def test_a_same_night_rerun_with_disjoint_tickers_is_reframed_not_suppressed(
    tmp_path: Path,
) -> None:
    """The measured failure, fixed: run A delivered, run B carries entirely new facts."""
    retriever = make_retriever(tmp_path, similarity_floor=0.20)

    trace_a = trace_in(tmp_path, "run-a")
    digest_a, _ = _synthesize(trace_a, _wsb_result(trace_a, EARLIER_LINE, EARLIER_TABLE), retriever)
    assert EARLIER_LINE in digest_a.text
    record_delivered_items(
        digest_a,
        "run-a",
        connection=retriever.connection,
        embedder=retriever.embedder,
    )

    # The delivered row records the declared facts, not just `fields` — without this the
    # disjoint-key clause reads every later night as "never told" forever.
    stored = rows_for_run("run-a", connection=retriever.connection)
    assert len(stored) == 1
    assert stored[0].fields["wsb:EV"] == 2
    assert stored[0].fields["as_of"] == "2026-08-31"

    trace_b = trace_in(tmp_path, "run-b")
    digest_b, client_b = _synthesize(
        trace_b, _wsb_result(trace_b, LATER_LINE, LATER_TABLE), retriever
    )

    assert LATER_LINE in digest_b.text, "entirely new facts must never be silenced"
    actions = [(beat, decision) for beat, decision in digest_b.dedup]
    assert len(actions) == 1
    beat, decision = actions[0]
    assert beat == "wsb"
    assert decision.action == "reframe"
    assert decision.forced is True
    assert "wsb:" in decision.reason
    assert client_b.dedup_calls == 0, "a rule must decide this, not the model"


def test_a_true_same_night_repeat_is_still_suppressible(tmp_path: Path) -> None:
    """The control: identical tickers and counts on a rerun still reach the model and
    stay suppressible — the clause must not turn the wsb beat unsuppressible forever."""
    retriever = make_retriever(tmp_path, similarity_floor=0.20)

    trace_a = trace_in(tmp_path, "run-a")
    digest_a, _ = _synthesize(trace_a, _wsb_result(trace_a, EARLIER_LINE, EARLIER_TABLE), retriever)
    record_delivered_items(
        digest_a,
        "run-a",
        connection=retriever.connection,
        embedder=retriever.embedder,
    )

    trace_b = trace_in(tmp_path, "run-b")
    digest_b, client_b = _synthesize(
        trace_b, _wsb_result(trace_b, EARLIER_LINE, EARLIER_TABLE), retriever
    )

    assert client_b.dedup_calls == 1, "identical facts are a judgment call, not a veto"
    assert [decision.action for _, decision in digest_b.dedup] == ["suppress"]
    assert EARLIER_LINE not in digest_b.text

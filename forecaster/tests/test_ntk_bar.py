"""Steps 46–47 — FR-36/FR-38: the bar. Watchlist carve-out first.

Synthetic routes rather than the real captures, because the whole point is controlling
which story matches which term. The scripted writer echoes a passage verbatim, so FR-26
passes by construction on honest output and the tests can prove it fails on tampering.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from forecaster.agent import AgentResponse
from forecaster.beats.base import BeatContext, load_builtin_beats, run_beat_safely
from forecaster.beats.need_to_know import NeedToKnowBeat
from forecaster.escalation import NEED_TO_KNOW_WATCHLIST, apply_escalation
from forecaster.memory import corpus as corpus_module
from forecaster.memory.dedup import assess_item
from forecaster.memory.retrieval import HashingEmbedder, Neighbour
from forecaster.trace import SYNTHESIZED, check_provenance, read_trace, records_of
from tests.conftest import Route, fixture_client
from tests.helpers import NEED_TO_KNOW_CONFIG, make_config, make_preferences, trace_in

load_builtin_beats()

NOW = datetime(2026, 8, 24, 19, 0, tzinfo=timezone.utc)
RECENT = "Mon, 24 Aug 2026 09:00:00 +0000"

BBC_FEED = r"feeds\.bbci\.test/"
TT_FEED = r"feeds\.texastribune\.test/"

SAFETY_BODY = (
    "<html><body><article>"
    + "<p>The city issued a boil notice for 120,000 residents after a water main "
    "break, officials said, and repairs are expected to take 3 days.</p>" * 8
    + "</article></body></html>"
)
CHESS_BODY = (
    "<html><body><article>"
    + "<p>A chess tournament opened with 42 grandmasters competing over nine rounds "
    "for the title, organizers said.</p>" * 8
    + "</article></body></html>"
)


def _feed_xml(*items: tuple[str, str]) -> str:
    entries = "".join(
        f"<item><title>{title}</title><link>{url}</link>"
        f"<pubDate>{RECENT}</pubDate><description>short summary text</description></item>"
        for title, url in items
    )
    return (
        '<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<title>Test</title>{entries}</channel></rss>"
    )


class ScriptedWriter:
    """Echoes the first passage, so every figure is grounded by construction."""

    auth_mode = "subscription_oauth"

    def __init__(self) -> None:
        self.write_calls = 0

    def complete(self, prompt, *, structured=None, system=None, effort="low"):
        self.write_calls += 1
        passages = (structured or {}).get("passages") or []
        source = passages[0]["source"] if passages else "a publication"
        body = passages[0]["text"] if passages else ""
        return AgentResponse(text=f"Per {source}: {body[:180]}")


class _no_model:
    auth_mode = "subscription_oauth"

    def complete(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("no model call was expected on this path")


def _routes(*, bbc_title: str, bbc_body: str = SAFETY_BODY):
    return [
        Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
        Route(
            BBC_FEED,
            text=_feed_xml((bbc_title, "https://bbc.test/story")),
            content_type="application/xml",
        ),
        Route(
            TT_FEED,
            text=_feed_xml(("Weekend chess roundup", "https://tt.test/chess")),
            content_type="application/xml",
        ),
        Route(r"bbc\.test/story", text=bbc_body, content_type="text/html"),
        Route(r"tt\.test/chess", text=CHESS_BODY, content_type="text/html"),
    ]


def _run(tmp_path: Path, *, bbc_title: str, bbc_body: str = SAFETY_BODY, client=None, mutate=None):
    http, _ = fixture_client(_routes(bbc_title=bbc_title, bbc_body=bbc_body))
    trace = trace_in(tmp_path, "ntk-bar")
    corpus = corpus_module.connect(tmp_path / "corpus.db")
    with http:
        context = BeatContext(
            config=make_config(
                beats={"need_to_know": True}, need_to_know=NEED_TO_KNOW_CONFIG
            ),
            preferences=make_preferences(),
            now=NOW,
            scratchpad=__import__(
                "forecaster.memory.scratchpad", fromlist=["Scratchpad"]
            ).Scratchpad(trace=trace),
            trace=trace,
            http_client=http,
            embedder=HashingEmbedder(),
            corpus=corpus,
            agent_client=client if client is not None else ScriptedWriter(),
        )
        result = run_beat_safely(NeedToKnowBeat(), context)
    if mutate is not None:
        mutate(result)
    trace.beat_result(result)
    trace.close()
    return result, trace


def _decisions(trace, kind: str):
    return [
        record
        for record in records_of(read_trace(trace.path), "decision")
        if record.get("decision") == kind
    ]


# --------------------------------------------------------------------------- #
# Step 46 — the watchlist carve-out
# --------------------------------------------------------------------------- #


def test_a_single_source_watchlist_story_delivers_and_escalates(tmp_path) -> None:
    """Only one source carries it (corroboration 0) — the carve-out delivers anyway."""
    client = ScriptedWriter()
    result, trace = _run(
        tmp_path, bbc_title="City issues boil notice after main break", client=client
    )

    assert result.available
    story = [item for item in result.items if item.fields.get("text_origin")]
    assert len(story) == 1
    assert story[0].fields == {"text_origin": SYNTHESIZED, "via": "watchlist"}
    assert story[0].observations, "the item must point at its chunks"
    assert client.write_calls == 1

    assert result.escalation_candidate is True
    assert "boil notice" in (result.escalation_reason or "")
    assert result.escalation_signals == {"watchlist": ["boil notice"]}
    (hit,) = _decisions(trace, "watchlist_hit")
    assert hit["term"] == "boil notice"

    ordered = apply_escalation([result], make_config(
        beats={"need_to_know": True}, need_to_know=NEED_TO_KNOW_CONFIG,
        escalation={"rules": ["need_to_know_watchlist", "freeze_alert", "watched_player_injury"]},
    ))
    promoted = [entry for entry in ordered.items if entry.promoted]
    assert promoted and promoted[0].rule == NEED_TO_KNOW_WATCHLIST
    assert ordered.items[0].item.text == story[0].text, "the hit leads the digest"


def test_without_the_term_nothing_delivers_and_no_model_is_called(tmp_path) -> None:
    result, trace = _run(
        tmp_path,
        bbc_title="City repairs water main quickly",
        bbc_body=CHESS_BODY,  # the body must not smuggle a term in either
        client=_no_model(),
    )
    assert result.available
    assert [item for item in result.items if item.fields.get("text_origin")] == []
    assert result.escalation_candidate is False
    assert _decisions(trace, "watchlist_hit") == []
    assert _decisions(trace, "corroboration_observed"), "observation still runs"


def test_matching_is_case_insensitive_and_whole_word(tmp_path) -> None:
    result, _ = _run(
        tmp_path, bbc_title="CITY ISSUES BOIL NOTICE DOWNTOWN", bbc_body=CHESS_BODY
    )
    assert result.escalation_candidate is True, "the headline alone must match, any case"

    result, _ = _run(
        tmp_path, bbc_title="Turboil noticeboard art installation", bbc_body=CHESS_BODY
    )
    assert result.escalation_candidate is False, "substrings must not match"


def test_the_delivered_item_passes_provenance_and_a_tampered_one_fails(tmp_path) -> None:
    result, trace = _run(tmp_path, bbc_title="City issues boil notice after main break")
    story = [item for item in result.items if item.fields.get("text_origin")][0]
    report = check_provenance(trace.path, story.text)
    assert report.violations == []

    # FR-26 polices the ITEM text against its linked chunks, so the tamper must land on
    # the item before it reaches the trace — a number the passages never stated.
    def _tamper(result_to_break) -> None:
        for item in result_to_break.items:
            if item.fields.get("text_origin"):
                item.text = item.text.replace("120,000", "250,000")

    result, trace = _run(
        tmp_path / "tampered",
        bbc_title="City issues boil notice after main break",
        mutate=_tamper,
    )
    story = [item for item in result.items if item.fields.get("text_origin")][0]
    assert "250,000" in story.text
    report = check_provenance(trace.path, story.text)
    assert any("ungrounded_number" in str(v.kind) for v in report.violations)


def test_dedup_can_never_suppress_a_watchlist_item(tmp_path) -> None:
    """FR-19 invariant 2, unmodified, is the guarantee — proven on the real item."""
    result, _ = _run(tmp_path, bbc_title="City issues boil notice after main break")
    story = [item for item in result.items if item.fields.get("text_origin")][0]

    neighbour = Neighbour(
        sent_item_id=1,
        beat="need_to_know",
        sent_at="2026-08-23T19:00:00",
        rendered_text=story.text,
        checkable_fields=dict(story.fields),
        similarity=1.0,
    )
    decision = assess_item(
        story,
        [neighbour],
        agent_client=_no_model(),  # would explode if the judgment were consulted
        beat="need_to_know",
        escalation_candidate=True,
    )
    assert decision.action == "include"
    assert decision.forced is True


# --------------------------------------------------------------------------- #
# Step 47 — the gated judgment
# --------------------------------------------------------------------------- #


class ScriptedJudgeAndWriter:
    """Answers the bar with a fixed verdict; writes by echoing a passage.

    Distinguishes the two calls by shape: the judgment carries `corroborated_by`,
    the writer carries `passages`.
    """

    auth_mode = "subscription_oauth"

    def __init__(self, verdict: str = "DELIVER local safety story") -> None:
        self.verdict = verdict
        self.judge_calls = 0
        self.write_calls = 0
        self.systems: list[str] = []

    def complete(self, prompt, *, structured=None, system=None, effort="low"):
        structured = structured or {}
        if "corroborated_by" in structured:
            self.judge_calls += 1
            self.systems.append(system or "")
            return AgentResponse(text=self.verdict)
        self.write_calls += 1
        passages = structured.get("passages") or []
        source = passages[0]["source"] if passages else "a publication"
        body = passages[0]["text"] if passages else ""
        return AgentResponse(text=f"Per {source}: {body[:180]}")


class RaisingJudge(ScriptedJudgeAndWriter):
    def complete(self, prompt, *, structured=None, system=None, effort="low"):
        if "corroborated_by" in (structured or {}):
            raise RuntimeError("judgment endpoint down")
        return super().complete(prompt, structured=structured, system=system, effort=effort)


#: Same story on both wires, so under min_sources = 1 the BBC copy passes the gate.
CORROBORATED_TITLE = "Grid operator warns of rolling outages this weekend"


def _gated_config(**bar_overrides):
    ntk = {
        **NEED_TO_KNOW_CONFIG,
        "corroboration": {**NEED_TO_KNOW_CONFIG["corroboration"], "min_sources": 1},
    }
    ntk.update(bar_overrides)
    return make_config(beats={"need_to_know": True}, need_to_know=ntk)


def _run_gated(tmp_path: Path, client, *, config=None):
    routes = [
        Route(r"/robots\.txt", text="User-agent: *\nDisallow:\n"),
        Route(
            BBC_FEED,
            text=_feed_xml((CORROBORATED_TITLE, "https://bbc.test/outages")),
            content_type="application/xml",
        ),
        Route(
            TT_FEED,
            text=_feed_xml(
                (CORROBORATED_TITLE, "https://tt.test/outages"),
                ("Weekend chess roundup", "https://tt.test/chess"),
            ),
            content_type="application/xml",
        ),
        Route(r"(bbc|tt)\.test/outages", text=SAFETY_BODY.replace("boil notice", "power warning"), content_type="text/html"),
        Route(r"tt\.test/chess", text=CHESS_BODY, content_type="text/html"),
    ]
    http, _ = fixture_client(routes)
    trace = trace_in(tmp_path, "ntk-judge")
    corpus = corpus_module.connect(tmp_path / "corpus.db")
    with http:
        context = BeatContext(
            config=config or _gated_config(),
            preferences=make_preferences(),
            now=NOW,
            scratchpad=__import__(
                "forecaster.memory.scratchpad", fromlist=["Scratchpad"]
            ).Scratchpad(trace=trace),
            trace=trace,
            http_client=http,
            embedder=HashingEmbedder(),
            corpus=corpus,
            agent_client=client,
        )
        result = run_beat_safely(NeedToKnowBeat(), context)
    trace.beat_result(result)
    trace.close()
    return result, trace


def test_a_deliver_verdict_delivers_a_grounded_item(tmp_path) -> None:
    client = ScriptedJudgeAndWriter("DELIVER grid trouble is local safety")
    result, trace = _run_gated(tmp_path, client)

    story = [item for item in result.items if item.fields.get("text_origin")]
    assert [item.fields["via"] for item in story] == ["bar", "bar"]
    assert client.judge_calls == 2, "both corroborated copies pass the gate"
    delivered = _decisions(trace, "ntk_delivered")
    assert len(delivered) == 2
    digest = "\n".join(item.text for item in story)
    assert check_provenance(trace.path, digest).violations == []


def test_the_chess_story_never_reaches_the_judge(tmp_path) -> None:
    """Sub-gate (count 0 < 1): the model must not even be asked."""
    client = ScriptedJudgeAndWriter()
    _run_gated(tmp_path, client)
    assert client.judge_calls == 2, "only the two corroborated copies, never chess"


def test_a_pass_verdict_suppresses_with_the_reason_on_record(tmp_path) -> None:
    client = ScriptedJudgeAndWriter("PASS wire drudgery")
    result, trace = _run_gated(tmp_path, client)

    assert [item for item in result.items if item.fields.get("text_origin")] == []
    suppressed = _decisions(trace, "ntk_suppressed")
    assert len(suppressed) == 2
    assert all("PASS" in record["reason"] for record in suppressed)
    assert client.write_calls == 0


def test_an_unrecognisable_verdict_is_uncertainty_and_suppresses(tmp_path) -> None:
    client = ScriptedJudgeAndWriter("hmm, tough one")
    result, trace = _run_gated(tmp_path, client)
    assert [item for item in result.items if item.fields.get("text_origin")] == []
    assert len(_decisions(trace, "ntk_suppressed")) == 2


def test_a_judgment_failure_is_a_named_abstention_never_include(tmp_path) -> None:
    result, trace = _run_gated(tmp_path, RaisingJudge())

    assert result.available, "abstention is not an outage"
    assert [item for item in result.items if item.fields.get("text_origin")] == []
    (abstention,) = _decisions(trace, "ntk_judgment_unavailable")
    assert abstention["unassessed"] == 2
    assert "never silent" in abstention["reason"]


def test_the_bar_lists_reach_the_prompt_from_config(tmp_path) -> None:
    client = ScriptedJudgeAndWriter("PASS")
    _run_gated(tmp_path, client)
    default_system = client.systems[0]
    assert "local safety" in default_system and "election outcomes" in default_system

    client = ScriptedJudgeAndWriter("PASS")
    _run_gated(
        tmp_path / "b",
        client,
        config=_gated_config(bar={"deliver": ["volcano news"], "exclude": ["sports"]}),
    )
    assert "volcano news" in client.systems[0] and "sports" in client.systems[0]
    assert client.systems[0] != default_system


def test_v4_observation_conditions_still_hold_under_the_bar(tmp_path) -> None:
    """The bar sits on top of observation, never instead of it."""
    from forecaster.ntk_metric import check_ntk_metric

    _, trace = _run_gated(tmp_path, ScriptedJudgeAndWriter("PASS"))
    report = check_ntk_metric([trace.path])
    assert report.condition("silence_accounted").passed
    assert report.condition("count_provenance").passed


def test_a_corroborated_watchlist_hit_skips_the_judge_entirely(tmp_path) -> None:
    """Carve-out precedence: matched term means delivered, no judgment consulted."""
    client = ScriptedJudgeAndWriter("PASS would have suppressed it")
    config = _gated_config(watchlist={"terms": ["rolling outages"]})
    result, trace = _run_gated(tmp_path, client, config=config)

    story = [item for item in result.items if item.fields.get("text_origin")]
    assert {item.fields["via"] for item in story} == {"watchlist"}
    assert client.judge_calls == 0
    assert result.escalation_candidate is True

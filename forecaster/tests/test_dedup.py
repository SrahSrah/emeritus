"""FR-9b, judgment half — the five safety invariants, one test each.

These are not tuning parameters. Each one is a rule that must hold whatever the embedding
scores and whatever the model says, which is why they are enforced *around* the model
rather than requested of it — the same reasoning as FR-11's provenance check.
"""

from __future__ import annotations

# FR-27's grounded-value veto lives at the bottom of this file.

from typing import Any, Mapping

import pytest

from forecaster.agent import AgentResponse, FakeAgentClient
from forecaster.beats.base import BeatItem
from forecaster.memory.dedup import DedupDecision, assess_item
from forecaster.memory.retrieval import Neighbour


class VerdictClient:
    """An agent double that returns a fixed verdict. Never calls a model."""

    auth_mode = "subscription_oauth"

    def __init__(self, verdict: str) -> None:
        self.verdict = verdict
        self.calls: list[Mapping[str, Any] | None] = []

    def complete(self, prompt: str, *, structured=None, system=None, effort="low"):
        self.calls.append(structured)
        return AgentResponse(text=self.verdict, input_tokens=0, output_tokens=0)


class ExplodingClient:
    auth_mode = "subscription_oauth"

    def complete(self, *args: Any, **kwargs: Any):
        raise RuntimeError("model unavailable")


def _neighbour(text: str, fields: dict[str, Any], similarity: float = 0.97) -> Neighbour:
    return Neighbour(
        sent_item_id=1,
        beat="astros",
        sent_at="2026-07-26T19:00:00",
        rendered_text=text,
        checkable_fields=fields,
        similarity=similarity,
    )


def _item(text: str, fields: dict[str, Any]) -> BeatItem:
    return BeatItem(beat="astros", text=text, fields=fields)


# --------------------------------------------------------------------------- #
# Invariant 1 — a differing checkable value can never be suppressed
# --------------------------------------------------------------------------- #


def test_a_changed_score_is_never_suppressed_however_similar_the_wording() -> None:
    """The load-bearing test. Cosine 0.9746 on the real model; the scores differ."""
    decision = assess_item(
        _item("Astros beat the Rangers 5-2.", {"score": "5-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"}, 0.9746)],
        agent_client=VerdictClient("SUPPRESS it adds nothing"),
        beat="astros",
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert "4-2" in decision.reason and "5-2" in decision.reason


def test_the_model_is_not_even_asked_when_a_checkable_value_moved() -> None:
    """An invariant that can be talked out of is not an invariant."""
    client = VerdictClient("SUPPRESS")
    assess_item(
        _item("Astros beat the Rangers 5-2.", {"score": "5-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=client,
        beat="astros",
    )
    assert client.calls == []


def test_a_value_that_only_changed_type_is_not_treated_as_news() -> None:
    """4 and 4.0 and "4" are the same observation. A type change is not information."""
    client = VerdictClient("SUPPRESS same game, nothing new")
    decision = assess_item(
        _item("Run-window low 41F.", {"run_window_low_f": 41}),
        [_neighbour("Run-window low 41F.", {"run_window_low_f": "41.0"})],
        agent_client=client,
        beat="astros",
    )
    assert decision.action == "suppress"


def test_a_newly_declared_field_is_always_included() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2; Alvarez left in the 3rd.", {"score": "4-2", "injury": "Alvarez"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=VerdictClient("SUPPRESS"),
        beat="astros",
    )
    assert decision.action == "include"
    assert decision.forced is True
    assert "injury" in decision.reason


# --------------------------------------------------------------------------- #
# Invariant 1, disjoint-key clause — measured 2026-08-31, run 20260831T200550-b5e8543f
#
# A same-night wsb rerun was suppressed at cosine 0.8180 against a line whose fact keys
# were entirely different tickers: the invariant compared values on shared keys only, so
# every shared key matched (post_total 25 = 25) and entirely new facts had no veto. The
# ticker counts live in the beat's declared checkable_fields, not BeatItem.fields, which
# is why `result_checkable` exists.
# --------------------------------------------------------------------------- #

WSB_EARLIER = (
    "On r/wallstreetbets' hot page tonight (25 posts): EV mentioned in 2 posts, "
    "GPU in 2, AGI in 1, API in 1, CI in 1."
)
WSB_LATER = (
    "On r/wallstreetbets' hot page tonight (25 posts): FWRG mentioned in 1 post, "
    "HIMS in 1, VSXY in 1."
)
WSB_LATER_CHECKABLE = {"wsb:post_total": 25, "wsb:FWRG": 1, "wsb:HIMS": 1, "wsb:VSXY": 1}


def _wsb_item(fields: dict[str, Any] | None = None) -> BeatItem:
    return BeatItem(
        beat="wsb",
        text=WSB_LATER,
        fields=fields or {"as_of": "2026-08-31", "post_total": 25},
    )


def _wsb_neighbour(fields: dict[str, Any], similarity: float = 0.8180) -> Neighbour:
    return Neighbour(
        sent_item_id=74,
        beat="wsb",
        sent_at="2026-08-31T19:27:42",
        rendered_text=WSB_EARLIER,
        checkable_fields=fields,
        similarity=similarity,
    )


def test_disjoint_fact_keys_are_never_suppressed_however_much_matches() -> None:
    """The measured case: same as_of, same post_total, disjoint tickers. Reframe-only."""
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _wsb_item(),
        [
            _wsb_neighbour(
                {
                    "as_of": "2026-08-31",
                    "post_total": 25,
                    "wsb:post_total": 25,
                    "wsb:EV": 2,
                    "wsb:GPU": 2,
                    "wsb:AGI": 1,
                    "wsb:API": 1,
                    "wsb:CI": 1,
                }
            )
        ],
        agent_client=client,
        beat="wsb",
        result_checkable=WSB_LATER_CHECKABLE,
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert "wsb:" in decision.reason
    assert client.calls == [], "a rule must decide this, not the model"


def test_the_clause_fires_against_a_row_stored_before_the_fix() -> None:
    """The shape actually stored on 2026-08-31: `fields` only, no fact keys at all."""
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _wsb_item(),
        [_wsb_neighbour({"as_of": "2026-08-31", "post_total": 25})],
        agent_client=client,
        beat="wsb",
        result_checkable=WSB_LATER_CHECKABLE,
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert client.calls == []


def test_identical_facts_are_still_suppressible_across_a_json_round_trip() -> None:
    """The control, plus the numeric gotcha: a genuine same-night repeat whose stored
    values came back string-typed must reach the model and stay suppressible — reading
    `25` vs `"25.0"` as news would disable suppression for every numeric field."""
    client = VerdictClient("SUPPRESS identical counts already delivered tonight")
    decision = assess_item(
        _wsb_item(),
        [
            _wsb_neighbour(
                {
                    "as_of": "2026-08-31",
                    "post_total": "25.0",
                    "wsb:post_total": "25.0",
                    "wsb:FWRG": "1.0",
                    "wsb:HIMS": "1.0",
                    "wsb:VSXY": "1.0",
                },
                similarity=1.0,
            )
        ],
        agent_client=client,
        beat="wsb",
        result_checkable=WSB_LATER_CHECKABLE,
    )

    assert decision.action == "suppress"
    assert len(client.calls) == 1


def test_a_differing_fact_value_vetoes_through_the_declared_surface() -> None:
    """The merged surface also feeds the differing-value clause: a count that moved is
    reframe-only even though `BeatItem.fields` never mentions the ticker."""
    client = VerdictClient("SUPPRESS")
    decision = assess_item(
        _wsb_item(),
        [
            _wsb_neighbour(
                {
                    "as_of": "2026-08-31",
                    "post_total": 25,
                    "wsb:post_total": 25,
                    "wsb:FWRG": 1,
                    "wsb:HIMS": 3,
                    "wsb:VSXY": 1,
                }
            )
        ],
        agent_client=client,
        beat="wsb",
        result_checkable=WSB_LATER_CHECKABLE,
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert "wsb:HIMS" in decision.reason
    assert client.calls == []


def test_one_legacy_neighbour_does_not_disable_suppression() -> None:
    """Absent from ALL neighbours, not just the nearest: once a fully-keyed row is also
    retrieved and every fact matches, a pre-fix row sitting closer must not veto."""
    client = VerdictClient("SUPPRESS identical counts already delivered tonight")
    keyed = dict(
        WSB_LATER_CHECKABLE, **{"as_of": "2026-08-31", "post_total": 25}
    )
    decision = assess_item(
        _wsb_item(),
        [
            _wsb_neighbour({"as_of": "2026-08-31", "post_total": 25}, similarity=0.99),
            _wsb_neighbour(keyed, similarity=0.98),
        ],
        agent_client=client,
        beat="wsb",
        result_checkable=WSB_LATER_CHECKABLE,
    )

    assert decision.action == "suppress"
    assert len(client.calls) == 1


# --------------------------------------------------------------------------- #
# Invariant 2 — an escalation candidate can never be suppressed
# --------------------------------------------------------------------------- #


def test_an_escalated_item_survives_even_a_perfect_duplicate() -> None:
    """A freeze alert is not less urgent for resembling last night's freeze alert."""
    decision = assess_item(
        _item("Freeze alert: 28F at 6 am.", {"run_window_low_f": "28"}),
        [_neighbour("Freeze alert: 28F at 6 am.", {"run_window_low_f": "28"}, 1.0)],
        agent_client=VerdictClient("SUPPRESS identical"),
        beat="weather",
        escalation_candidate=True,
    )
    assert decision.action == "include"
    assert decision.forced is True


# --------------------------------------------------------------------------- #
# Invariant 3 — cold start means "nothing known", not "nothing new"
# --------------------------------------------------------------------------- #


def test_an_empty_neighbour_set_includes_without_asking_the_model() -> None:
    client = VerdictClient("SUPPRESS")
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [],
        agent_client=client,
        beat="astros",
    )
    assert decision.action == "include"
    assert client.calls == []


# --------------------------------------------------------------------------- #
# Invariant 4 — a failure degrades to include, never to silence
# --------------------------------------------------------------------------- #


def test_a_model_failure_includes_the_item() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=ExplodingClient(),
        beat="astros",
    )
    assert decision.action == "include"
    assert "unavailable" in decision.reason


def test_an_unparseable_verdict_includes_the_item() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=VerdictClient("I'm not sure, could go either way"),
        beat="astros",
    )
    assert decision.action == "include"


def test_disabling_retrieval_includes_everything() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=VerdictClient("SUPPRESS"),
        beat="astros",
        enabled=False,
    )
    assert decision.action == "include"


# --------------------------------------------------------------------------- #
# Invariant 5 — every decision is auditable
# --------------------------------------------------------------------------- #


def test_a_suppression_names_the_item_it_duplicated_and_the_score() -> None:
    decision = assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"}, 0.99)],
        agent_client=VerdictClient("SUPPRESS you were told this last night"),
        beat="astros",
    )

    assert decision.action == "suppress"
    assert "#1" in decision.reason
    assert "0.99" in decision.reason
    record = decision.as_record()
    assert record["action"] == "suppress"
    assert record["neighbours"][0]["sent_item_id"] == 1


def test_the_model_only_ever_sees_text_already_delivered() -> None:
    """The dedup call must not become a second place a value can be invented."""
    client = VerdictClient("INCLUDE")
    assess_item(
        _item("Astros beat the Rangers 4-2.", {"score": "4-2"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2"})],
        agent_client=client,
        beat="astros",
    )
    payload = client.calls[0]
    assert set(payload) == {"candidate", "candidate_fields", "previously_sent"}
    assert payload["previously_sent"][0]["text"] == "Astros beat the Rangers 4-2."


# --------------------------------------------------------------------------- #
# The reframe path
# --------------------------------------------------------------------------- #


def test_a_reframe_verdict_carries_the_replacement_text() -> None:
    decision = assess_item(
        _item("The Astros are 4 games up in the West.", {"lead": "4"}),
        [_neighbour("The Astros are 4 games up in the West.", {"lead": "4"})],
        agent_client=VerdictClient(
            "REFRAME same standings story, the lead is what moved\n"
            "TEXT: Still 4 games up in the West — unchanged since last night."
        ),
        beat="astros",
    )

    assert decision.action == "reframe"
    assert decision.reframed_text == (
        "Still 4 games up in the West — unchanged since last night."
    )


def test_a_reframe_with_no_replacement_text_keeps_the_original() -> None:
    decision = assess_item(
        _item("The Astros are 4 games up.", {"lead": "4"}),
        [_neighbour("The Astros are 4 games up.", {"lead": "4"})],
        agent_client=VerdictClient("REFRAME but I forgot the text line"),
        beat="astros",
    )
    assert decision.action == "reframe"
    assert decision.reframed_text is None


# --------------------------------------------------------------------------- #
# FR-27 — invariant 1, transplanted from typed fields to grounded prose
# --------------------------------------------------------------------------- #
#
# The typed version assumes a recurring status item, where identical wording on a
# different day means a different fact. News inverts that: the same story on a different
# day IS the repeat. So for an item whose text the model wrote from retrieved passages,
# the veto reads the prose — a new number, quotation, or proper noun.

from forecaster.memory.dedup import SYNTHESIZED  # noqa: E402

SYNTH_FIELDS = {"topic": "claude", "text_origin": SYNTHESIZED}


def _news_item(text: str) -> BeatItem:
    return BeatItem(beat="news", text=text, fields=dict(SYNTH_FIELDS))


def _news_neighbour(text: str, similarity: float = 1.0) -> Neighbour:
    return Neighbour(
        sent_item_id=1,
        beat="news",
        sent_at="2026-08-03T19:00:00",
        rendered_text=text,
        checkable_fields=dict(SYNTH_FIELDS),
        similarity=similarity,
    )


def test_a_new_figure_survives_a_cosine_one_neighbour_without_asking_the_model() -> None:
    """FR-27's first clause. A benchmark number no neighbour stated is new information."""
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _news_item("Anthropic's newest Claude model scored 71.5 on the benchmark."),
        [_news_neighbour("Anthropic shipped a newest Claude model this week.")],
        agent_client=client,
        beat="news",
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert "71.5" in decision.reason
    assert client.calls == [], "a rule must decide this, not the model"


def test_a_new_entity_survives_the_same_way() -> None:
    """The clause without which the model alone decides whether a real story lands."""
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _news_item("Anthropic shipped the Claude Agent SDK this week."),
        [_news_neighbour("Anthropic shipped a model this week.")],
        agent_client=client,
        beat="news",
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert "SDK" in decision.reason or "Agent" in decision.reason
    assert client.calls == []


def test_a_new_quotation_survives_the_same_way() -> None:
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _news_item('Anthropic called it "a meaningful step for agentic work".'),
        [_news_neighbour("Anthropic commented on the release.")],
        agent_client=client,
        beat="news",
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert client.calls == []


def test_the_same_story_restated_reaches_the_model_and_is_suppressible() -> None:
    """The case the whole feature exists for: three days of the same AI story."""
    client = VerdictClient("SUPPRESS adds nothing new")
    text = "Anthropic shipped a faster Claude model, and it costs more."
    decision = assess_item(
        _news_item(text),
        [_news_neighbour(text)],
        agent_client=client,
        beat="news",
    )

    assert decision.action == "suppress"
    assert len(client.calls) == 1


def test_the_same_story_reworded_is_still_suppressible() -> None:
    """Different sentence, same figures and entities. Publishers do this constantly."""
    client = VerdictClient("SUPPRESS same story")
    decision = assess_item(
        _news_item("Claude got faster this week, though Anthropic raised the price."),
        [_news_neighbour("Anthropic shipped a faster Claude model, and it costs more.")],
        agent_client=client,
        beat="news",
    )

    assert decision.action == "suppress"
    assert len(client.calls) == 1


def test_a_sentence_initial_capital_is_not_treated_as_a_new_entity() -> None:
    """Otherwise the veto fires on everything, which is the opposite failure."""
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _news_item("Today Anthropic shipped a faster Claude model."),
        [_news_neighbour("Anthropic shipped a faster Claude model.")],
        agent_client=client,
        beat="news",
    )

    assert decision.action == "suppress"
    assert len(client.calls) == 1, "'Today' must not count as a new name"


def test_an_entity_named_in_a_different_case_still_counts_as_known() -> None:
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _news_item("Reports say Anthropic shipped a model."),
        [_news_neighbour("reports say anthropic shipped a model.")],
        agent_client=client,
        beat="news",
    )

    assert decision.action == "suppress"


def test_escalation_still_outranks_the_grounded_veto() -> None:
    """Invariant 2 is checked before FR-27 and stays unconditional."""
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _news_item("Anthropic shipped a faster Claude model."),
        [_news_neighbour("Anthropic shipped a faster Claude model.")],
        agent_client=client,
        beat="news",
        escalation_candidate=True,
    )

    assert decision.action == "include"
    assert decision.forced is True
    assert client.calls == []


def test_a_cold_ledger_still_means_nothing_known_for_a_news_item() -> None:
    """Invariant 3, unchanged: an empty neighbour set is not 'nothing new'."""
    decision = assess_item(
        _news_item("Anthropic shipped a faster Claude model."),
        [],
        agent_client=VerdictClient("SUPPRESS"),
        beat="news",
    )
    assert decision.action == "include"


def test_a_broken_judgment_still_degrades_to_include_for_a_news_item() -> None:
    """Invariant 4, unchanged, reached through the new branch."""
    decision = assess_item(
        _news_item("Anthropic shipped a faster Claude model."),
        [_news_neighbour("Anthropic shipped a faster Claude model.")],
        agent_client=ExplodingClient(),
        beat="news",
    )
    assert decision.action == "include"
    assert "unavailable" in decision.reason


def test_the_typed_invariant_is_untouched_for_unflagged_items() -> None:
    """The two shipped beats must not notice FR-27 exists."""
    client = VerdictClient("SUPPRESS adds nothing")
    decision = assess_item(
        _item("Astros beat the Rangers 5-2.", {"score": "5-2", "game_date": "2026-08-04"}),
        [_neighbour("Astros beat the Rangers 4-2.", {"score": "4-2", "game_date": "2026-08-03"})],
        agent_client=client,
        beat="astros",
    )

    assert decision.action == "reframe"
    assert decision.forced is True
    assert "score changed" in decision.reason
    assert client.calls == []

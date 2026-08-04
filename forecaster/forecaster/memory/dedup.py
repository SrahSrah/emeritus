"""FR-9b — "have I already been told this?", as a judgment over retrieved neighbours.

`retrieval.py` finds candidates. This module decides. The split is the whole design:
similarity is good at *finding* the handful of prior items worth looking at and bad at
*deciding* whether tonight's line adds anything, so it is only ever used for the first job.

## The failure mode this is built around

Static embeddings are close to blind to numerals. Measured on the shipped model
(`potion-retrieval-32M`, 2026-08-02):

    "Final: Houston Astros 4, Texas Rangers 2."
        vs "Final: Houston Astros 5, Texas Rangers 2."                   cosine 0.9859
    "Astros beat the Rangers 4-2." vs "Astros beat the Rangers 5-2."     cosine 0.9746
    "Astros beat the Rangers 4-2." vs a weather line                     cosine 0.0037

Those near-duplicates are *different games on different nights*. A threshold-only dedup would
read 0.97 as "same story" and silently drop tonight's real result. For an agent whose only
promise is that its facts are real, going quiet is a worse failure than repeating itself,
and it is much harder to notice.

So the safety rules below are not tuning parameters. They are invariants, each with a test:

1. **A differing checkable value can never be suppressed.** If the candidate declares a
   checkable field whose value differs from the nearest neighbour's recorded value, the
   most retrieval may do is *reframe*. This is what makes the 0.97 collision harmless:
   the scores differ, so the item survives regardless of what the embedding thinks.
2. **An escalation candidate can never be suppressed.** A freeze alert is not less urgent
   for resembling last night's.
3. **An unavailability line can never be suppressed.** FR-18's honesty guarantee outranks
   tidiness.
4. **Retrieval failure degrades to `include`.** A broken index must never silence the
   digest.
5. **Every decision is auditable** — the neighbours, their scores, the action, and the
   model's stated reason all go into the run trace.

Rule 1 is the load-bearing one, and it is why the ledger stores `checkable_fields`
alongside the rendered text: without the neighbour's *observed values* there is no way to
tell a genuine repeat from a near-identical sentence about a different fact.

## Rule 1 does not generalize to a document-shaped beat (FR-27)

Rule 1 assumes a **recurring status item**, where identical wording on a different day
means a genuinely different fact. A score and a forecast are new every night, so the date
in `fields` is what keeps them alive.

News inverts that. The same story on a different day **is** the repeat, and is exactly
what should be suppressed. Any per-artifact field in a news item's `fields` therefore
disables dedup for that beat, permanently and invisibly:

- a run date differs every night, so rule 1 fires on every item and nothing is suppressed;
- `published` differs whenever tonight's top article is newer than last night's, the
  normal case;
- `url` differs whenever a second publisher picks up the story — which is precisely the
  "three days of *Fable rocks but is expensive*" case the news beat exists to fix.

So for an item declaring `text_origin="synthesized"`, rule 1 is **transplanted from typed
fields to grounded prose**: the veto fires when the candidate introduces a **number**, a
**quoted phrase**, or a **proper noun** that appears in none of its neighbours. Those are
the things that mean the reader is learning something. A genuine repeat of the same story
reuses its figures and its entities, so it stays suppressible, which is what keeps the
feature's own success metric satisfiable.

If the veto over-fires the digest repeats itself, which the trace records and which is the
**correct-side error**: going quiet is worse than repeating, and much harder to notice.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from forecaster.agent import AgentClientLike, DEFAULT_EFFORT
from forecaster.memory.retrieval import Neighbour, RetrievalError
from forecaster.trace import SYNTHESIZED

Action = Literal["include", "reframe", "suppress"]

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_QUOTED = re.compile(r'"([^"]{4,})"')
#: A capitalized token of three or more characters. Sentence-initial ones are excluded
#: separately — "Anthropic" mid-sentence is a name; "Today" opening one is not.
_CAPITALIZED = re.compile(r"\b([A-Z][A-Za-z0-9][A-Za-z0-9.&+-]{1,})\b")

SYSTEM_PROMPT = (
    "You decide whether a new digest line tells the reader anything they do not already "
    "know, given lines they were sent on previous nights. "
    "Answer with one of: INCLUDE (new information), REFRAME (same subject, but something "
    "changed and the line should lead with what changed), SUPPRESS (adds nothing). "
    "You may never invent, alter, or drop a number, score, or state. "
    "When uncertain, choose INCLUDE — repeating something is a smaller error than "
    "withholding it."
)


@dataclass
class DedupDecision:
    """What retrieval concluded about one candidate item, and why."""

    action: Action
    reason: str
    neighbours: list[Neighbour] = field(default_factory=list)
    reframed_text: str | None = None
    forced: bool = False  # a safety invariant overrode the judgment

    @property
    def top_similarity(self) -> float:
        return self.neighbours[0].similarity if self.neighbours else 0.0

    def as_record(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "forced": self.forced,
            "top_similarity": round(self.top_similarity, 4),
            "neighbours": [n.as_record() for n in self.neighbours],
        }


def _same_value(left: Any, right: Any) -> bool:
    """Is this the same observation, allowing for how it happened to be serialised?

    `4`, `4.0` and `"4"` are one score. The ledger round-trips through JSON and a beat may
    hand over an int where yesterday's row holds a string, so a naive string compare would
    read a type change as news — and "news" here means an item can never be suppressed,
    which would quietly disable dedup for every numeric field.
    """
    if left == right:
        return True
    try:
        return float(left) == float(right)
    except (TypeError, ValueError):
        return str(left) == str(right)


def _checkable_values_differ(item: Any, neighbour: Neighbour) -> tuple[bool, str | None]:
    """Does the candidate state a checked value the neighbour recorded differently?"""
    candidate = getattr(item, "fields", None) or {}
    prior = neighbour.checkable_fields or {}
    for key, value in candidate.items():
        if key not in prior:
            continue
        if not _same_value(prior[key], value):
            return True, f"{key} changed from {prior[key]!r} to {value!r}"
    return False, None


def _new_checkable_key(item: Any, neighbour: Neighbour) -> str | None:
    """A field tonight's item declares that the neighbour never carried."""
    candidate = getattr(item, "fields", None) or {}
    prior = neighbour.checkable_fields or {}
    for key in candidate:
        if key not in prior:
            return key
    return None


def _proper_nouns(text: str) -> list[str]:
    """Capitalized tokens that are not sentence-initial.

    Sentence-initial words are excluded because every sentence starts with a capital and
    treating "Today" as a new entity would make the veto fire on everything — which is
    the failure mode opposite to the one it exists to prevent.
    """
    found: list[str] = []
    for match in _CAPITALIZED.finditer(text):
        preceding = text[: match.start()].rstrip()
        if not preceding or preceding[-1] in ".!?":
            continue
        found.append(match.group(1))
    return found


def _mentions(blob: str, token: str) -> bool:
    return re.search(rf"\b{re.escape(token)}\b", blob, re.IGNORECASE) is not None


def _new_grounded_values(item: Any, neighbours: Sequence[Neighbour]) -> list[str]:
    """What this item says that no neighbour said. FR-27's veto reads this.

    Returns human-readable descriptions rather than a bool, because the reason goes into
    the trace and "a figure changed" is not an auditable explanation.
    """
    text = str(getattr(item, "text", "") or "")
    blob = "\n".join(neighbour.rendered_text for neighbour in neighbours)
    lowered = blob.lower()
    new: list[str] = []

    for number in dict.fromkeys(_NUMBER.findall(text)):
        if number not in blob:
            new.append(f"the figure {number}")

    for quoted in dict.fromkeys(_QUOTED.findall(text)):
        if quoted.lower() not in lowered:
            new.append(f"the quotation {quoted!r}")

    for noun in dict.fromkeys(_proper_nouns(text)):
        if not _mentions(blob, noun):
            new.append(f"the name {noun!r}")

    return new


def assess_item(
    item: Any,
    neighbours: Sequence[Neighbour],
    *,
    agent_client: AgentClientLike,
    beat: str = "",
    escalation_candidate: bool = False,
    effort: str = DEFAULT_EFFORT,
    enabled: bool = True,
) -> DedupDecision:
    """Decide whether to include, reframe, or suppress one candidate line.

    Safety invariants are applied **around** the model, not requested of it — an
    instruction in a prompt is not a guarantee, the same reasoning as FR-11's provenance
    check.
    """
    neighbours = list(neighbours)

    if not enabled:
        return DedupDecision("include", "retrieval disabled in config", neighbours)

    # Cold start. An empty ledger means nothing is known, not that nothing is new.
    if not neighbours:
        return DedupDecision(
            "include", "no prior item within the retrieval window", neighbours
        )

    # Invariant 2 — an escalated item is never suppressed by retrieval.
    if escalation_candidate:
        return DedupDecision(
            "include",
            "escalation candidate; retrieval may not suppress an escalated item",
            neighbours,
            forced=True,
        )

    nearest = neighbours[0]

    # Invariant 1, transplanted (FR-27). For an item whose text the model wrote from
    # retrieved passages, the veto reads the prose rather than typed fields — see this
    # module's docstring for why the typed-field version inverts for a news beat.
    if (getattr(item, "fields", None) or {}).get("text_origin") == SYNTHESIZED:
        introduced = _new_grounded_values(item, neighbours)
        if introduced:
            joined = ", ".join(introduced[:3])
            more = "" if len(introduced) <= 3 else f" (and {len(introduced) - 3} more)"
            return DedupDecision(
                "reframe",
                (
                    f"near-duplicate wording (cosine {nearest.similarity:.4f}) but the "
                    f"candidate introduces {joined}{more}, which no retrieved neighbour "
                    "carried; suppression is not permitted"
                ),
                neighbours,
                forced=True,
            )
        # Nothing new was introduced. Now it is a genuine judgment call, so ask — the
        # typed-field invariants below are meaningless here (a news item declares only
        # its topic and its origin) and would just wave everything through.
        return _ask_model(
            item, neighbours, nearest, agent_client=agent_client, effort=effort
        )

    # Invariant 1 — the one that makes the 0.97 numeral collision harmless.
    differs, detail = _checkable_values_differ(item, nearest)
    if differs:
        return DedupDecision(
            "reframe",
            (
                f"near-duplicate wording (cosine {nearest.similarity:.4f}) but a checkable "
                f"value differs — {detail}; suppression is not permitted"
            ),
            neighbours,
            forced=True,
        )

    new_key = _new_checkable_key(item, nearest)
    if new_key is not None:
        return DedupDecision(
            "include",
            f"declares {new_key!r}, which no retrieved neighbour carried",
            neighbours,
            forced=True,
        )

    # No checkable value moved. Now it is a genuine judgment call, so ask.
    return _ask_model(item, neighbours, nearest, agent_client=agent_client, effort=effort)


def _ask_model(
    item: Any,
    neighbours: Sequence[Neighbour],
    nearest: Neighbour,
    *,
    agent_client: AgentClientLike,
    effort: str = DEFAULT_EFFORT,
) -> DedupDecision:
    """The judgment step, reached only once every mechanical veto has declined to fire."""
    structured = {
        "candidate": getattr(item, "text", str(item)),
        "candidate_fields": dict(getattr(item, "fields", None) or {}),
        "previously_sent": [
            {"sent_at": n.sent_at, "text": n.rendered_text, "similarity": round(n.similarity, 4)}
            for n in neighbours
        ],
    }
    try:
        response = agent_client.complete(
            "Does the candidate line tell the reader anything the previously sent lines "
            "did not? Answer INCLUDE, REFRAME, or SUPPRESS, then give a one-sentence "
            "reason. If REFRAME, follow with a line beginning 'TEXT:' that leads with "
            "what changed, reusing the candidate's numbers exactly.",
            structured=structured,
            system=SYSTEM_PROMPT,
            effort=effort,
        )
    except Exception as exc:  # noqa: BLE001 - invariant 4
        return DedupDecision(
            "include", f"dedup judgment unavailable ({exc}); defaulting to include", list(neighbours)
        )

    return _parse_judgment(response.text, list(neighbours), nearest)


def _parse_judgment(
    text: str, neighbours: list[Neighbour], nearest: Neighbour
) -> DedupDecision:
    """Read the model's verdict. Anything unrecognised means include."""
    raw = (text or "").strip()
    upper = raw.upper()
    reframed: str | None = None

    for line in raw.splitlines():
        if line.strip().upper().startswith("TEXT:"):
            reframed = line.split(":", 1)[1].strip()
            break

    if upper.startswith("SUPPRESS"):
        return DedupDecision(
            "suppress",
            f"judged to add nothing over item #{nearest.sent_item_id} "
            f"(cosine {nearest.similarity:.4f}): {raw.splitlines()[0][:200]}",
            neighbours,
        )
    if upper.startswith("REFRAME"):
        return DedupDecision(
            "reframe",
            f"same subject as item #{nearest.sent_item_id} "
            f"(cosine {nearest.similarity:.4f}); leading with what changed",
            neighbours,
            reframed_text=reframed,
        )
    return DedupDecision(
        "include",
        f"judged to add new information over {len(neighbours)} retrieved neighbour(s)",
        neighbours,
    )


__all__ = [
    "SYNTHESIZED",
    "SYSTEM_PROMPT",
    "Action",
    "DedupDecision",
    "assess_item",
]

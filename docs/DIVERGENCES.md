# DIVERGENCES — submitted vs. built

Every place the **submitted checkpoint text** and the **shipped code** disagree, with how it was
resolved and when.

Why this file exists: checkpoints are design documents written before the code, so drift is normal and
often correct. What's not acceptable is drift nobody recorded — a grader reading checkpoints 1 through
N in order shouldn't hit an unexplained moving target, and next week's essay shouldn't claim a
capability that shipped disabled.

**Read by** `write-next-assignment` (so the draft can acknowledge a revision in a sentence).
**Written by** `continue-build` (at its conflict gate, and again after the build reveals reality).

| # | Submitted | Shipped | Resolution | Date |
|---|---|---|---|---|
| 1 | Checkpoints 1.1 and 2.x both state the report arrives as **a text message** at 7 pm CT. | **Email.** | Deliberate scope cut. Real SMS needs Twilio, a number, and A2P 10DLC registration — paperwork plus a multi-day approval that would have blocked the build. Email also makes the reply-based feedback loop (FR-16) work natively instead of needing a webhook. **Owes one sentence of acknowledgement in the next checkpoint.** Tracked as PRD §9 Q1. | 2026-07-27 |
| 2 | Checkpoint 2.x describes escalation firing on "any injury update on only my favorite players." | Rule is implemented and unit-tested, but **dormant** — it can never fire. | No v1 endpoint returns injury data. `statsapi.mlb.com` gives schedule, game state, score, and game ID. The rule reads a generic `escalation_signals["injuries"]` key that nothing populates. **Do not claim injury escalation works.** Adding a feed is new scope. | 2026-07-27 |
| 3 | Checkpoint 2.x: "the synthesizer… checks them against what I've already been told" — i.e. dedup against the ledger. | Ledger is **write-only**; the synthesizer does not read it. | Dedup (FR-9b) is blocked on PRD §9 Q3 — what makes two items "the same story". Deferred rather than guessed, and enforced by tests that assert no identity column, no similarity check, and no read path. The repetition failure mode it solves doesn't occur in the v1 beat set anyway (a score and a forecast are new every night); it lands with the AI-news beat. | 2026-07-27 |

## How to add a row

At `continue-build`'s conflict gate, and again after the build discovers reality. Record what was
*submitted* verbatim enough to be findable, what actually *shipped*, and **why** — the reasoning is the
part that's useful in a later essay. Date it.

If a divergence gets closed (the code catches up, or a later checkpoint revises the promise), leave the
row and note the closure rather than deleting it. The history is the point.

# DIVERGENCES — submitted vs. built

Every place the **submitted checkpoint text** and the **shipped code** disagree, with how it was
resolved and when.

Why this file exists: checkpoints are design documents written before the code, so drift is normal and
often correct. What's not acceptable is drift nobody recorded — a grader reading checkpoints 1 through
N in order shouldn't hit an unexplained moving target, and next week's essay shouldn't claim a
capability that shipped disabled.

**Read by** `write-next-assignment` (so the draft can acknowledge a revision in a sentence).
**Written by** `continue-capstone-build` (at its conflict gate, and again after the build reveals reality).

| # | Submitted | Shipped | Resolution | Date |
|---|---|---|---|---|
| 1 | Checkpoints 1.1 and 2.x both state the report arrives as **a text message** at 7 pm CT. | **Email.** | Deliberate scope cut. Real SMS needs Twilio, a number, and A2P 10DLC registration — paperwork plus a multi-day approval that would have blocked the build. Email also makes the reply-based feedback loop (FR-16) work natively instead of needing a webhook. **CLOSED 2026-08-02** — Checkpoint 3 acknowledges the revision in a sentence, so the promise and the build now agree. PRD §9 Q1 resolved. | 2026-07-27 → closed 2026-08-02 |
| 2 | Checkpoint 2.x describes escalation firing on "any injury update on only my favorite players." | Rule is implemented and unit-tested, but **dormant** — it can never fire. | No v1 endpoint returns injury data. `statsapi.mlb.com` gives schedule, game state, score, and game ID. The rule reads a generic `escalation_signals["injuries"]` key that nothing populates. **Do not claim injury escalation works.** Adding a feed is new scope. | 2026-07-27 |
| 3 | Checkpoint 2.x: "the synthesizer… checks them against what I've already been told" — i.e. dedup against the ledger. | Ledger was **write-only**; the synthesizer did not read it. | Dedup (FR-9b) was blocked on PRD §9 Q3 — what makes two items "the same story". Deferred rather than guessed. **CLOSED 2026-08-02**: Q3 answered (identity is a read-time relation, not a stored property), FR-9b built and shipped as the Module 3 increment. The code now does what Checkpoint 2 said it would. The guardrail tests were revised rather than deleted — no identity may still ever be written down. | 2026-07-27 → closed 2026-08-02 |
| 4 | Checkpoint 3 says retrieval "meaningfully influences the agent's output" and demonstrates it with a before/after digest pair. | True, but the demonstration runs on a **seeded ledger**, not on organically accumulated history. | The two v1 beats do not naturally repeat — a score and a forecast are new every night — so a genuine repeat has not yet occurred in the wild. The mechanism is real, tested, and wired into the nightly run; what is synthetic is the *occasion*. Checkpoint 3 says so explicitly rather than implying weeks of live dedup. Retires when FR-17's AI-news beat lands, which is where repetition is frequent. | 2026-08-02 |
| 5 | Checkpoint 3 cites `k = 5`, `similarity_floor = 0.60`, `window_days = 14` as the retrieval design. | Those values ship, but they are **reasoned, not measured**. | Nothing has run against a real multi-week ledger, so no threshold here is empirically validated. The trace records every neighbour and its score precisely so they can be tuned from evidence later. Tracked as PRD §9 Q5. **A later checkpoint must not describe these as tuned.** | 2026-08-02 |
| 6 | Checkpoint 3 (submitted): "Retrieval of the classic kind arrives with the AI news beat, where the documents are articles." | Not built. FR-17's AI-news beat does not exist. | **A forward commitment, not a divergence yet.** It is the promise the submitted text makes about what comes next, so Checkpoint 4 is measured against it: document-shaped RAG over article text, with real chunking. Retires when FR-17's news beat ships. Until then no checkpoint may imply classic RAG is running. | 2026-08-02 |
| 7 | Checkpoint 3 (submitted): "nothing leaves the machine and my total costs remain $0". | True of the retrieval layer. Not true of the whole system. | Embeddings are local (model2vec) and both live APIs are free and keyless, so retrieval genuinely costs nothing. The digest still makes model calls that draw on Sarah's paid Claude subscription. In context the sentence is about the embedding step, so it reads as marginal cost rather than total cost. Minor, recorded rather than corrected. **Don't repeat "$0" as a claim about the system.** | 2026-08-02 |

## How to add a row

At `continue-capstone-build`'s conflict gate, and again after the build discovers reality. Record what was
*submitted* verbatim enough to be findable, what actually *shipped*, and **why** — the reasoning is the
part that's useful in a later essay. Date it.

If a divergence gets closed (the code catches up, or a later checkpoint revises the promise), leave the
row and note the closure rather than deleting it. The history is the point.

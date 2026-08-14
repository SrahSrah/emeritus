# STATUS — Emeritus

_Last updated: 2026-08-14_

> **Graduated from the playground on 2026-07-27.** Source: `playground/emeritus`.
> Home: `C:\Users\Sarah\Documents\31 Emeritus` → https://github.com/SrahSrah/emeritus (private).
> Git history starts fresh here. The per-step build commits (one per build step) stay on the
> `feature/forecaster` branch of `SrahSrah/playground` if you want to cite process in a checkpoint.

## Where things stand

Checkpoints 1.1, 2.x and **3.1 submitted** (3.1 on 2026-08-02). The capstone is built through
**increment 3**: 34 build steps, **419 tests green**, no network and no model calls in the suite.
First live end-to-end run succeeded 2026-08-04.

**FR-37 (2026-08-14) — within-run dedup. On `feature/within-run-dedup`, PR into `dev` open.**
FR-9b only ever compared a candidate against previous nights; two topics writing up one story in
the *same* run sailed through, observed live 2026-08-13 when the model patched the duplication in
prose. The dedup pass now also feeds the run's already-kept items to `assess_item` as same-beat
neighbours, every FR-19 invariant unchanged. Specced as FR-37 in the ai-news-beat PRD (numbered
after the need-to-know-news spec's FR-31 … FR-36 block, whose FR-36 depends on it). 455 tests green.

**Increment 3 (2026-08-04) — the AI news beat. Merged into `dev`, and it runs.**
FR-20 … FR-30: RSS discovery plus an article-body fetch, real chunking, a second vector collection
in its own file, and topic-query retrieval that **grounds** the prose rather than only selecting
lines. DIVERGENCES row 6 is **closed**. Row 4 is **not** — it needs 14 organic nights, which needs
[HUMAN-TODO](HUMAN-TODO.md) ④.

**First green news run, 2026-08-04:** 51 articles fetched (46 full bodies, 5 fell back to the feed
summary — all OpenAI, which blocks the fetch), three grounded items, provenance OK across 10
checkable fields, 84s, 313 output tokens, 5 ledger rows. On one topic the model **declined to write
an item** because the retrieved passages did not support one, which is the thesis working rather
than a gap.

**Read [docs/DIVERGENCES.md](docs/DIVERGENCES.md) row 8 before writing Checkpoint 4.** The
provenance check was loosened three times on its first three live runs and FR-11's fail-the-run
response was narrowed by FR-30. Every fix was a real false alarm, narrowly fixed and tested against
the true positive — but nothing has yet tried to fabricate and been caught in the wild, so the
guarantee has held without being tested.

**Module 3 increment (2026-08-02):** FR-9b shipped — retrieval-backed dedup against the sent-item
ledger, plus FR-19's safety invariants. PRD §9 **Q3 is answered** (Sarah's call: item identity is a
read-time relation, not a stored property), and §9 **Q1 is resolved** (email framed as a deliberate
scope cut, acknowledged in Checkpoint 3). DIVERGENCES rows 1 and 3 are **closed**; rows 4 and 5 are
new and both concern what Checkpoint 3 may not claim.

Capstone track: **Forecaster** — a nightly 7 pm CT text digest (AI/Claude news,
Astros, r/WallStreetBets, next-morning weather, need-to-know news, local live music),
with personalized escalation and dedup against past reports.

## Current module

| | |
|---|---|
| Module | 3 — RAG, vector databases, semantic retrieval |
| Deliverable | Written design update, 600–900 words, **plus a working agent update** |
| Draft | [assignments/assignment-3-retrieval.md](assignments/assignment-3-retrieval.md) |
| Build | FR-9b + FR-19 **merged into `dev`** 2026-08-04 (`f452153`), 265 tests green |
| State | **submitted 2026-08-02** |

### Module 3's architectural decision (locked)

**Retrieval is required, and scoped to exactly one place: the sent-item ledger.** The two v1 beats
are structured JSON APIs where a score is a field, not a passage, so retrieval adds nothing to
*grounding* — that job belongs to the tool call, and FR-11 already enforces it. What retrieval
changes is *selection*: deciding whether tonight's line tells Sarah anything she wasn't already
told. Similarity finds candidates; a model judgment decides; five invariants bound the judgment.

The number the design turns on, measured on the shipped model before the design was fixed:
`"Final: Houston Astros 4, Texas Rangers 2."` vs `"…5, Texas Rangers 2."` → **cosine 0.9859**.
Two different games. A threshold-only dedup would have dropped a real result.

### Checked against the "Outcome" criteria (Complete rating)

The doc's Outcome block lists five must-haves. Current text covers all five. The two
that needed work were fixed on 2026-07-26:

- **"A justification for *each* added capability"** — tools had an explicit prompt-only
  contrast; the reasoning loop and memory did not. Added one sentence to each.
- **"A clear description of the *refined* concept"** — the opening read as a restatement.
  Added "The concept is unchanged. What I've refined is the machinery underneath it."

## Capstone build — Forecaster

PRD: [docs/prd/forecaster/PRD.md](docs/prd/forecaster/PRD.md) (Draft, v1). Code will live at
`emeritus/forecaster/`. Non-UI, so no design phase — spec went straight to `build-build-prompts`.

Build prompts: [docs/prd/forecaster/BUILD-PROMPTS.md](docs/prd/forecaster/BUILD-PROMPTS.md) —
**19 ordered steps**, full coverage of all 16 MVP FRs, `[Later]` items (FR-9b/16/17) explicitly out
of scope. Resumable ledger: [docs/prd/forecaster/BUILD-PROGRESS.md](docs/prd/forecaster/BUILD-PROGRESS.md).

**Build state (2026-07-27): all 19 steps implemented**, one commit each, on
`feature/forecaster`. Code at `emeritus/forecaster/`. `uv run pytest -q` → **221 passed**.
The suite makes **no network call and no model call** — recorded HTTP fixtures plus a
socket guard, and a `FakeAgentClient` everywhere the model would otherwise be.

What is *not* verified, and why:

| Gate | Blocked on | Status |
|---|---|---|
| Live `--dry-run` end-to-end | `CLAUDE_CODE_OAUTH_TOKEN` not minted | Runner exits 2: *"refusing to start … will not fall back to an API key."* Working as designed. |
| FR-12 — digest in the inbox | SMTP app password **+** a human sending it | Delivery layer built and tested against a mocked `smtplib`; **no agent sends mail**. |
| FR-14 — three scheduled nights | Task Scheduler job registered **+** three nights | `scripts\run_nightly.ps1` written and verified in dry-run; **the agent did not register the task**. |

Three spec gaps were flagged rather than guessed, and remain open: FR-10's injury rule has no v1
data source (implemented, tested against a synthetic signal, **dormant**), FR-10's "freeze within N
days" exceeds the forecast horizon FR-6 fetches (rule applies over the fetched window only), and
FR-11's "applies the ledger check" contradicts FR-9's write-only scope (that check is FR-9b, blocked
on §9 Q3 — the synthesizer does not read the ledger, asserted by a test).

**A fourth inaccuracy surfaced during the build:** the PRD and BUILD-PROMPTS both describe
`abstractGameState` as *"Final / In Progress / Preview"*. The live endpoint returns **`Live`** for a
game in progress; `"In Progress"` is the `detailedState`. The adapter exposes both fields.

**Locked build decisions (2026-07-27):**

- **Stack:** Python 3.12 + `claude-agent-sdk`, authenticated via `CLAUDE_CODE_OAUTH_TOKEN` against
  Sarah's Claude subscription. ⚠️ `ANTHROPIC_API_KEY` must be **unset** in the job environment or it
  shadows the OAuth token and silently bills per-token. Agent SDK usage draws from subscription
  usage limits; the separate Agent-SDK monthly credit was announced then **paused** as of 2026-06-15.
- **v1 scope:** two beats only — Astros game state + next-morning Austin weather. Both APIs are
  free and keyless (`statsapi.mlb.com`, `api.weather.gov` — the latter needs a `User-Agent`).
  Verified live 2026-07-27.
- **Delivery:** email, **not** SMS. Diverges from what Checkpoints 1.1 and 2.x promise — a future
  checkpoint owes one sentence acknowledging the revision. Tracked as PRD §9 Q1.
- **Location:** Austin, TX (NWS grid EWX 156,91).
- **Flexibility strategy:** syllabus beyond Module 2 is unknown, so the design buys optionality
  generically — every beat behind one `Beat` protocol, every tool behind an adapter, config-driven
  runs, and a run trace that records more than v1 consumes so a later evaluation module has data.

## Progress log

| Date | What happened |
|---|---|
| 2026-08-14 | **FR-37 — within-run dedup.** The 2026-08-13 live run had the `claude` and `agents` topics both write up the same Anthropic finding, and the model noted the duplication in prose — a guard's job done in prose. Fix: the synthesizer's dedup pass now hands the run's already-kept items (same beat only) to `assess_item` as extra neighbours, scored by the same embedder against the same floor; every FR-19 invariant applies unchanged and a same-run neighbour is identifiable in the trace. ~A dozen lines in `synthesizer.py` plus a scoring helper in `retrieval.py`; specced as FR-37 in the ai-news-beat PRD. 455 tests green, PR into `dev`. |
| 2026-07-26 | Created the `emeritus` playground project and scaffolded trackers. |
| 2026-07-26 | Drafted Assignment 2 and wrote it into the shared Google Doc under `ASSIGNMENT 2: SUBMISSION:`. |
| 2026-07-27 | Assignment 2 submitted. Wrote the Forecaster PRD (v1, 18 FRs) and locked the build decisions above. |
| 2026-07-27 | Decomposed the PRD into BUILD-PROMPTS.md — 19 steps, all MVP FRs covered, 3 spec gaps + 2 human gates flagged. |
| 2026-07-27 | **Built all 19 steps** on `feature/forecaster` (one commit per step), 221 tests green, PR opened into `dev`. Live run blocked on the OAuth token; FR-12's send and FR-14's three nights left at their human gates. Added `tzdata` (Windows has no tz database) and corrected the `abstractGameState` value for live games. |
| 2026-08-04 | **First live end-to-end run.** `auth_mode=subscription_oauth`, provenance OK across 7 checkable fields with 0 violations, 12.0s, 2 in / 85 out tokens, nothing sent (FakeDeliverer). Then merged PR #1 into `dev` as `f452153`. `main` still untouched. |
| 2026-08-02 | **Checkpoint 3 submitted.** Final text logged verbatim at [assignments/assignment-3-retrieval.md](assignments/assignment-3-retrieval.md). It commits to document-shaped RAG landing with the AI news beat, recorded as DIVERGENCES row 6 and now the top build priority. |
| 2026-08-02 | Fixed a silent-suppression bug FR-19 was supposed to prevent: three Astros items carried no date, so two off days in a row, or two different games sharing a scoreline, reached the model as suppression candidates. Dates added to `BeatItem.fields`; `tests/test_time_scoped_items.py` guards it. 265 tests green. |
| 2026-08-04 | **First green end-to-end run with all three beats**, after three consecutive provenance failures — every one a false alarm, each fixed narrowly and merged (PRs #3, #4, #5, #6). (1) Two true scores sharing a sentence shape: a fidelity template from one game matched the other game's sentence. A **v1 bug latent since 2026-07-27** that would have fired on most nights of a series. (2) A curly apostrophe versus an ASCII one in a quotation. (3) A truncated quotation ending in a period where the source has a comma. (4) **FR-30**, Sarah's call: an item-level violation now quarantines the item and names the withholding, instead of killing the whole digest — one punctuation mark had cost the Astros score, the forecast, and everything else. Also captured `mlb_series_today/lookback` as **real recordings**, closing a fixture blind spot where every MLB fixture descended from one captured game. **442 tests.** |
| 2026-08-04 | **Increment 3 built — the AI news beat.** Steps 23–34 on `feature/ai-news-beat`, one commit each, **419 tests green** (from 265). Retrieval now grounds prose rather than only selecting lines, which is what Checkpoint 3 promised. Two safety mechanisms had to grow: **FR-26** (provenance gained a case, because neither the support nor the fidelity check can see a number the model *invented* into a sentence) and **FR-27** (FR-19's first invariant inverts for a document-shaped beat — it was transplanted from typed fields to grounded prose). Three silent bugs found and fixed en route: `published` stored in the publisher's own UTC offset while the window filter compared strings; "all sources failed" tested as "no entries", so a quiet night read as an outage; a cold corpus raised instead of returning empty, making the first-ever run report itself broken. FR-2's seam held — `git diff dev...HEAD` touches none of `planner.py`, `synthesizer.py`, `delivery/`. |
| 2026-08-04 | **AI news beat decomposed into build prompts.** [docs/prd/ai-news-beat/BUILD-PROMPTS.md](docs/prd/ai-news-beat/BUILD-PROMPTS.md) — **Steps 23–34**, continuing the parent ledger. Full coverage of FR-20 … FR-29; no FR withheld, unusually for this project (Q2/Q5/Q6 constrain *how* steps build, not *whether*). Found a prerequisite the PRD missed: the fixture harness is JSON-only (`load_fixture`, `mock_transport`, `capture_fixture.py` all assume JSON), so Step 23 widens it to XML/HTML/text or the no-network rule can't hold for the new adapters. |
| 2026-08-04 | **AI news beat specced.** [docs/prd/ai-news-beat/PRD.md](docs/prd/ai-news-beat/PRD.md) — FR-20 … FR-29, RSS discovery plus article-body fetch (free and keyless; no news API returns full article text at any price, so paying would not have bought the feature). Parent FR-17 amended to point here for the news beat only. Two findings: FR-11's provenance check must grow a case for model-synthesized item text, and **FR-19's first invariant inverts for a document-shaped beat** — any per-artifact field in a news item's `fields` silently disables dedup for that beat. Child FR-27 transplants the invariant to grounded prose. |
| 2026-08-02 | **Module 3 increment.** §9 Q3 answered → FR-9b unblocked and built (Steps 20–22) on `feature/fr-9b-retrieval`: model2vec embeddings + a sqlite-vec index inside `ledger.db`, retrieval-narrows/model-judges dedup, and FR-19's five safety invariants. **256 tests green**, no torch, no paid service. Drafted Checkpoint 3 against the shipped code. Found and fixed a silent bug: numeric fields that round-tripped through JSON compared unequal, which would have disabled suppression invisibly. |

## Assignment 2 — design decisions (locked)

These are the choices the submission commits to. Later modules should stay consistent
with them or explicitly note the revision.

- **Reasoning loop:** planner above per-beat ReAct workers, plus a synthesizer that
  dedupes, applies escalation rules, and composes the message.
- **Memory:** both. Short-term = per-run scratchpad, discarded on send. Long-term =
  (a) a ledger of everything already sent, for dedup and "what's new about this story",
  (b) a preference profile.
- **Feedback:** reply to the nightly text in plain English → parsed into a durable
  preference rule; new rules held provisional until repeated or confirmed.
- **Tool centerpiece:** MLB Stats API (`statsapi.mlb.com`) for Astros game state —
  free, no key. Verified live on 2026-07-26: returns `abstractGameState`, UTC start
  time, score, per-game ID. Covers recency + grounding + the UTC/doubleheader arithmetic.
  ⚠️ Corrected 2026-07-27: `abstractGameState` is **`Live`** for a game in progress, not
  `"In Progress"` — that string is the separate `detailedState` field. The earlier note
  here was wrong and would have made any branch on it silently never match.
- **Failure mode named:** the confident fabricated box score — a prompt-only model
  invents a plausible final and cannot signal that it doesn't know.

## Modules

| # | Module | Notes | Assignment | State |
|---|---|---|---|---|
| 1 | Agent concept | — | Forecaster concept | submitted |
| 2 | Agent architecture | — | [text](assignments/assignment-2-agent-architecture.md) | submitted |
| 3 | RAG / vector databases | Wants a **working agent update**, not just prose | [text](assignments/assignment-3-retrieval.md) | submitted |
| — | _rest of syllabus TBD_ | | | |

## Open questions

- Which program / cohort is this? (README "Program" block is still blank.)
- Is there a graded capstone, and when is it due?
- Open design question carried into later modules: how much escalation logic can be
  rules vs. judgment.

## Caveat worth remembering

`statsapi.mlb.com` is an undocumented public endpoint under MLB's copyright terms.
Fine for a personal capstone; not something to build a product on.

# STATUS — Emeritus

_Last updated: 2026-08-24_

> **Graduated from the playground on 2026-07-27.** Source: `playground/emeritus`.
> Home: `C:\Users\Sarah\Documents\31 Emeritus` → https://github.com/SrahSrah/emeritus (private).
> Git history starts fresh here. The per-step build commits (one per build step) stay on the
> `feature/forecaster` branch of `SrahSrah/playground` if you want to cite process in a checkpoint.

## Where things stand

**Spec 2026-08-24 — the r/WallStreetBets beat, the last unbuilt Checkpoint 1 beat.**
[`docs/prd/wsb-beat/PRD.md`](docs/prd/wsb-beat/PRD.md), FR-48 … FR-52; parent FR-17 amended —
all four FR-17 beats now have child specs. Spec only, no code yet; DIVERGENCES row 10 closes
when the build increment merges. The framing decision *is* the spec: Checkpoint 1's "stock
market picks" killed in favor of mention-volume counting (the narrowing Checkpoints 2/3/5
already submitted) — counts computed in code, zero model calls, a counts-not-picks invariant
enforced by test. Endpoints re-verified at spec time: `.rss` 200 (Atom, 25 hot posts), JSON
403, a second request 12 s later 429, and reddit robots.txt is now a blanket `Disallow: /` —
Sarah's call (interview, four decisions recorded in the PRD): fetch on the FR-20
feed-syndication precedent, never spoof, dark via FR-18 if Reddit ever refuses the feed.

Checkpoints 1.1, 2.x and **3.1 submitted** (3.1 on 2026-08-02). The capstone is built through
**increment 3**: 34 build steps, **419 tests green**, no network and no model calls in the suite.
First live end-to-end run succeeded 2026-08-04.

**Increment 4 (2026-08-14) — the need-to-know beat, v4 (observation). Built on
`feature/need-to-know-beat`, Steps 35–39, 498 tests green.**
FR-31 … FR-35: the sixth beat's substrate, deliberately delivering **nothing** — it fetches four
general-news wires (real fixtures captured live), indexes into the shared `corpus.db` (with a
config-load guard against TTL disagreement), computes a source-scoped corroboration count per
in-window article with full provenance, and proves its own silence in the trace
(`corroboration_observed` / `no_candidates`; `--ntk-metric` reads them). Zero model calls — the
tests inject a client that raises on contact. The bar (FR-36, FR-38 … FR-41) is decided but not
built; the distribution this increment accumulates is what tunes it. Discovered en route: **NPR
times out the article fetch** — expect summary fallback from it in production, like OpenAI on the
AI beat.

**FR-37 (2026-08-14) — within-run dedup. Merged into `dev` (PR #12).**
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
| 2026-08-24 | **Increment 6 built — the need-to-know bar (v5, FR-36 + FR-38 … FR-41).** Steps 45–50 on `feature/need-to-know-bar`, one commit each, **581 tests green** (from 550). The beat now delivers: config-owned bar categories with named exclusions; the watchlist carve-out (whole-word, headline + first chunk) bypassing gate and judgment and escalating via the deterministic `need_to_know_watchlist` rule; the gated suppress-when-unsure judgment with **named abstention** on failure (a deliberate inversion of FR-19(d), safe because it is loud); the provenance-checked pulse line (quiet nights now inbox-visible, counts supported by a traced tally); one-way cross-beat deferral that names its cover; and metric conditions (d)–(f) with nightly gate-pass counts (pre-v5 history reported n/a, never recomputed). Highlight from the build: FR-30 quarantined a test fixture's ungrounded figure — the guardrail caught its own author. Seam: planner/delivery untouched; synthesizer edited only in Step 49 as dedup machinery. All six Checkpoint 1 beats now deliver or account for themselves; only r/WSB remains unbuilt. |
| 2026-08-24 | **Checkpoint 6 submitted** (safety and intervention plan). Final text logged verbatim at [assignments/assignment-6-safety.md](assignments/assignment-6-safety.md). Headline choice: the guarantee "has held, but it has never once been tested by a real fabrication," with the four false alarms told in full and the floor retune as evaluation-changing-the-system. **Locks:** no guardrail loosened without Sarah's review; open design questions stop the build; nothing runs unattended until the plan has been watched working (three verified scheduled nights). **DIVERGENCES row 10 added:** the opener lists a r/WSB summary among the digest's contents and that beat is unbuilt — next fresh increment closes it. |
| 2026-08-20 | **The corroboration floor is the project's first measured threshold: 0.55 → 0.35.** Night 3 banked (run `20260820T151604`), then a floor sweep over the live corpus (`scripts/corroboration_sweep.py`, 162 articles, floors 0.35–0.55 × windows 2–3): above 0.40 no candidate ever reached two sources — the reasoned 0.55 made v5's `min_sources = 2` gate structurally dead — while 0.35 yields ~2 gate-passing candidates/night (spot-checked: genuinely co-covered stories, e.g. an FDA nomination on Al Jazeera + BBC). Retuned per Sarah's standing instruction under the pre-stated rule; the old floor-inequality proxy test replaced by a pin on the measured value. `window_days`/`min_sources`/band remain reasoned; "measured on three nights" ≠ "tuned on fourteen" (§9 Q7 partially answered — first of the Q5/Q6/Q7 family to graduate). |
| 2026-08-16 | **Need-to-know evidence gate set to 2 nights (Sarah's call).** `ntk_metric.TARGET_NIGHTS` 1 → 2: two nights of corroboration distribution is her chosen gate before building v5 (the bar), replacing the one-night dev concession. Still a divergence from the parent's 14, same row-9 posture — no checkpoint may present a two-night result as the fourteen-night one. |
| 2026-08-16 | **Increment 5 built — the venue-listings beat, v1 (FR-42 … FR-46).** Steps 40–44 on `feature/venue-listings-beat`, one commit each, **548 tests green** (from 498). `[venues]` config + `[retrieval] exempt_beats`; the ZACH parser off a live capture (11 productions; parsed-empty vs redesign kept structurally distinct); the beat itself — 14-day window, digest lines quoting the venue's **own dates text verbatim** (deviation from the PRD's paraphrase sample, for provenance exactness; a tampered-date test proves FR-11 bites); the dedup opt-out as an accounted bypass (zero retrieval/model cost for exempt items, `dedup_exempt` on every repeat); and `--venues-metric`, whose load-bearing condition is **never-suppressed**. Zero model calls in the whole beat. Ships enabled: with the clock at the capture evening, tonight's digest lists *Sally & Tom* (through Aug 23) and *Come From Away* (opens Aug 19). Seam clean. |
| 2026-08-16 | **Venue-listings beat specced (FR-42 … FR-47)** — [docs/prd/venue-listings/PRD.md](docs/prd/venue-listings/PRD.md), from Sarah's re-scope: named venues, not discovery; **no dedup, repeats deliberate** (made auditable — a never-suppressed metric condition). Structured beat, zero model calls. v1 is **ZACH-only**: measured 2026-08-14, `www.zachtheater.org/tickets/shows/` is server-rendered and keyless with no robots Disallow (domain gotcha: one "t"); TPA and Broadway in Austin WAF-403 everything including robots.txt. Bass = FR-47 `[Later]`, gated on the Ticketmaster developer account — **signup failed 2026-08-16**, retry steps in HUMAN-TODO; free tier verified (5,000 calls/day vs ~1/night). First keyed dependency, approved by Sarah conditional on the free tier. Parent FR-17 amended; only r/WSB remains unspecced. |
| 2026-08-14 | **Increment 4 built — the need-to-know beat's observation substrate (v4, FR-31 … FR-35).** Steps 35–39 on `feature/need-to-know-beat`, one commit each, **498 tests green** (from 455). Config schema with a shared-corpus TTL-equality guard; co-tenancy proven (url-keyed replace, cutoff-only purge, idempotent); `corroborating_sources` — a read-time count probing with the stored ordinal-0 vector, no identity written; the beat itself, emitting zero digest items and proving its silence per candidate; `--ntk-metric` with the quiet-vs-broken discriminator and the distribution report. Real fixtures captured live for all four feeds + a Texas Tribune article/robots pair. **NPR timed out the article fetch twice** — summary fallback is its expected production behaviour. Zero model calls anywhere in the increment. Seam verified: `git diff dev...HEAD` touches none of `planner.py`, `synthesizer.py`, `delivery/`. |
| 2026-08-14 | **FR-37 — within-run dedup.** The 2026-08-13 live run had the `claude` and `agents` topics both write up the same Anthropic finding, and the model noted the duplication in prose — a guard's job done in prose. Fix: the synthesizer's dedup pass now hands the run's already-kept items (same beat only) to `assess_item` as extra neighbours, scored by the same embedder against the same floor; every FR-19 invariant applies unchanged and a same-run neighbour is identifiable in the trace. ~A dozen lines in `synthesizer.py` plus a scoring helper in `retrieval.py`; specced as FR-37 in the ai-news-beat PRD. 455 tests green, PR into `dev`. |
| 2026-08-14 | **The need-to-know bar decided, same day.** Sarah answered §9 Q2 for this beat via structured interview (eight decisions, recorded in the child PRD §9 Q2): FR-9b split transferred to importance, **suppress-when-unsure** (inverted from dedup, with the inversion's no-backstop cost named), mechanical watchlist carve-out that bypasses the bar and escalates via a new deterministic rule, calibration target 2–3 delivering nights per 14 (report-only band), categories in / elections & major-figure deaths **deliberately out**, nightly provenance-checked quiet pulse line, one-way cross-beat deferral. FR-36 rewritten from blocked placeholder into buildable v5 (since renumbered FR-36 + FR-38 … FR-41 — see the next row); parent §9 Q2 narrowed (selection answered, escalation still open). Every new number is a target, not a measurement — §9 Q1/Q7 grew. Within-run dedup fix and FR-30 retro-spec running in their own sessions. |
| 2026-08-14 | **Numbering collision found and resolved at rebase.** The within-run dedup session and the need-to-know spec session both claimed FR-37 concurrently — dedup merged first (PR #12, ai-news PRD), so its number stands and the need-to-know v5 renumbered to FR-38 … FR-41 (watchlist, pulse, deferral, band). Its landing satisfies v5's only external dependency: v5 now waits only on v4. PR #10 rebased onto `dev`; **note PR #10 is still open** — the merges on 2026-08-14 were #11 and #12. |
| 2026-08-14 | **Need-to-know news beat specced** — [docs/prd/need-to-know-news/PRD.md](docs/prd/need-to-know-news/PRD.md), FR-31 … FR-36; parent FR-17 amended, parent §9 gains Q7. The spec first argues it *is* a beat (inverted delivery contract, distinct sources, corroboration machinery that doesn't exist) and then concedes the honest limit: the bar ("higher than the daily drudgery") is unwritable without §9 Q2, so v4 is **observation-only** — reuse the news plumbing over four live-verified general-news feeds (BBC World, NPR, Al Jazeera, Texas Tribune; Guardian blocked the fetch), shared `corpus.db` with a TTL-equality guard, read-time source-scoped corroboration counts with full provenance, zero digest content, zero model calls. FR-36 (the bar + delivery) is `[Later]`, blocked on Q2, with both uncertainty defaults' costs written out for Sarah's decision. Within-run dedup ruled its own increment. Docs only; 448 tests green, untouched. |
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

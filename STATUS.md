# STATUS — Emeritus

_Last updated: 2026-07-27_

> **Graduated from the playground on 2026-07-27.** Source: `playground/emeritus`.
> Home: `C:\Users\Sarah\Documents\31 Emeritus` → https://github.com/SrahSrah/emeritus (private).
> Git history starts fresh here. The per-step build commits (one per build step) stay on the
> `feature/forecaster` branch of `SrahSrah/playground` if you want to cite process in a checkpoint.

## Where things stand

Checkpoints 1.1 and 2.x both **submitted**. The capstone is **built**: all 19 build steps
implemented and merged, 221 tests green. The pipeline has never made a live model call —
`CLAUDE_CODE_OAUTH_TOKEN` isn't minted yet, which is the one blocker on a first real run.
See [HUMAN-TODO.md](HUMAN-TODO.md) items ①–④.

Capstone track: **Forecaster** — a nightly 7 pm CT text digest (AI/Claude news,
Astros, r/WallStreetBets, next-morning weather, need-to-know news, local live music),
with personalized escalation and dedup against past reports.

## Current module

| | |
|---|---|
| Module | 2 — agent architecture (reasoning loops, memory, tools) |
| Deliverable | Written refinement of the Checkpoint 1.1 concept, 600–900 words |
| Draft | [assignments/assignment-2-agent-architecture.md](assignments/assignment-2-agent-architecture.md) — 879 words, synced to the doc |
| State | **submitted 2026-07-27** |

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
| 2026-07-26 | Created the `emeritus` playground project and scaffolded trackers. |
| 2026-07-26 | Drafted Assignment 2 and wrote it into the shared Google Doc under `ASSIGNMENT 2: SUBMISSION:`. |
| 2026-07-27 | Assignment 2 submitted. Wrote the Forecaster PRD (v1, 18 FRs) and locked the build decisions above. |
| 2026-07-27 | Decomposed the PRD into BUILD-PROMPTS.md — 19 steps, all MVP FRs covered, 3 spec gaps + 2 human gates flagged. |
| 2026-07-27 | **Built all 19 steps** on `feature/forecaster` (one commit per step), 221 tests green, PR opened into `dev`. Live run blocked on the OAuth token; FR-12's send and FR-14's three nights left at their human gates. Added `tzdata` (Windows has no tz database) and corrected the `abstractGameState` value for live games. |

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
| — | _rest of syllabus TBD_ | | | |

## Open questions

- Which program / cohort is this? (README "Program" block is still blank.)
- Is there a graded capstone, and when is it due?
- Open design question carried into later modules: how much escalation logic can be
  rules vs. judgment.

## Caveat worth remembering

`statsapi.mlb.com` is an undocumented public endpoint under MLB's copyright terms.
Fine for a personal capstone; not something to build a product on.

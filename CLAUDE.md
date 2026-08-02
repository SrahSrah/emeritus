# CLAUDE.md — Emeritus

Repo-level guidance. Sarah's global `~/.claude/CLAUDE.md` still applies; this specializes it.

## What this repo is

Coursework for an **online AI program from Emeritus**, plus the capstone it builds toward.
Two things live here and they have different rules:

1. **Written checkpoints** (`assignments/`, `modules/`, `writing/`) — a short essay is due
   roughly weekly. This is **prose work**: craft matters, it must sound human, and every
   factual claim gets grounded.
2. **The Forecaster** (`forecaster/`) — the capstone agent. This is **code work**: terse,
   tests green before "done".

Don't apply code-mode terseness to the essays or prose-mode looseness to the code.

## The Forecaster, in one paragraph

A nightly digest, delivered by email around 7 pm CT, covering things Sarah stopped seeing when
she quit social media. v1 runs two beats: **Astros game state** (MLB Stats API) and
**next-morning Austin weather** (National Weather Service). Architecture is a planner above
per-beat ReAct workers, then a synthesizer that applies escalation rules and composes the
message. The thesis the whole capstone argues: **every checkable fact traces to a tool call.**
The model phrases; it never originates a score or a temperature.

Since 2026-08-02 the synthesizer also runs a **retrieval-backed ledger check** (FR-9b) before
composing: semantic search over everything already delivered, then a model judgment on whether
tonight's line adds anything. Similarity finds candidates; it never decides. FR-19's invariants
are why — a checkable value that differs from its nearest neighbour can be reframed but never
suppressed, because silence is a worse failure here than repetition.

## Non-negotiables

- **Auth is subscription OAuth, never an API key.** `CLAUDE_CODE_OAUTH_TOKEN` only.
  `assert_subscription_auth()` refuses to start if `ANTHROPIC_API_KEY` is present, and
  `scripts/run_nightly.ps1` strips it. Do not add an API-key fallback — that guard is the
  feature, not an obstacle.
- **No network in the test suite.** Recorded HTTP fixtures plus a socket guard (loopback is
  allowed so asyncio works on Windows). New adapter → capture its fixture in the same change.
- **No model calls in tests.** `FakeAgentClient` everywhere.
- **Never fabricate a fact to fill a gap.** If a tool fails, the digest says so explicitly and
  carries no substitute value. That behavior is FR-18 and it is the point of the project.
- **Both external APIs are free and keyless.** `statsapi.mlb.com` and `api.weather.gov` (the
  latter rejects requests with no `User-Agent`). Don't introduce a paid dependency without
  raising it first.

## The weekly loop

Two global skills drive this repo. Run them in this order, once a week:

1. **`/write-next-assignment`** — drafts the next checkpoint into the course Google Doc, in Sarah's
   voice, grounded in what this repo actually does.
2. **`/continue-capstone-build`** — folds what that checkpoint newly promises into the PRD, builds the delta,
   and opens a PR into `dev` (unmerged — Sarah merges).

They share [docs/DIVERGENCES.md](docs/DIVERGENCES.md): every place the submitted text and the shipped
code disagree, and why. **Check it before writing any sentence about what the agent does** — it's the
file that stops a checkpoint claiming a feature that shipped dormant.

## Spec is the source of truth

`docs/prd/forecaster/PRD.md` — numbered functional requirements with acceptance criteria.
`BUILD-PROMPTS.md` decomposes it; `BUILD-PROGRESS.md` is the resumable ledger.

**PRD §9 lists open questions. Do not invent answers to them.** If a change would require
answering one, stop and surface it.

Q3 (item identity) **was** the live one; Sarah answered it on 2026-08-02 — *identity is a
relation computed at read time, not a property stored on an item* — which unblocked FR-9b, so
the ledger is no longer write-only. Still open: **Q2** (rules vs judgment for escalation) and
**Q5** (the retrieval thresholds are reasoned, not measured — don't let a checkpoint call them
tuned).

## Gotchas that cost time already

- `abstractGameState` is **`Live`** for a game in progress. `"In Progress"` is the separate
  `detailedState` field. Branching on the wrong one silently never matches.
- Stdlib `zoneinfo` has **no tz database on Windows** — `tzdata` is a required dependency.
- PowerShell 5.1's `Tee-Object` writes UTF-16 into a UTF-8 log and wraps native stderr in
  ErrorRecords. Use `Start-Process` with redirect files.
- FR-10's injury rule is **dormant**: no v1 endpoint returns injury data. It is implemented and
  tested against a synthetic signal on purpose.
- **sqlite-vec's KNN returns distance, not similarity.** Over unit vectors,
  `similarity = 1 - d²/2`. Inverting that means nothing is ever a duplicate and the tests still
  pass for the wrong reason — there's a test asserting an identical line scores ~1.0.
- **Static embeddings are near-blind to numerals.** Two different Astros finals score **cosine
  0.9859**. Never dedup on similarity alone; FR-19's invariants exist for exactly this.
- **Compare checkable values numerically, not as strings.** The ledger round-trips through JSON,
  so an int `41` meets a stored `"41.0"`. A string compare reads that as new information and
  silently disables suppression for every numeric field.

## Conventions

- Python 3.12, `uv`. `uv run pytest -q` before calling anything done.
- Feature branches off `dev`, PR'd into `dev`. Never commit to `main` directly.
- Keep `STATUS.md` and `HUMAN-TODO.md` live. `HUMAN-TODO.md` is only what Sarah must do herself
  — minting tokens, sending the first real email, registering the scheduled task.

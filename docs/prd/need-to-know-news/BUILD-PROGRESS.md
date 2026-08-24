# BUILD PROGRESS — Need-to-know news beat, v4

Resumable ledger for [`BUILD-PROMPTS.md`](BUILD-PROMPTS.md). Committed to the branch so it rides
along with each per-step commit.

**Resume rule:** read this file, reconcile against `git log`, skip every `done` step, continue from
the first `todo` or `blocked`. If this file and git disagree, **trust the working tree and git
log**, repair this file, and say so.

- **Branch:** `claude/need-to-know-news-spec-1f0dff` (PR #10; rename to
  `feature/need-to-know-beat` when building starts, per the ai-news precedent), based on `dev`
  at `2d8ae60`
- **Baseline:** 455 tests green on `dev` (`2d8ae60`, includes FR-37 within-run dedup)
- **Verify command:** `cd forecaster; uv run pytest -q`
- **Scope:** v4 only — FR-31 … FR-35. v5 (FR-36, FR-38 … FR-41) is out of scope and gets its own
  decomposition after v4 lands.

## Environment deviations from the skill's defaults

- No `scripts/new-worktree.mjs` in this repo (that helper is Scout's). Build in an isolated
  worktree off `dev` per repo convention.
- No `scripts/check-protected-paths.mjs`. The equivalent gates are the `ast`/guard tests named in
  BUILD-PROMPTS' environment block — **none may be edited to force a green run**.
  `test_time_scoped_items.py`'s coverage test will fire when the beat registers; Step 38 satisfies
  it with real fixtures, by design.

## Steps

> **SHA convention:** a step's commit SHA is written in during the *next* step's commit, since a
> commit cannot contain its own hash. If the last row shows `done` with no SHA, it is the tip
> commit — read it from `git log`.

| # | Step | Status | Commit | Notes |
|---|---|---|---|---|
| 35 | `[need_to_know]` config schema + TTL-equality rule | **done** | `23660d1` | 467 tests (+12). `[need_to_know]` optional like `[news]`; chunking/corpus/feeds parsing extracted into shared `_parse_*` helpers (news error messages unchanged, asserted by the existing suite). TTL rule fires only with both sections present. `need_to_know = false` until Step 38. |
| 36 | Shared-corpus co-tenancy proof | **done** | `66c8ac0` | 470 tests (+3). No production change needed, as predicted — corpus.py is already url-keyed and path-agnostic. `_entry` helper gained a `source` kwarg. Purge proven cutoff-only and idempotent across tenants. |
| 37 | Corroboration counter | **done** | `678bbe6` | 478 tests (+8). Probe is the stored ordinal-0 vector read back from vec0 — nothing re-embedded, no embedder param. Same-source and same-url excluded; source-list scoping proven against an AI-beat tenant. Schema-guard test asserts the SCHEMA string gained no identity storage. |
| 38 | `NeedToKnowBeat` + silence accounting + fixtures | **done** | `2f6ed29` | 489 tests (+11). Real fixtures captured for all four feeds; Texas Tribune article + robots captured; **NPR timed out the article fetch twice** — expect summary fallbacks from it in production, like OpenAI on the AI beat. cli corpus block generalized: any enabled beat whose config section has a `corpus` block gets a connection, keyed by resolved path (shared path = one connection). Coverage test satisfied with real fixtures. Seam verified: no edit to planner/synthesizer/delivery. Suite slowed to ~75s (ntk tests index ~560 real chunks per run). |
| 39 | Observation metric checker + CLI | **done** | — | 498 tests (+9). `ntk_metric.py` reuses `Condition` from news_metric; n/a-not-pass posture kept. Verified against the real data/runs: 0 runs examined, all n/a — correct, the beat has never run live. Beat gained `text_source` in the corroboration payload so the report can surface the per-source article/summary split §8 asks for. |

## v5 — the bar (appended 2026-08-19)

- **Branch:** `feature/need-to-know-bar`, cut from `dev` (`358e801`)
- **Baseline:** 550 tests green on `dev`; two live nights banked (evidence gate 2 of 2 met)
- **Scope:** FR-36 + FR-38 … FR-41, per BUILD-PROMPTS' v5 section. **The measured-dead-gate flag
  governs:** `min_sources = 2` at `floor = 0.55` passed zero candidates on both measured nights —
  ship the mechanism, surface the number nightly (Step 50), never tune it silently.

| # | Step | Status | Commit | Notes |
|---|---|---|---|---|
| 45 | Bar config: min_sources, watchlist, bar lists | **done** | `75c5078` | 553 tests (+3 net of 550). v5 blocks REQUIRED once [need_to_know] exists; watchlist dupes rejected case-insensitively; bar deliver/exclude both non-empty by rule. `need_to_know_watchlist` escalation rule registered DORMANT (injury-rule landing pattern) and configured first in the rules list; Step 46 populates its signal. |
| 46 | Watchlist carve-out + deterministic escalation | **done** | `7a5a714` | 558 tests (+5). Match = headline + first stored chunk, whole-word, case-insensitive (a term in the BODY hits too — test construction learned that the specced way). Items model-written via the news beat's copied contract; corpus gained `chunks_for`; helpers watchlist terms changed to ones absent from the real captures (TT capture mentions ERCOT). Invariant-2 unsuppressibility proven on the real produced item; tampered-number FR-26 test bites at the item layer. |
| 47 | Importance judgment: gate → judge → suppress-when-unsure | **done** | — | 566 tests (+8). Gate reads the observed counts (corroboration_observed now carries min_sources, so FR-41 computes gate-passes from the trace alone). Unrecognisable verdict = uncertainty = suppress. Judgment failure = named abstention with the unassessed count; already-judged deliveries stand. Bar lists proven to reach the prompt from config. v4 metric conditions verified to still hold under the bar. |
| 48 | Pulse line: quiet nights and abstentions | todo | — | |
| 49 | Cross-beat deferral, one-way | todo | — | |
| 50 | Bar-phase metric (d)–(f) + gate-pass count | todo | — | |

## Log

- **2026-08-19** — v5 section opened. Steps continue at 45 (venues v1 used 40–44). Sarah's call:
  decompose now rather than retune first; the dead-gate finding rides the prompts as a flag.
- **2026-08-14** — Ledger opened alongside BUILD-PROMPTS. Step numbering continues at 35: the
  FR-37 within-run dedup increment was a single direct commit (`c3305ef`) and consumed no steps.

## Blockers surfaced

_None yet._

## Bugs found and fixed during the build

_None yet._

## For HUMAN-TODO

Nothing new anticipated: the four feeds are keyless, and the standing items (①–④, feed-list and
watchlist review) already cover this feature. Step 38's live fixture capture needs network once,
outside the test suite, from the build session.

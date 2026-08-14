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
| 35 | `[need_to_know]` config schema + TTL-equality rule | **done** | — | 467 tests (+12). `[need_to_know]` optional like `[news]`; chunking/corpus/feeds parsing extracted into shared `_parse_*` helpers (news error messages unchanged, asserted by the existing suite). TTL rule fires only with both sections present. `need_to_know = false` until Step 38. |
| 36 | Shared-corpus co-tenancy proof | todo | — | |
| 37 | Corroboration counter | todo | — | |
| 38 | `NeedToKnowBeat` + silence accounting + fixtures | todo | — | |
| 39 | Observation metric checker + CLI | todo | — | |

## Log

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

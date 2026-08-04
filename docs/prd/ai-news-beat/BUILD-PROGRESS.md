# BUILD PROGRESS — AI news beat

Resumable ledger for [`BUILD-PROMPTS.md`](BUILD-PROMPTS.md). Committed to the branch so it rides
along with each per-step commit.

**Resume rule:** read this file, reconcile against `git log`, skip every `done` step, continue from
the first `todo` or `blocked`. If this file and git disagree, **trust the working tree and git log**,
repair this file, and say so.

- **Branch:** `feature/ai-news-beat`, cut from `dev` (`98690ba`)
- **Worktree:** `.claude/worktrees/ai-news-beat-rag-spec-4cc1b9`
- **Baseline:** 265 tests green on `dev`
- **Verify command:** `cd forecaster; uv run pytest -q`

## Environment deviations from the skill's defaults

- No `scripts/new-worktree.mjs` in this repo (that helper is Scout's). The build runs in the existing
  isolated worktree, which is already off `dev`.
- No `scripts/check-protected-paths.mjs`. This repo's equivalent gates are the `ast` tests that
  assert the FR-2 seam (`test_cli.py`, `test_synthesizer.py`) and the no-identity-column guard
  (`test_ledger.py`). **None of them may be edited to force a green run.** `test_time_scoped_items.py`
  is amended in Step 31, but by design and per FR-27, not to dodge a failure.

## Steps

> **SHA convention:** a step's commit SHA is written in during the *next* step's commit, since a
> commit cannot contain its own hash. If the last row shows `done` with no SHA, it is the tip commit
> — read it from `git log`.

| # | Step | Status | Commit | Notes |
|---|---|---|---|---|
| 23 | Text/bytes fixtures in the harness | **done** | `407afbf` | 271 tests (+6). `load_text_fixture` requires the extension; `Route.text`/`content_type`; `capture_fixture.py --raw`. Regression case asserts all three JSON route shapes unchanged. |
| 24 | News config schema | **done** | — | 289 tests (+18). `[news]` is **optional** — every pre-news config (including `tests/helpers.BASE_CONFIG`) is still valid; enabling the beat without the section is what raises. `[beats] news = false` until Step 32. |
| 25 | RSS/Atom feed adapter | todo | — | — |
| 26 | Article body fetch and extraction | todo | — | — |
| 27 | Paragraph-aware chunking | todo | — | — |
| 28 | Article chunk corpus | todo | — | — |
| 29 | Topic-query retrieval | todo | — | — |
| 30 | Grounded-text provenance check | todo | — | — |
| 31 | Grounded-value suppression veto | todo | — | — |
| 32 | News beat worker | todo | — | — |
| 33 | Per-source failure handling | todo | — | — |
| 34 | News-beat metric checker | todo | — | — |

## Log

- **2026-08-04** — Ledger opened. Branch renamed from `claude/ai-news-beat-rag-spec-4cc1b9` to
  `feature/ai-news-beat`; the PRD (`ac7c98f`) and BUILD-PROMPTS (`75b6bb8`) commits are already on it.

## Deviations from the build prompts

_None yet._

## Blockers surfaced

_None yet._

## For HUMAN-TODO

_None yet beyond what the PRD already flagged (③ SMTP, ④ scheduled task, Q6 thresholds, feed-list
review)._

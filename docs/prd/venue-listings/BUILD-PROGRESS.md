# BUILD PROGRESS — Venue listings beat, v1 (ZACH only)

Resumable ledger for [`BUILD-PROMPTS.md`](BUILD-PROMPTS.md). Committed to the branch so it rides
along with each per-step commit.

**Resume rule:** read this file, reconcile against `git log`, skip every `done` step, continue
from the first `todo` or `blocked`. If this file and git disagree, **trust the working tree and
git log**, repair this file, and say so.

- **Branch:** `feature/venue-listings-beat`, cut from `dev` (`71d4846`)
- **Baseline:** 498 tests green on `dev`
- **Verify command:** `cd forecaster; uv run pytest -q`
- **Scope:** v1 only — FR-42 … FR-46. FR-47 (Bass via Ticketmaster) is `[Later]`, gated on the
  developer account (signup failed 2026-08-16); no stub.

## Environment deviations from the skill's defaults

- No `scripts/new-worktree.mjs` in this repo (that helper is Scout's). Build in an isolated
  worktree off `dev` per repo convention.
- No `scripts/check-protected-paths.mjs`. The equivalent gates are the `ast`/guard tests named in
  BUILD-PROMPTS' environment block — **none may be edited to force a green run**.
  `test_time_scoped_items.py`'s coverage test fires when the beat registers; Step 42 satisfies it
  with real fixtures. `synthesizer.py` may be edited **only** in Step 43, as dedup machinery.

## Steps

> **SHA convention:** a step's commit SHA is written in during the *next* step's commit, since a
> commit cannot contain its own hash. If the last row shows `done` with no SHA, it is the tip
> commit — read it from `git log`.

| # | Step | Status | Commit | Notes |
|---|---|---|---|---|
| 40 | `[venues]` config + `[retrieval] exempt_beats` | todo | — | |
| 41 | ZACH parser + captured fixtures | todo | — | |
| 42 | `VenueListingsBeat`: window, items, quiet vs broken | todo | — | |
| 43 | Dedup opt-out (`exempt_beats`), explicit and accounted | todo | — | |
| 44 | Venues metric checker + CLI | todo | — | |

## Log

- **2026-08-16** — Ledger opened alongside BUILD-PROMPTS. Step numbering continues at 40
  (need-to-know v4 used 35–39).

## Blockers surfaced

_None yet._

## Bugs found and fixed during the build

_None yet._

## For HUMAN-TODO

Nothing new anticipated for v1 (ZACH is keyless). The Ticketmaster signup retry (gates FR-47
only) is already tracked. Step 41's live fixture capture needs network once, outside the suite.

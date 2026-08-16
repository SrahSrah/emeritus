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
| 40 | `[venues]` config + `[retrieval] exempt_beats` | **done** | `d50d9f7` | 504 tests (+6; earlier note said 505 — miscount, corrected). `[venues]` optional per the house contract; `kind` deliberately not validated against a registry (config stays ignorant of code). `exempt_beats` on RetrievalConfig, default []; ships ["venues"]. `venues = false` until Step 42. VENUES_CONFIG helper deliberately excludes the exemption so the un-exempt path stays testable. |
| 41 | ZACH parser + captured fixtures | **done** | `e8b7773` | 523 tests (+19). Live capture 2026-08-16: 11 productions, `id="onstage"` landmark, cards with h3/strong/href. Real variety handled: en-dashes, NBSPs, cross-year ranges, year-inheriting starts (incl. the December→January back-up rule), day-only second halves, all-caps months, a title containing "|" (so nothing splits on it). Two hand-derived fixtures documented in the fixtures README. `follow_redirects=False` — the session-bounce gotcha surfaces as HTTP 301 instead of being chased. |
| 42 | `VenueListingsBeat`: window, items, quiet vs broken | **done** | `80256e4` | 536 tests (+13). Deviation from the PRD's sample rendering, for a stronger reason: the digest quotes the venue's OWN dates text verbatim instead of a paraphrase, making the FR-11 support check exact (and a tampered-date test proves it has teeth). NOW pinned to the capture evening: exactly Sally & Tom + Come From Away in-window. Unknown kind = named runtime failure. Seam clean. |
| 43 | Dedup opt-out (`exempt_beats`), explicit and accounted | **done** | `b4a4406` | 540 tests (+4). Bypass sits before retrieval: zero ledger queries, zero same-run comparisons, zero model calls for exempt items — the CountingRetriever double fails the test by being useful. Exempt items never join the same-run pool. Contrast test: without the config line, the identical items suppress. Every existing dedup/FR-19 suite untouched. |
| 44 | Venues metric checker + CLI | **done** | — | 548 tests (+8). Condition (b) also fails when a repeat lacks its dedup_exempt record — a repeat must be deliberate on the record, not a dedup outage that happens to repeat. Verified against real data/runs: n/a, the beat has never run live. |

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

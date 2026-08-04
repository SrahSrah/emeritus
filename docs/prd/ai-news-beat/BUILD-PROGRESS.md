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
| 24 | News config schema | **done** | `5f1ed7b` | 289 tests (+18). `[news]` is **optional** — every pre-news config (including `tests/helpers.BASE_CONFIG`) is still valid; enabling the beat without the section is what raises. `[beats] news = false` until Step 32. |
| 25 | RSS/Atom feed adapter | **done** | `f62bff4` | 303 tests (+14). Stdlib `xml.etree`, no `feedparser`. Real fixtures captured: Ars = RSS 2.0/20 items, Verge = Atom/10 entries. `within_window` lives here so FR-21 can filter before fetching. |
| 26 | Article body fetch and extraction | **done** | `fb2051d` | 321 tests (+18). Hand-rolled extractor (see deviation below). Real article fixture extracts to 3,673 chars / 15 paragraphs. Unreachable `robots.txt` disallows per RFC 9309. |
| 27 | Paragraph-aware chunking | **done** | `09093de` | 340 tests (+19). `reconstruct()` shipped in the module, not just the tests — it *is* the definition of correct chunking. Paragraph spans tile the body contiguously so no character can be lost. |
| 28 | Article chunk corpus | **done** | `1919b26` | 347 tests (+7). `create_vector_schema`/`index_item` parameterized by table; `similarity_from_distance` extracted so there is exactly one of it. AST guard asserts `corpus.py` never opens the ledger in live code. |
| 29 | Topic-query retrieval | **done** | `42925f8` | 358 tests (+11). Found and fixed a real bug while writing it: `published` was stored in whatever offset the feed gave, and FR-24 compares those **as strings** in SQL. Now normalized to UTC on write. |
| 30 | Grounded-text provenance check | **done** | `da1d098` | 369 tests (+11). Added `ungrounded_item` beyond the spec's two kinds — a synthesized item pointing at no observation is the emptiest version of the failure. Word-form mapping is closed at 20. |
| 31 | Grounded-value suppression veto | **done** | `e35e098` | 385 tests (+16). Built **stronger than specced** — see the deviation below; PRD FR-27 amended to match. `test_time_scoped_items.py` gains a coverage test that fails when a registered beat is not exercised there. |
| 32 | News beat worker | **done** | `351ab05` | 398 tests (+13). `BeatContext` gains `embedder`, `corpus`, **and `agent_client`** (the PRD anticipated the first two). Seam verified: `git diff dev...HEAD` touches none of `planner.py`, `synthesizer.py`, `delivery/`. Step 31's coverage test fired on cue and forced the news case into the time-scoped guard. |
| 33 | Per-source failure handling | **done** | `952754b` | 405 tests (+7). Fixed two bugs Step 32 left: "all sources failed" was tested as "no entries" (a quiet night misread as an outage), and a cold corpus raised instead of returning empty. Failed-source lines are **status** items with a date, so FR-19's original invariant makes them unsuppressible. |
| 34 | News-beat metric checker | **done** | — | 419 tests (+14). `--news-metric` verified against the real `data/runs/`. Condition (d) reports **n/a** rather than passing when retrieval was off — a run that assessed nothing proves nothing. |

## Log

- **2026-08-04** — Ledger opened. Branch renamed from `claude/ai-news-beat-rag-spec-4cc1b9` to
  `feature/ai-news-beat`; the PRD (`ac7c98f`) and BUILD-PROMPTS (`75b6bb8`) commits are already on it.

## Deviations from the build prompts

**Step 26 — extractor: hand-rolled, not `trafilatura`.** The prompt said prefer
`trafilatura` only if it pulls a small tree. Measured 2026-08-04: it resolves to **16
packages** — `lxml`, `lxml-html-clean`, `babel`, `pytz`, `dateparser`, `python-dateutil`,
`regex`, `tzlocal`, `courlan`, `htmldate`, `justext`, `tld`, `six`, `urllib3`,
`charset-normalizer`. That is not a small tree for one function, in a project that already
chose `model2vec` over `sentence-transformers` on exactly this reasoning. The hand-rolled
pass extracts 3,673 chars from the real fixture, inside the measured 3,233–6,838 range the
source decision was made on.

**Step 26 — the 1,108-entry case is built in code, not checked in as a fixture.** A
1,108-item XML file is roughly a megabyte of repo for a test whose entire subject is the
*count* of HTTP requests. The entries are constructed in `test_article_fetch.py`; the
assertion is unchanged.

**Step 31 — the veto short-circuits rather than coexists, which is stronger than specced.**
FR-27 was written assuming the grounded-value check would sit *beside* the typed one, which made
"news items carry no date, url, or source in `fields`" a necessity: a leaked artifact key would fire
the typed invariant every night and silently kill dedup. As built, a synthesized item never reaches
the typed comparison at all, so a stray key **cannot** disable dedup. The convention still holds and
is still asserted, but the bug class is now impossible rather than forbidden. Caught by writing a
demonstration test that asserted the weaker claim and watching it fail. PRD FR-27 amended to record
the amendment rather than quietly shipping past its own spec.

**Step 31 — `test_time_scoped_items.py` gains a coverage test, not a registry walk.** The prompt
asked for the structural assertion to be "registry-driven so it covers the news beat automatically".
A registry walk cannot actually drive a new beat, because it has no way to know that beat's fixture
routes. So the file keeps driving real beats through real fixtures and adds
`test_every_registered_beat_is_exercised_by_this_file`, which fails with an explanation the moment a
registered beat is missing from the list. Not automatic, but it cannot be forgotten either, which
was the actual goal.

**Step 26 — unreachable `robots.txt` disallows.** The prompt did not say what to do when
`robots.txt` itself 5xx's or times out. Chose disallow-and-record, per RFC 9309: "the
publisher said nothing" and "we could not find out what the publisher said" are different,
and only one of them is permission. A 404 still means no restrictions.

## Blockers surfaced

**None.** No §9 open question had to be answered to finish a step. Q2 (escalation), Q5 (dedup
thresholds), Q6 (corpus thresholds), and child Q4 (suppression resurrection) all stayed open and
constrained *how* steps were built rather than whether they could be.

## Bugs found and fixed during the build

Recorded because each one was invisible in the output and would have shipped quietly:

1. **`published` stored in the publisher's own UTC offset** (found Step 29). FR-24's window filter
   compares those as strings in SQL, so an article stamped `-05:00` sorted against one stamped
   `+00:00` by its local wall clock. Normalized to UTC on write.
2. **"All sources failed" tested as "no entries came back"** (found Step 33). Three working feeds on
   a quiet news day return nothing, and the beat would have reported an outage. Now counted against
   the configured feed list.
3. **A cold corpus raised instead of returning empty** (found Step 33). `vec_chunks` does not exist
   until something is indexed, so the first-ever run — or any genuinely quiet night — reported
   `available=False`. The beat calling itself broken when it simply had nothing to read is the exact
   confusion FR-18 exists to prevent.

## For HUMAN-TODO

Nothing new. The build surfaced no credential, signup, or account action beyond what the PRD already
flagged: ③ SMTP app password, ④ the scheduled task, Q6's thresholds, and a review of the feed list
and topic queries in `config.toml`.

**④ is the one that matters now.** §2(c) — the organic dedup evidence that retires DIVERGENCES row
4 — needs 14 consecutive nights. This build made the traffic; it cannot make the nights.

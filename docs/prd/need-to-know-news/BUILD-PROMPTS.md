# BUILD PROMPTS — Need-to-know news beat, v4 (observation increment)

Decomposes [`PRD.md`](PRD.md) **v4 only: FR-31 … FR-35**. v5 (FR-36, FR-38 … FR-41 — the bar,
watchlist, pulse line, deferral, calibration band) is **explicitly out of scope** here and gets its
own decomposition after v4 lands. FR-37 (within-run dedup) already shipped in the ai-news beat and
consumed no step numbers, so this file continues the repo ledger at **Step 35** (parent build 1–19,
FR-9b 20–22, ai-news beat 23–34).

**Driving note.** Keep [`BUILD-PROGRESS.md`](BUILD-PROGRESS.md) in this folder updated after every
step (status, commit SHA per the there-noted convention, and anything discovered), and resume from
it in a fresh session: skip `done` steps, continue from the first `todo`. If the ledger and `git
log` disagree, trust git, repair the ledger, and say so. One commit per step.

**Environment, for every step:**

- Repo: `C:\Users\Sarah\Documents\31 Emeritus`, code under `forecaster/`. Python 3.12 + `uv`.
- Verify command for every step: `cd forecaster; uv run pytest -q` — **all green before "done"**.
- Branch model: the build continues on the spec's own branch (ai-news precedent: rename
  `claude/need-to-know-news-spec-1f0dff` → `feature/need-to-know-beat` once building starts), cut
  from and PR'd into `dev` — never `main`. If `dev` has moved, rebase before Step 35.
- **No network and no model calls in the test suite.** Recorded fixtures + the socket guard
  (loopback allowed); `capture_fixture.py --raw` records XML/HTML/text; `HashingEmbedder` is the
  offline embedder and its scores do **not** match the shipped model's — construct fixture corpora
  so expectations hold under it, and assert set membership/ordering, never absolute similarity.
- **Protected gates — never edit to force green:** the FR-2 seam test
  (`tests/test_cli.py::test_adding_the_dummy_beat_required_no_edit_to_planner_synthesizer_or_delivery`),
  the synthesizer seam test in `test_synthesizer.py`, the no-identity-column guard in
  `test_ledger.py`, and `test_time_scoped_items.py`'s coverage test (it **will** fire when the new
  beat registers — Step 38 satisfies it properly, with fixtures, per its FR-27-era design).
- **Zero edits to `planner.py`, `synthesizer.py`, or `delivery/`** anywhere in v4. If a step seems
  to need one, stop and surface it — that is a spec problem, not a workaround problem.
- No secrets exist in this feature (all four feeds are keyless), so any `.env` mention in a diff is
  a mistake by definition.
- The PRD's §9 Q1 values (`floor = 0.55`, `window_days = 2`) go into config **verbatim, untuned**.
  No step measures, adjusts, or claims to have validated them.

---

### Step 35 — `[need_to_know]` config schema + corpus TTL-equality rule  (implements FR-31 config half, FR-32 validation)
**Context:** [`PRD.md`](PRD.md) FR-31/FR-32 and §6 "Config". `forecaster/forecaster/config.py`,
`forecaster/config.toml`, `forecaster/tests/test_config.py`. Mirror how `[news]` landed in Step 24:
an **optional** section — every pre-existing config (including `tests/helpers.BASE_CONFIG`) must
stay valid; enabling the beat without its section is what raises.
**Task:** Add a `need_to_know` settings model shaped like the news one **minus topics**: `feeds`
(name+url list), `user_agent`, `fetch_delay_seconds`, `timeout_seconds`, `min_body_chars`,
`chunking` (target/max/overlap chars), `corpus` (path, ttl_days), and a new `corroboration` block
(`window_days`, `floor`) — **no `min_sources`, no `watchlist`, no `bar`** (v5). Add
`[beats] need_to_know = false` and a fully populated `[need_to_know]` section to `config.toml`
using §6's four verified feeds and the §6 values (chunking and fetch settings same as `[news]`;
corpus path `data/corpus.db`, `ttl_days = 7`; corroboration `window_days = 2`, `floor = 0.55`).
Keep the flag **false until Step 38**. Then the FR-32 rule: config validation **errors** when any
two corpus blocks (`[news.corpus]`, `[need_to_know.corpus]`) resolve to the same path with unequal
`ttl_days`, with an error naming both sections; distinct paths with distinct TTLs stay valid.
**Verify:** `uv run pytest -q` green. New tests prove: a config without `[need_to_know]` loads and
every existing test passes unchanged; enabling the beat without the section raises with a message
naming it; same-path/different-TTL raises naming both sections; same-path/equal-TTL and
different-path/different-TTL both load. FR-32's acceptance clause "config naming one path with two
TTLs fails to load" is this step's check.
**Guardrails:** No beat class yet, no corpus code, no v5 keys. Don't restructure existing config
sections — additive only.

### Step 36 — Shared-corpus co-tenancy proof  (implements FR-32)
**Context:** [`PRD.md`](PRD.md) FR-32. `forecaster/forecaster/memory/corpus.py` (expected:
**no production change** — it is already path-agnostic and url-keyed) and
`forecaster/tests/test_corpus.py`. The hazards being ruled out are named in FR-32 and §8
("Shared-file purge").
**Task:** Write the tests that prove two beats can share `corpus.db` safely: (i) indexing the same
url from two different entry objects (as the two beats would on one night) leaves exactly one
`articles` row and one chunk set — the second index replaces, never duplicates; (ii) articles from
disjoint source sets coexist, and `purge_expired` with the shared TTL removes only rows older than
the cutoff regardless of which beat triggers it — a purge by one beat never touches the other's
in-TTL articles; (iii) purge is idempotent when both beats run it in one night; (iv) every existing
FR-23 test passes unchanged. Fix any real defect these tests surface (none is expected); record a
discovery in BUILD-PROGRESS if one appears.
**Verify:** `uv run pytest -q` green with the four new cases present and the FR-23 suite untouched.
FR-32's acceptance clause "both beats indexing an overlapping url leaves exactly one `articles` row"
is this step's check.
**Guardrails:** Tests first; touch `corpus.py` only if a test catches a genuine bug. No schema
change — the no-new-column discipline that Step 37 asserts starts holding here.

### Step 37 — Corroboration counter  (implements FR-33)
**Context:** [`PRD.md`](PRD.md) FR-33 — read its "first chunk, deliberately" note before designing.
`forecaster/forecaster/memory/corpus.py`, `forecaster/tests/test_corroboration.py` (new file).
Reuse `similarity_from_distance` and the existing `vec_chunks` query shape from
`retrieve_for_topic`; the counter is a sibling read, not a new store.
**Task:** A pure read function in `corpus.py` — suggested signature
`corroborating_sources(connection, url, *, sources, floor, window_days, now)` — that, for the
article at `url`: takes its **first chunk** (ordinal 0, headline-prefixed) as the probe, queries
the vector index for neighbours within `window_days` (publication window, UTC-normalized strings —
the Step 29 lesson), keeps chunks scoring at or above `floor`, restricts to the caller-supplied
`sources` list, **excludes the candidate's own source and its own url**, and returns the distinct
corroborating source names plus, per source, the contributing chunk ids and scores. Counts one
source once no matter how many of its chunks match. No identity is written anywhere — this is a
read-time relation, per parent §9 Q3.
**Verify:** `uv run pytest -q` green. Over a `HashingEmbedder`-built fixture corpus (near-identical
wording across sources so hashed scores clear a test-chosen floor — assert membership, never
absolute scores): a story carried by three configured sources yields the other-two set for each
carrier with correct contributing chunk ids; an unrelated article yields the empty set; a matching
chunk from a source **not** in `sources` contributes nothing; two matching chunks from one source
count that source once; an in-corpus but out-of-window article contributes nothing; and a
schema-guard test asserts `corpus.py`'s `SCHEMA` gained no column, table, or stored hash.
**Guardrails:** First-chunk probe only — no all-pairs comparison, no clustering, no stored
representative. The floor comes in as a parameter; nothing in this step reads config.

### Step 38 — `NeedToKnowBeat`: observation run, silence accounting, fixtures  (implements FR-31, FR-34)
**Context:** [`PRD.md`](PRD.md) FR-31/FR-34, §4, §6. New `forecaster/forecaster/beats/need_to_know.py`;
`forecaster/forecaster/beats/base.py`'s `load_builtin_beats` gains the import; `forecaster/cli.py`
(corpus + embedder wiring); `config.toml` (`need_to_know = true`); fixtures under
`forecaster/tests/fixtures/`. Model the structure on `beats/news.py` — `_collect` (per-source
failure, FR-28 pattern), `_index` (window filter **before** body fetch), but **no topics loop, no
`_write`, no `agent_client`**.
**Task:** One `Beat` class, `name = "need_to_know"`, run = purge → fetch the four configured feeds
via `feeds.fetch_feed` through the scratchpad → all-sources-down check against the **configured
feed count** (the Step 33 lesson: a quiet night is not an outage) → `feeds.fetch_article_bodies`
window-filtered → `chunk_article` + `index_article` into the shared corpus → for every in-window
article from this beat's sources, call Step 37's counter with the beat's own source names and
record one `corroboration_observed` decision carrying the count, contributing observation ids, and
the floor/window in force; a night with zero in-window candidates records exactly one
`no_candidates` decision. The returned `BeatResult` is `available=True`, `checkable_fields={}`, and
its `items` contain **only** FR-28-style dated unavailability status lines for failed sources —
never a story item, never synthesized text. Wire `cli.py` to open the corpus and pass the
already-built embedder when this beat is enabled even if `news` is not. **Capture real fixtures in
this same step** (`capture_fixture.py --raw`): all four feed XMLs (BBC World, NPR News, Al Jazeera,
Texas Tribune — §6 URLs, Texas Tribune's at its `feeds.` host after the 301), plus at least one
article page and its `robots.txt`; summary fallbacks are expected and fine (§6/§8 — short
general-news descriptions are the known skew). Satisfy `test_time_scoped_items.py`'s coverage test
properly: drive the new beat through real fixtures there; its only dated items are the
unavailability lines, which carry `as_of` like the news beat's.
**Verify:** `uv run pytest -q` green, and specifically: the FR-2 seam test passes with the beat
registered and enabled; a full fixture run yields zero non-status items, one
`corroboration_observed` per in-window candidate (or one `no_candidates` on a quiet fixture), and
`git diff` over `planner.py`, `synthesizer.py`, `delivery/` is empty; disabling
`[beats] need_to_know` returns the digest to its prior shape; a two-of-four-feeds-fail fixture
produces a digest naming both dead sources and counts computed over the two that worked; all four
failing produces the standard FR-18 unavailability result. FR-31's and FR-34's acceptance clauses
are this step's checks, verbatim.
**Guardrails:** Zero model calls — the beat must not touch `context.agent_client`; add a test
asserting it. Zero edits to `feeds.py` or the chunking code — they are reused as-is; if either
seems to need a change, stop and surface it. No v5 behavior: no gate, no judgment, no watchlist,
no pulse line.

### Step 39 — Observation metric checker + CLI  (implements FR-35)
**Context:** [`PRD.md`](PRD.md) FR-35 and §2(a)–(c). New `forecaster/forecaster/ntk_metric.py` —
follow `forecaster/forecaster/news_metric.py`'s shape end to end: `Condition` /
report dataclass, `TARGET_NIGHTS` honesty posture (**1**, with the DIVERGENCES row 9 caveat text),
and the "cannot know organic from seeded / real nights from dev reruns" caveat style.
`forecaster/cli.py` gains `--ntk-metric`; `forecaster/tests/test_ntk_metric.py`.
**Task:** Compute §2's three conditions over one or more trace files: **(a) silence is accounted**
— every run where the beat ran and was available carries ≥1 `corroboration_observed` or exactly
one `no_candidates`; a run with neither and no unavailable result fails; **(b) corroboration
provenance** — every recorded count equals the number of distinct sources among its listed
contributing observation ids and every id resolves in the same trace; **(c) evidence accumulates**
— nights with distribution records vs `TARGET_NIGHTS`, never claimed early. The report also prints
the accumulated corroboration distribution (per night: candidates, max and median count) and the
per-source `text_source` split (§8 asks for it), labeled as *evidence for Q1/Q2 tuning, not a
result*. Runs where the beat is disabled report **n/a**, not pass (the Step 34 lesson).
**Verify:** `uv run pytest -q` green. The checker passes a fixture trace set satisfying all three
conditions; returns the specific failing condition for fixture traces violating exactly (a) and
exactly (b); reports n/a for a disabled-beat trace; and `uv run python -m forecaster.cli
--ntk-metric` runs cleanly against the real `data/runs/` (expected: n/a / 0 nights — the beat has
never run live). FR-35's acceptance is this step's check.
**Guardrails:** Report-only — the checker gates nothing and never adjusts a threshold. No band
condition, no delivery conditions (§2(d)–(f) are v5). Don't refactor `news_metric.py`; a shared
helper is fine only if both files' tests stay green and the diff stays small.

---

## Withheld pending §9 — none

No v4 requirement depends on an unresolved open question. §9 Q1 (unmeasured thresholds) constrains
what may be **claimed** — steps use the config values verbatim and the metric labels its output as
evidence, not results — exactly the Q5/Q6 pattern from the ai-news build. Q2/Q3/Q4 are answered;
Q5 (resurrection) is a v5 concern.

## Explicitly out of this build

FR-36 and FR-38 … FR-41 (v5: judgment, watchlist, pulse line, deferral, band) — decomposed
separately after v4 lands. Any temptation to "just add the gate while we're in there" is the
gold-plating this file exists to prevent.

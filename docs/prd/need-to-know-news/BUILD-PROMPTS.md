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


---
---

# BUILD PROMPTS — Need-to-know news beat, v5 (the bar)

Appended 2026-08-19. Decomposes **FR-36 + FR-38 … FR-41** — the importance bar Sarah decided by
interview (PRD §9 Q2). v4 (Steps 35–39) is shipped and running; the within-run dedup prerequisite
shipped as ai-news FR-37. Steps continue the repo ledger at **Step 45** (venues v1 used 40–44).

**The gate flag — RESOLVED 2026-08-20, read the history so you don't re-litigate it.** Two live
nights at the reasoned `floor = 0.55` produced max corroboration 1 (the `min_sources = 2` gate
passed zero candidates), so a floor sweep over the live corpus was run
(`scripts/corroboration_sweep.py`, now committed) and, per Sarah's standing instruction, **the
floor was retuned to 0.35** — the first measured threshold in the project. At the shipped config
the gate now passes **~2 candidates a night**, so the judgment path is live at launch, not
watchlist-only. What survives for the build: the *numbers* are still Sarah's (§9 Q1/Q7 — measured
on three nights, not tuned on fourteen); no step may adjust `floor` or `min_sources` further; and
Step 50 still puts the nightly **gate-pass count** in the metric report — that number is how the
next retune gets its evidence. Historical nights (2026-08-16/19/20) recorded their counts at the
old floor, so their gate-pass counts read as 0 in old traces; that is correct history, not a bug.

**Environment, unchanged from v4's block** (worktree off `dev`, `uv run pytest -q` green before
done, no network/model calls in tests, protected gates, zero edits to `planner.py`/`delivery/`;
`synthesizer.py` only where a step says so). New for v5: the beat now **does** call the model in
production for items it delivers — `FakeAgentClient`/scripted clients in tests, and
`tests/test_time_scoped_items.py::_run_ntk` must switch from the exploding `_no_model` client to a
scripted passage-writing client (the `PassageClient` pattern in `test_beat_news.py`), since v5's
beat may legitimately write text.

---

### Step 45 — Bar config: `min_sources`, `[need_to_know.watchlist]`, `[need_to_know.bar]`  (implements FR-36/FR-38 config halves)
**Context:** [`PRD.md`](PRD.md) FR-36/FR-38 and §6's amended config note. `forecaster/config.py`,
`forecaster/config.toml`, `tests/helpers.py` (`NEED_TO_KNOW_CONFIG`), `tests/test_config.py`.
**Task:** Extend the `need_to_know` settings: `corroboration` gains `min_sources` (int ≥ 1);
new `watchlist` block with `terms` (non-empty strings; duplicates rejected case-insensitively);
new `bar` block with `deliver` and `exclude` (non-empty string lists — Sarah's categories are
config, not code, same reasoning as the news topics). All three **required once `[need_to_know]`
exists** — v5 makes the bar part of the beat's definition, so a section without them fails at load
naming the missing block. Ship `config.toml` with: `min_sources = 2` (alive at the measured
`floor = 0.35` — ~2 gate-passes/night; see the resolved flag above), the watchlist
seed from FR-38 (Austin, Texas, ERCOT, Austin Water, boil notice, evacuation, grid emergency),
and the §9 Q2 categories (deliver: local/personal safety for Austin and Texas; national and world
emergencies; market and economy shocks — exclude: election outcomes; deaths of public figures).
Add `need_to_know_watchlist` to `[escalation] rules`. Update `NEED_TO_KNOW_CONFIG` in helpers
with small test values.
**Verify:** `uv run pytest -q` green. New tests: missing `bar`/`watchlist`/`min_sources` each
raise naming the block; `min_sources = 0` raises; empty or duplicate watchlist terms raise; empty
`deliver` or `exclude` raises; the real `config.toml` parses with the seed values and the
escalation rule present. Every pre-v5 test that builds `[need_to_know]` updated via the helper,
not by loosening validation.
**Guardrails:** Config stays ignorant of code — no prompt text in config beyond the plain-language
category lists. Do not touch `floor` or `window_days`.

### Step 46 — Watchlist carve-out: mechanical match, bypass, deterministic escalation  (implements FR-38)
**Context:** [`PRD.md`](PRD.md) FR-38. `forecaster/beats/need_to_know.py`,
`forecaster/escalation.py` (new rule id — editable, not part of the FR-2 seam), a new
`_write`-style helper modeled on `beats/news.py` (system prompt: one or two sentences, figures
exact, name the source, quotes verbatim — copy the news beat's contract, not a paraphrase of it).
**Task:** After v4's observation pass, match each candidate's **headline + first chunk** against
`watchlist.terms`, case-insensitive, whole-word. A hit bypasses the corroboration gate and the
FR-36 judgment entirely: the item is written by the model from the candidate's own chunks
(`text_origin = "synthesized"`, chunk observations linked, **no artifact keys in `fields`** per
FR-27 — add its case to the existing conventions test), `escalation_candidate = True` with the
matched term in `escalation_reason`, and the beat's result carries it so the deterministic
`need_to_know_watchlist` rule promotes it. Trace: a `watchlist_hit` decision naming term + url.
Ledger dedup can never suppress it — FR-19 invariant 2 already guarantees that; add the test, not
new machinery.
**Verify:** `uv run pytest -q` green. Over fixtures: a story only one source carries, containing a
watchlist term, is delivered and sits at the top of the ordered digest (escalation asserted on
structure); the same story with the term absent is gated out (no model call — assert call count);
matching is whole-word ("ERCOT" hits, "supercot" does not) and case-insensitive; the item's text
passes FR-26 against its linked chunks; a scripted suppress-happy client cannot suppress it
(invariant 2 path, `forced=True`).
**Guardrails:** The carve-out is mechanical — no model classification decides safety. Escalation
stays rules-only (parent §9 Q2's open half must not leak). `synthesizer.py` untouched.

### Step 47 — The importance judgment: gate → judge → suppress-when-unsure  (implements FR-36)
**Context:** [`PRD.md`](PRD.md) FR-36 — the invariants are the requirement; read them verbatim.
`forecaster/beats/need_to_know.py`; the system prompt interpolates `bar.deliver`/`bar.exclude`
from config and states the inverted default in words ("when uncertain, PASS — repeating the
drudgery is the larger error here").
**Task:** Candidates that pass the mechanical gate (v4 corroboration count ≥ `min_sources`) and
are not watchlist hits are judged one at a time: DELIVER or PASS plus a one-sentence reason.
DELIVER → model-written item from the candidate's chunks (same helper as Step 46, same FR-27
field shape, chunk observations linked). PASS → `ntk_suppressed` decision carrying the reason.
Judgment invariants, enforced around the model: (i) watchlist hits never reach it (Step 46
already delivered them — assert call counts); (ii) a judgment **failure** degrades to **named
abstention**, never include: nothing delivers, an `ntk_judgment_unavailable` decision records the
unassessed count, and Step 48's pulse line states it in the digest (build the decision now, the
line next step); (iii) every verdict is traced. Sub-gate candidates never reach the model.
**Verify:** `uv run pytest -q` green. Fixtures with a scripted client: DELIVER yields an item
whose text passes FR-26 and whose fields pass the FR-27 conventions test; PASS yields
`ntk_suppressed` with the model's reason; a raising client yields zero deliveries plus
`ntk_judgment_unavailable` with the count; a sub-gate candidate never reaches the client (call
count); the bar lists reach the prompt from config (run twice with two configs, assert the prompt
changed); v4's observation decisions still record for every candidate — the bar sits **on top of**
observation, it does not replace it (`--ntk-metric` conditions (a)–(c) must still pass over a v5
fixture run).
**Guardrails:** Suppress-when-unsure is the *prompt's stated default*, but the mechanism never
relies on prompt obedience for safety — the carve-out and abstention are code. Do not consult the
model for anything the gate already decided.

### Step 48 — The pulse line: quiet nights and abstentions, inbox-visible  (implements FR-39)
**Context:** [`PRD.md`](PRD.md) FR-39. `forecaster/beats/need_to_know.py`. The failed-source and
venue quiet lines are the house pattern: code-assembled, dated, declared checkable.
**Task:** On any run where the beat is available and delivers zero story items, emit exactly one
code-assembled status line — "Nothing cleared the need-to-know bar tonight (N stories watched,
max corroboration M)." — with N and M copied from this run's own trace tallies, declared in
`checkable_fields` so FR-11 polices them, and `as_of` in `fields` so FR-19's date rule makes it
reframe-only. When Step 47 recorded an abstention, the line instead names it: "The need-to-know
bar couldn't be judged tonight (K candidates unassessed)." A delivering night emits no pulse line.
**Verify:** `uv run pytest -q` green. Quiet fixture → exactly one pulse item, N and M matching
the trace, provenance passing; delivering fixture → no pulse; abstention fixture → the abstention
wording with K; a prior-night near-identical pulse line reframes, never suppresses (date rule);
the digest-level FR-18 checks unchanged.
**Guardrails:** The pulse line is code-assembled — never model-written. Its numbers come from the
trace, not from re-counting at render time in a second code path.

### Step 49 — Cross-beat deferral, one-way  (implements FR-40)
**Context:** [`PRD.md`](PRD.md) FR-40. `forecaster/synthesizer.py` (**the one step allowed to
touch it**, in the dedup pass — FR-9b/FR-37/FR-44 precedent) and `forecaster/memory/dedup.py` if
needed. Read `_apply_dedup` first: FR-37's `kept_this_run` pool is same-beat by construction, and
FR-44's exempt items never join it — both properties must survive.
**Task:** A need-to-know item that cleared Step 47 is additionally assessed against the run's
already-kept items **from other beats** before delivery, by handing them to `assess_item` as
extra neighbours — one way only (no other beat ever sees ntk candidates as neighbours; exempt
beats' items are never anyone's neighbours, FR-44). A suppress verdict here is recorded as
`ntk_deferred` naming the covering beat and item, not as a plain dedup_suppress. FR-27's veto
applies unchanged: an ntk candidate carrying a figure or entity the other beat's item lacks
force-reframes and still delivers, leading with what is new — deferral means "already covered,"
and a story with uncovered facts is not covered.
**Verify:** `uv run pytest -q` green. Fixture where the news beat kept an Anthropic item and the
ntk candidate restates it with no new grounded values → `ntk_deferred` naming the news beat, no
duplicate in the digest; the same candidate with one new figure → forced reframe, delivered;
news beat disabled → the candidate is assessed against nothing and delivers (one-way coupling
optional at runtime); watchlist hits are **never** deferred (feeds §2(e)); every existing dedup,
FR-37, and FR-44 test passes untouched.
**Guardrails:** No FR-19 invariant weakened; no test edited to force green. If the implementation
wants to change `assess_item`'s signature, stop and reconsider — extra neighbours through the
existing parameter is the intended shape.

### Step 50 — Bar-phase metric: conditions (d)–(f) + the gate-pass count  (implements FR-41)
**Context:** [`PRD.md`](PRD.md) §2 (d)–(f) and FR-41. `forecaster/ntk_metric.py`,
`forecaster/tests/test_ntk_metric.py`, `forecaster/cli.py` (same `--ntk-metric` flag — one
report, both phases).
**Task:** Extend the checker: **(d) no unaccounted judgment** — every gate-passing candidate ends
in exactly one of delivered / `ntk_suppressed` / `ntk_deferred` / `ntk_judgment_unavailable`, and
the pulse line's stated counts match the tally; **(e) the carve-out held** — zero watchlist-hit
candidates suppressed or deferred, ever; a single violation fails; **(f) calibration band,
report-only** — delivering nights per rolling 14 against Sarah's 2–3 target, never pass/fail.
Add to the distribution block the **nightly gate-pass count** (candidates with count ≥
`min_sources`, read from the decisions) so the measured-dead gate is visible in every report
until Sarah tunes it. Conditions (d)/(e) are n/a on pre-v5 traces (no bar decisions present) —
the existing two live nights must not retroactively fail.
**Verify:** `uv run pytest -q` green. Fixtures: all-pass over a v5-shaped trace; one fixture per
failing condition, including a synthetic suppressed watchlist hit for (e); pre-v5 trace → (a)–(c)
computed, (d)/(e) n/a; band drift reported without failing; `uv run python -m forecaster.cli
--ntk-metric` runs cleanly against the real `data/runs/` and shows gate-pass counts of **0** for
the pre-retune nights — correct history (their counts were recorded at the old 0.55 floor), and
the report must not recompute the past under the new floor.
**Guardrails:** Report-only, never gating, never auto-tuning. Keep the row-9-posture caveat and
the "evidence, not a result" label.

---

## Withheld pending §9 — none (v5)

Q2 is answered for this beat (PRD §9 Q2, Sarah's interview). Q1/Q7 (the numbers) constrain
*claims and tuning*, not buildability — and the measured-dead-gate flag above is Q1 evidence
carried into the build, not a blocker. Q5 (suppression resurrection) remains open and out of
scope; if a step appears to need it, stop.

## Explicitly out of the v5 build

Retuning `floor` / `min_sources` (Sarah's, from the metric's evidence); any escalation judgment
beyond the deterministic watchlist rule (parent §9 Q2's open half); r/WSB; Bass.

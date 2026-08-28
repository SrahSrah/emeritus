# BUILD PROMPTS — r/WallStreetBets beat, v1 (mention volume)

Decomposes [`PRD.md`](PRD.md) **v1: FR-48 … FR-52** — one increment, no `[Later]` items. This
file continues the repo step ledger at **Step 51** (parent 1–19, FR-9b 20–22, ai-news 23–34,
need-to-know 35–39, venues 40–44, ntk-bar 45–50).

**Driving note.** Keep [`BUILD-PROGRESS.md`](BUILD-PROGRESS.md) updated after every step and
resume from it in a fresh session. If the ledger and `git log` disagree, trust git, repair the
ledger, and say so. One commit per step.

**Environment, for every step:**

- Repo: `C:\Users\Sarah\Documents\31 Emeritus`, code under `forecaster/`. Python 3.12 + `uv`.
- Verify command: `cd forecaster; uv run pytest -q` — all green before "done".
- Branch: `feature/wsb-beat`, cut from the spec branch (PR #24) + `dev` merged in, PR'd into
  `dev`. Never `main`.
- **No network and no model calls in the test suite.** The real fixture is captured once with
  `capture_fixture.py --raw` in Step 52; derived fixtures are hand-edited and recorded as such
  in `tests/fixtures/README.md`. Socket guard stays on.
- **This beat makes zero model calls in production** (FR-51). No test hands it a working agent
  client; the exploding-client pattern from `tests/test_beat_need_to_know.py::_no_model` is
  mandatory on every path.
- **Protected gates — never edit to force green:** the FR-2 seam test in `test_cli.py` (its
  name tuple *gains* `wsb` in Step 53 — that is the specced edit, not a loosening), the
  no-identity guard in `test_ledger.py`, and `test_time_scoped_items.py`'s coverage test —
  it fires the moment the beat registers; Step 53 satisfies it with real fixtures.
- Beat-seam rule: zero edits to `planner.py`, `synthesizer.py`, or `delivery/` anywhere in
  this increment. The only edit outside new files and registration points is `fetch_feed`'s
  `beat` keyword (FR-49, three lines, default `"news"`).
- **Politeness is law (§2c):** one Reddit request per run, ever, including failures. No retry
  may appear anywhere. The fixture capture in Step 52 is itself one request.
- **Never spoof.** The identifying UA (`${CONTACT_EMAIL}`-expanded, like every other beat's)
  is part of the capstone's argument. A refused fetch goes dark through FR-18.

---

### Step 51 — `[wsb]` config + the `fetch_feed` `beat` keyword (FR-48/FR-49 config halves)

`WsbConfig` in `config.py` (feed_url, user_agent, timeout_seconds, top_n, stoplist), following
the optional-section contract every beat section follows: absent is valid, enabled-without-
section raises naming the section. `user_agent` goes through `_expand_contact`. Validate
top_n ≥ 1, timeout > 0, stoplist a list of strings normalized to upper. `[beats] wsb` stays
**false** in `config.toml` this step (flip is Step 53); the `[wsb]` section lands now with the
PRD §6 sketch values. `fetch_feed` gains `beat: str = "news"` used by its drop-decision
records; existing call sites untouched. Tests: config round-trip + each validation raise +
helpers `WSB_CONFIG`/`make_config(wsb=…)` support + a drops-labeled test proving `beat="wsb"`
flows through and the default still says `"news"`.
**Done when:** suite green; enabling wsb without `[wsb]` raises; stoplist edit changes parsed
config with no code change.

### Step 52 — the real fixture + `count_mentions` (FR-48)

Capture `feed_wsb.xml` with `uv run python scripts/capture_fixture.py --raw feed_wsb.xml
"https://www.reddit.com/r/wallstreetbets/.rss"` — **one request**, recorded in
`tests/fixtures/README.md` as real. Then the pure counter in `beats/wsb.py`:
`count_mentions(entries, *, stoplist, ...) -> dict[ticker, {count, post_urls}]` + post total.
Cashtags `$` + 1–5 letters any case; bare tokens 2–5 chars all-upper whole-word; stoplist
removes; posts-mentioning (distinct entry.url), not occurrences. Acceptance tests exactly as
PRD FR-48: `$NVDA`+bare `NVDA` two posts → 2 with both urls; five-in-one-title → 1;
stoplisted → absent; `nvda` bare → absent while `$nvda` counts; 6-letter upper → absent;
two stoplists, two results, zero code edits.
**Done when:** suite green, fixture parses through the FR-20 adapter, counter is pure (no
network, no trace — tracing is the beat's job).

### Step 53 — `WsbMentionsBeat` + quiet/broken + registration (FR-49, FR-50)

`WsbMentionsBeat` (`name="wsb"`): one `fetch_feed` call (with `trace=`, `beat="wsb"`) → one
traced `wsb.count_mentions` tool call whose observation payload is the **full** count table +
`post_total` (§6 trace contract) → exactly one code-assembled item. Template per PRD FR-49,
ties alphabetical, `top_n` truncation with the same tie rule; `checkable_fields` = reported
tickers' counts + post total, linked to the count observation; `fields` carries `as_of`.
Quiet (`wsb_no_mentions`, incl. zero-entries → "(0 posts scanned)") vs broken (FR-18
unavailable, adapter called exactly once, no retry) per FR-50; `wsb_counts` decision on the
counts path. Register in `load_builtin_beats`; flip `[beats] wsb = true` in `config.toml`;
add `wsb` to `COVERED_BEATS` + its parametrized case, and to the seam test's name tuple.
Derived fixtures: zero-match, zero-entries, 429, tied counts, dropped entries — hand-edited,
recorded in `tests/fixtures/README.md`.
**Done when:** every FR-49/FR-50 acceptance bullet has a passing test; disabling the beat
restores the prior digest shape; suite green.

### Step 54 — the counts-not-picks invariant (FR-51)

Three structural tests: (i) `_no_model`-style raising client injected on every path (counts,
quiet, zero-entries, unavailable) and the beat completes; (ii) template equality — reconstruct
the expected string from the count observation payload and `assert ==` on the real fixture,
plus a proof the test bites (any appended character fails); (iii) ordering asserted on the
tied-counts fixture: count-descending, alphabetical ties, `top_n` boundary alphabetical.
**Done when:** all three pass and (ii) demonstrably fails on a mutated template.

### Step 55 — `wsb_metric.py` + `--wsb-metric` (FR-52)

House shape (`venues_metric.py` sibling): §2's three conditions over traces. (a) two-hop count
provenance — delivered checkable counts pass the final provenance verdict AND, in the count
observation, each ticker's count == len(distinct contributing urls) all resolving into the
same run's fetch observation; (b) exactly one of `wsb_counts` / `wsb_no_mentions` / FR-18
unavailable per run where the beat ran; (c) at most one fetch tool-call with a reddit.com
host per trace. n/a when the beat appears in no run; house caveat (cannot tell real nights
from dev reruns). CLI flag `--wsb-metric` in the `--venues-metric` pattern. Tests: one
all-pass trace; three traces each violating exactly one condition (orphaned count, no-state
run, two reddit fetches); one n/a trace.
**Done when:** each failure names its condition; suite green.

### Step 56 — reconcile the record

README beat table row → live. STATUS.md build-state + progress-log row. DIVERGENCES row 10
closure note — dated at this build, explicitly recording the §9 Q2 nightly-vs-"this week"
phrasing nuance (the row closes at merge; the note says so). FEATURES-TODO. BUILD-PROGRESS
final pass. No code.
**Done when:** trackers agree with the code and the row-10 note carries the Q2 nuance.

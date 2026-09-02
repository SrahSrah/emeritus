# PRD: r/WallStreetBets beat — mention volume, counted, never picked

**Project:** emeritus (capstone) · **Status:** Built (v2, 2026-08-31) · **Feature ID:** `wsb-beat` · **Target path:** `forecaster/forecaster/beats/wsb.py`

> Child of [`docs/prd/forecaster/PRD.md`](../forecaster/PRD.md). Taken FR numbers: 1–19 (parent),
> 20–30 and 37 (ai-news), 31–36 and 38–41 (need-to-know), 42–47 (venue-listings). This spec owns
> **FR-48 … FR-52**. The parent's FR-17 is amended to point here for the r/WallStreetBets beat —
> and with that, FR-17's four beats are all specced. This is the last one.

## 1. Problem & why now

Checkpoint 1 promised *"scanning r/WallStreetBets for potential stock market picks."* That
sentence cannot survive this project's honesty rules, and it does not have to: **"picks" implies a
judgment the thesis forbids** — a recommendation the model would have to originate — and it brushes
against giving investment guidance, which this project will not do in any form. The promise was
already narrowed on the record: Checkpoint 2 says *"Reddit for mention volume on r/WallStreetBets"*
and *"what r/WallStreetBets has decided to love this week"*; later checkpoints repeat the
loves-this-week phrasing. The honest beat, and the one this spec builds, is **mention-volume
reporting**: which tickers the forum's hot page mentions, in how many posts, counted in code,
with every count traced to the night's one fetch. What the forum is loud about — full stop. The
beat never ranks beyond count order, never endorses, and never frames anything as a pick; that is
FR-51, machine-enforced, not a tone preference.

Why now: this is the **last unbuilt beat from Checkpoint 1**. Checkpoint 6 (submitted 2026-08-24)
lists "a r/WallStreetBets summary" in present tense among what the digest carries, recorded as
DIVERGENCES row 10 — the only Checkpoint 1 beat with no spec. This spec is the first half of
closing that row; the build increment is the second.

**Shape:** this is a **structured beat**, venues-shaped, not news-shaped. Counts are computed in
code from typed feed entries, counts are the `checkable_fields`, and the item text is a template.
No corpus, no chunking, no retrieval, **zero model calls** — the strongest possible form of the
counts-not-judgments line, because there is no model in the loop to editorialize.

## 2. Goal & success metric

- **Goal:** Every night, one digest item reporting which configured-pattern tickers appear on
  r/wallstreetbets' hot page and in how many posts, with every count traceable through the
  counter's recorded output to that run's single feed fetch — and a night where nothing matches,
  or the fetch is refused, says so explicitly and distinguishably.

- **Success metric.** Three conditions, computable from `data/runs/*.jsonl` alone. Parent §2(a)
  holds unchanged. (Runs "where the beat ran" are identified by a `wsb` beat-result record in
  the trace, the `venues_metric.py` proxy — config is not in the trace.)
  - **(a) Count provenance, both hops.** Hop one: every delivered per-ticker count and the post
    total are declared in `checkable_fields` and match the count observation they link to —
    enforced nightly by the existing FR-11 support check, zero violations. Hop two: in the count
    observation, every ticker's contributing post urls resolve to entries in the same run's
    fetch observation, and each count equals the number of distinct contributing urls. Zero
    orphans, zero counts from anywhere but tonight's fetch.
  - **(b) Quiet is not broken.** Every run where the beat ran records exactly one of: a
    `wsb_counts` decision (≥1 ticker matched), a `wsb_no_mentions` decision (feed parsed, zero
    matches — including the parsed-to-zero-entries case), or the FR-18 `unavailable` shape
    (fetch refused or unparseable). No third state, no silent night.
  - **(c) Politeness held.** At most **one** fetch tool-call whose url argument's host ends in
    `reddit.com` per run, ever — including runs that got a 429. A second such call in one trace
    fails the metric. This is the no-retry-storm rule made machine-checkable.

Deliberately **not** a metric: anything about whether the mentioned tickers matter, moved, or
were "right." The beat has no opinion, so nothing measures the quality of an opinion.

## 3. Users & job-to-be-done

One user: Sarah. The job: "tell me what r/WallStreetBets is loud about tonight, without me ever
opening Reddit." The capstone job underneath: demonstrate that a beat whose subject is the
stock market can ship inside a no-fabrication, no-advice frame — by making the only claim it
emits a count.

## 4. Scope

**In scope (v1):**

- One `Beat` implementation plus one config entry (`[beats] wsb`, `[wsb]` section). Zero edits to
  `planner.py`, `synthesizer.py`, or `delivery/`.
- One fetch per night of `https://www.reddit.com/r/wallstreetbets/.rss` through the shipped FR-20
  feed adapter — it already parses Atom (Reddit's shape), strips markup from summaries, and
  raises `AdapterError` on any ≥400 — plus **one small amendment to it**: `fetch_feed`'s
  dropped-entry decisions currently hardcode `beat="news"`; it gains a `beat` keyword
  (default `"news"`, existing call sites untouched) so this beat's drop records are labeled
  honestly rather than mislabeled or silenced (FR-49).
- A ticker-mention counter over post headlines + summaries: **cashtags only** since
  2026-08-31 (originally cashtags plus bare uppercase tokens per the 2026-08-24 interview;
  narrowed by Sarah on the first live night's measured false positives — FR-48 amendment),
  minus a config-owned stoplist. Counts are posts-mentioning, not occurrences. The counter is **traced as a tool call** with its own
  observation, so the delivered counts have a payload for FR-11 to check them against (FR-48).
- One code-assembled digest item per night from a fixed template, counts and tickers as
  `checkable_fields`, `as_of`-dated.
- Quiet-vs-broken distinguished structurally, failure via the FR-18/FR-28 pattern (FR-50).
- A metric checker in the house shape (`wsb_metric.py`, `--wsb-metric`) (FR-52).

**Out of scope / non-goals:**

- **Picks, sentiment, rankings beyond count order, or commentary of any kind.** Not a beat
  feature deferred to later — a standing prohibition (FR-51). No later increment may add "the
  forum is bullish on X" without violating this spec.
- **Comment-level counting.** Most ticker chatter lives in comments, which the feed does not
  carry. Reaching them means Reddit's OAuth API: free tier, but keyed plus an account signup —
  a break with the free-and-keyless standing rule. Not proposed; if it is ever wanted, it is a
  raise-first decision and Sarah's signup, in the FR-47 keyed-dependency pattern.
- **Weekly accumulation.** Sarah chose the nightly shape (2026-08-24): fetch hot nightly, report
  nightly, no cross-night tally store. The checkpoints' "this week" phrasing therefore stays
  slightly ahead of the build — see §9 Q2.
- **The JSON endpoints, old.reddit, or any spoofing past the 403.** Measured refusals are the
  boundary. The identifying UA is part of the capstone's argument.
- **A second subreddit.** `feed_url` is config, so the capability is latent, but nothing is
  specced or tested beyond r/wallstreetbets.

## 5. Functional requirements

- **FR-48 — Ticker mention counter (cashtag-only + stoplist, config-owned, traced)** `[MVP]`
  - **Amended 2026-08-31 — bare-token matching removed, on measured evidence.** The first
    live night (run `20260831T192534`) reported five tickers: EV, GPU, AGI, API, CI —
    every one an acronym, zero real tickers, exactly the §8 minefield firing on contact.
    Sarah's call the same day: **count cashtags only** (`$` + 1–5 letters; the forum's own
    shorthand), with the stoplist retained and still applied to cashtags. The five
    measured false positives joined the config stoplist as its first measured entries.
    What this costs is recall — posters often omit the `$` — which is the correct side to
    err on for this beat and stays tracked under §9 Q1. The bare-token clause below is
    preserved for the record and is **no longer in force**; the acceptance criteria are
    superseded where they exercised bare tokens (bare `NVDA` now yields no entry, and a
    regression test asserts the five live false positives never match again).
  - **Requirement:** A pure function (in `beats/wsb.py` — no new tool module; the input is
    already-typed `FeedEntry` objects, not a network resource) that, given the night's entries
    and the `[wsb]` settings, returns per-ticker mention data: for each matched ticker, the
    count of **distinct posts** mentioning it and the contributing posts' urls ("post" is
    identified by `entry.url` throughout this spec — `FeedEntry` has no separate id field).
    Matching runs over each entry's headline and summary (both already plain text out of the
    adapter — no second markup strip):
    - **Cashtags:** `$` followed by 1–5 letters, any case, normalized to upper. `$tsla` counts.
    - **Bare tokens:** 2–5 character all-uppercase words, matched as whole words. Single letters
      are cashtag-only (bare `F` would count every sentence containing "F").
    - **Stoplist:** `[wsb] stoplist` removes forum vocabulary that collides with real tickers
      (`DD`, `YOLO`, `CEO`, `AI`, …). Config-owned like the watchlist and the news topics —
      vocabulary is taste, and Sarah edits it without a code change.
    A ticker mentioned five times in one title counts once for that post: posts-mentioning is
    the honest unit when snippet lengths vary this much. The beat traces the counter as a tool
    call (adapter name `wsb.count_mentions`) whose observation payload is the **full** count
    table — every matched ticker with its count and contributing urls, plus the post total —
    per the §6 trace contract. Tracing a deterministic code step as a tool call is the point,
    not a trick: it gives the delivered counts a recorded observation for FR-11 to check them
    against, and gives FR-52 the payload for the second provenance hop. **The pattern's
    precision is reasoned, not measured** (§9 Q1); every match is post-attributed in that
    payload, so false positives are auditable rather than invisible.
  - **Acceptance:** Done when, over a constructed entry set: `$NVDA` and bare `NVDA` in two
    different posts yield count 2 with both urls; five occurrences in one title yield count 1;
    a stoplisted token yields no entry; a lowercase bare token (`nvda`) yields no entry while
    `$nvda` counts; a 6-letter uppercase token yields no entry; and changing the config stoplist
    changes the result with no code edit, proven by running twice with two settings.
  - **Touches:** `forecaster/beats/wsb.py`, `forecaster/config.py`

- **FR-49 — WSB beat worker and nightly item** `[MVP]`
  - **Requirement:** One `Beat` implementation, `WsbMentionsBeat` (`name = "wsb"`), registered by
    `[beats] wsb = true` plus a `[wsb]` section: `feed_url`, `user_agent`, `timeout_seconds`,
    `top_n` (tickers reported, default 5), `stoplist`. The run is: **one** `fetch_feed` call
    (FR-20) → count (FR-48) → emit **one** code-assembled item. The fetch passes the beat's
    trace and `beat="wsb"` — the one-line adapter amendment from §4, so dropped entries (no
    url, no date) are recorded against the right beat instead of mislabeled or silenced; the
    post total counts only surviving entries. Item template, ties broken alphabetically for
    determinism, truncated to the top `top_n` by count with the same tie rule at the boundary:
    *"On r/wallstreetbets' hot page tonight (25 posts): NVDA mentioned in 6 posts, TSLA in 4,
    GME in 2. https://www.reddit.com/r/wallstreetbets/"*
    `checkable_fields` carries each **reported** ticker's count and the post total, linked to
    the FR-48 count observation — the reported slice only, because FR-11 checks declared values
    against linked payloads and every declared value must appear in the delivered text; the
    full table lives in the count observation, where FR-52's hop two audits it.
    `fields` carries `as_of`, so the item is time-scoped under FR-19's date rule
    (`test_time_scoped_items` — reframe-only, never suppressed; its closed `COVERED_BEATS`
    registry and the FR-2 seam test's module-name tuple both gain `wsb`, listed in Touches
    because both tests fail the moment the beat registers otherwise). Registration follows the
    house pattern: `load_builtin_beats()` in `beats/base.py` imports the module. No
    `agent_client`, no corpus, no embedder.
  - **Acceptance:** Done when the FR-2 seam test
    (`test_adding_the_dummy_beat_required_no_edit_to_planner_synthesizer_or_delivery`, its name
    tuple extended with `wsb`) passes with the beat registered and enabled; the real captured
    fixture produces exactly one item whose every `checkable_fields` value appears in the text
    and passes the FR-11 support check against the count observation; a fixture with 3 matches
    and `top_n = 5` reports all 3; a fixture with a tie straddling the `top_n` boundary
    truncates alphabetically and deterministically; a fixture with dropped entries records
    `feed_entry_dropped` decisions labeled `beat="wsb"` and a post total counting only
    survivors; existing `[news]` fixtures still record their drops as `beat="news"`; disabling
    `[beats] wsb` returns the digest to its prior shape; and the fixture is captured with
    `capture_fixture.py --raw` in the same change, per the repo rule.
  - **Touches:** `forecaster/beats/wsb.py`, `forecaster/beats/base.py` (`load_builtin_beats`),
    `forecaster/tools/feeds.py` (the `beat` keyword, default `"news"`),
    `forecaster/config.py`, `config.toml`, `tests/test_time_scoped_items.py` (`COVERED_BEATS`
    + the per-beat case), `tests/test_cli.py` (seam-test name tuple), `tests/fixtures/`

- **FR-50 — Quiet night vs broken fetch** `[MVP]`
  - **Requirement:** The two must never collapse, and no third state may exist. **Quiet:** the
    feed fetched and parsed but zero tickers matched — including the degenerate
    parsed-to-zero-entries case (valid Atom, no `<entry>`; possible during a Reddit format
    change) — yields one code-assembled, `as_of`-dated line: *"No ticker mentions counted on
    r/wallstreetbets' hot page tonight (N posts scanned)."* with N the surviving-entry total
    (0 is honest and stays visible), and a `wsb_no_mentions` decision. **Broken:** any fetch
    failure — timeout, ≥400 including the measured 429, unparseable XML — takes the FR-18 path:
    an unavailable `BeatResult` carrying the error, an explicit "couldn't read r/wallstreetbets
    tonight" line in the digest, and **no retry, ever** (measured: a second request 12 s after
    the first drew a 429; the politeness budget is one request per night, and a refused night
    is an honest-failure night).
  - **Acceptance:** Done when a zero-match fixture yields exactly the quiet line with its N and
    a `wsb_no_mentions` decision; a zero-entries fixture yields the quiet line with "(0 posts
    scanned)"; a 429 fixture yields the FR-18 unavailable shape, the outage line, and the feed
    adapter called **exactly once** (asserted on call count); and no fixture path can produce
    both a quiet line and an outage line in one run.
  - **Touches:** `forecaster/beats/wsb.py`

- **FR-51 — Counts-not-picks invariant, machine-enforced** `[MVP]`
  - **Requirement:** The beat must be structurally incapable of producing a pick. Three
    enforced properties: (i) the beat never requests or receives an `agent_client` — in tests,
    a client that raises on contact is injected and the beat completes anyway (the ntk-v4
    pattern); (ii) every item text is **exactly** a render of the fixed templates over counted
    values — asserted by reconstructing the expected string from the count observation and
    comparing equal, so no code path can append commentary unnoticed; (iii) the only ordering
    anywhere is count-descending with alphabetical ties — no weighting, no selection beyond
    `top_n`. This is the FR-44 move (a posture made auditable) applied to this beat's defining
    risk: with these three properties, "the digest recommended a stock" is not a bug that can
    be introduced quietly — it fails a test.
  - **Acceptance:** Done when a raising fake client proves zero model calls on every fixture
    path (counts, quiet, unavailable); the template-equality test passes on the real fixture
    and fails if any character is appended to the item text; and ordering is asserted on a
    fixture with tied counts.
  - **Touches:** `forecaster/beats/wsb.py`, `forecaster/tests/`

- **FR-52 — WSB metric checker** `[MVP]`
  - **Requirement:** §2's three conditions over trace files, in the `ntk_metric.py` /
    `venues_metric.py` shape, plus a CLI flag (`--wsb-metric`). Beat-ran detection by beat-result
    record (the `venues_metric.py` proxy); Reddit-host detection by the host of the fetch
    tool-call's url argument (per the §6 trace contract). Reports n/a when the beat appears in
    no run, and carries the house caveat posture (it cannot tell real nights from dev reruns).
    Condition (c) — one fetch per run, even on failure — is the condition this beat adds to the
    project: it is the first beat whose *source* enforces a budget the metric must prove we
    honored.
  - **Acceptance:** Done when the checker passes a fixture trace satisfying all three
    conditions; returns the specific failing condition for three traces each violating exactly
    one (a count not matching its contributing urls, a run with neither decision nor
    unavailability, a run with two Reddit-host fetches); and reports n/a for a trace with the
    beat disabled.
  - **Touches:** `forecaster/wsb_metric.py`, `forecaster/cli.py`

## 6. Technical & data notes

- **Measurements** (repo `httpx` client, identifying UA — 2026-08-16 sweep, re-verified
  2026-08-24 at spec time):

  | Endpoint | Result |
  |---|---|
  | `r/wallstreetbets/.rss` | **200**, valid Atom, 25 entries (hot listing), titles + HTML content snippets, **no comments** |
  | `r/wallstreetbets/top/.rss?t=week` | **429** at 12 s spacing; **200, 25 entries** at ~5 min spacing (2026-08-24) — works, unused (nightly-hot chosen) |
  | `hot.json`, `top.json`, old.reddit | **403** — no keyless JSON path |
  | Second `.rss` request, 12 s after the first | **429** — the real limit is far stricter than our 1 s politeness delay |
  | `reddit.com/robots.txt` | **200**: `User-agent: * Disallow: /` (with a Public Content Policy preamble) |

- **The robots call, made explicitly (Sarah, 2026-08-24 interview):** the beat fetches the feed
  on the FR-20 precedent — no feed fetch in this repo is robots-gated, because a published feed
  is a syndication offer, and Reddit's own server enforces its access policy per-endpoint: 403
  to the JSON, 200 to the feed, against the same honest UA. The blanket `Disallow: /` is
  recorded here verbatim rather than glossed. The posture stays never-spoof: if Reddit ever
  403s the feed, the beat goes dark through FR-18 and stays dark — resolution would be a
  checkpoint revision or the keyed OAuth path (raise-first), never a disguised client.
- **Trace contract** (what FR-49/FR-52 assume, pinned so the metric is computable): the fetch
  `tool_call` record's arguments include the feed `url` (host detection for metric (c)); the
  fetch observation payload carries the surviving entries with at minimum `url`, `headline`,
  `summary` per entry; the `wsb.count_mentions` observation payload carries the full count
  table — `{ticker: {count, post_urls}}` — plus `post_total`; the `wsb_counts` /
  `wsb_no_mentions` decision summarizes (tickers matched, post total) and points at that
  observation. Delivered `checkable_fields` link to the count observation (hop one); the count
  observation's urls resolve against the fetch observation (hop two, FR-52's job).
- **Feed content:** entry titles plus HTML `content` snippets — already markup-stripped into
  `FeedEntry.summary` by the adapter. Flair (DD/YOLO/Gain tags) arrives inline in the title
  text where it appears at all — another reason the stoplist exists.
- **Config sketch:** `[beats] wsb = true`; `[wsb]` with
  `feed_url = "https://www.reddit.com/r/wallstreetbets/.rss"`, `user_agent` (the standard
  identifying string), `timeout_seconds = 15`, `top_n = 5`, and `stoplist` seeded with forum
  vocabulary that is also a plausible ticker or acronym — starting set: `DD, YOLO, CEO, AI,
  ATH, WSB, IPO, FOMO, GDP, CPI, FED, EPS, ITM, OTM, USD, ETF, IMO, LOL, TLDR, EDIT` — Sarah's
  to grow, like the watchlist (every seed is reasoned, none measured; §9 Q1).
- **Dedup posture:** the standard path, **not** a venues-style exemption. The item is a
  recurring status item with `as_of` in `fields`, so FR-19's date rule already makes it
  reframe-only; counts differ nightly anyway. Nothing new touches the dedup machinery.
- **Dependencies unchanged except one keyword.** `fetch_feed` gains `beat` (default `"news"`)
  so drop decisions label honestly — a three-line amendment with existing call sites untouched,
  and the only edit outside new files and registration points. Counting is stdlib regex; no
  model, no embedder, no corpus. The suite needs no `FakeAgentClient` beyond FR-51's
  raising-client guard.
- **Testing:** the real `.rss` fixture captured with `capture_fixture.py --raw` in the same
  change; derived fixtures (zero-match, zero-entries, tied counts, dropped entries) are
  hand-edited and say so in `tests/fixtures/README.md`, per the house convention. Socket guard
  stays on.

## 7. Dependencies

- The shipped FR-20 feed adapter — already in `dev`; one keyword added, no behavior change for
  existing callers (§6).
- Nothing else: no key, no signup, no new package.

## 8. Risks & edge cases

- **All-caps titles were this extractor's minefield — and it fired on night one.** As
  originally shipped, bare 2–5 letter uppercase words counted, and the first live line was
  five acronyms and zero tickers (EV, GPU, AGI, API, CI). Resolved 2026-08-31 by the FR-48
  amendment: cashtag-only matching. The residual risk inverts to **recall**: a night where
  every poster writes "NVDA calls" with no `$` produces the quiet line, not a count — honest,
  visible, and the reason no checkpoint may present the counts as complete (§9 Q1). Still
  rejected: an exchange-listed ticker allowlist — it converts false positives into silent
  false *negatives* (the new meme ticker not on the list), and invisible errors are the kind
  this project forbids.
- **The rate limit is the outage mode.** One fetch per night at ~24 h spacing should hold (the
  same UA fetched clean on probes days apart); but Reddit throttles aggressively and without
  notice. A 429 night is an honest-failure night: one FR-18 line, no retry, no cached
  substitute. Metric (c) exists so a retry can never creep in as a "fix."
- **Reddit can close the feed door any day.** They closed the JSON one. If the feed 403s
  permanently, this beat's honest end state is dark-with-a-named-reason, and the checkpoint
  story becomes "the source withdrew consent" — which is a *good* safety-chapter example, not a
  failure of the spec. No fallback scraping.
- **A hot page is not "this week."** The nightly item reports one evening's hot listing.
  Checkpoints 2/3/5 say "loves this week"; a close reader could take nightly counts as weekly
  ones. The template says "tonight" explicitly, and §9 Q2 tracks the phrasing debt — no
  checkpoint may describe the shipped counts as weekly.
- **Financial-adjacency.** Even counts can be read as signal by a motivated reader. The
  template carries no prices, no returns, no "up/down," no verbs of motion — tickers and post
  counts only. FR-51 makes the constraint structural; this row records the *why*: the beat
  reports attention, and attention is not advice.
- **One item per night means quiet-vs-broken is the whole game.** A missing wsb line must be
  impossible: metric (b) allows no third state, same discipline as venues (c). The degenerate
  states are enumerated in FR-50 (zero matches, zero entries, refused fetch) precisely so no
  new one can appear unclassified.

## 9. Open questions

Downstream must not invent answers to these.

1. **Q1 — extractor precision is unmeasured.** The pattern, the stoplist seeds, and `top_n = 5`
   are all reasoned values validated by nothing. They join the project's reasoned-not-measured
   family (parent Q5/Q6/Q7 lineage) with the same contract: the count observation records every
   match with its posts, so precision *can* be measured from accumulated nights — spot-check
   the matches, grow the stoplist, and only then let a checkpoint characterize accuracy. Until
   then a checkpoint may say "counted," never "accurately."
   **Amended 2026-08-31 — the first measurement arrived, and it moved the design.** Live
   night one: five reported tokens, zero real tickers. Precision of the bare-token pattern
   measured 0/5 and the pattern was cut (FR-48 amendment); the five tokens are now measured
   stoplist entries. What remains open flips to the other side: cashtag-only **recall** is
   unmeasured — the fetch observation still records every entry, so bare-but-real tickers
   the counter now skips can be tallied from accumulated traces before anyone widens the
   pattern again. One night is one night: a checkpoint may say the false-positive mode was
   "observed and removed," not that the counter is now accurate.
2. **Q2 — the weekly shape is deferred, and the phrasing debt is real.** Sarah chose nightly
   hot with a nightly item (2026-08-24). The measured weekly path exists (`top/.rss?t=week`
   returns 200 under patient spacing) and a cross-night tally store was designed around and
   rejected as scope. If a later checkpoint wants the literal "what WSB loved this week," that
   is a small follow-on increment — but the *submitted* phrasing already exists, so
   `continue-capstone-build`'s conflict gate should expect to record the nightly-vs-weekly
   nuance when this ships (DIVERGENCES row 10's closure note is the natural place).
3. **Q3 — comment depth.** Titles and snippets are the tip; the chatter is in comments, behind
   keyed OAuth. Not proposed. If reach ever matters more than the keyless rule, that is Sarah's
   signup and a raise-first change in the FR-47 pattern.

## 10. Phasing

- **v1: FR-48 … FR-52.** One increment, no cuts — the beat is five small requirements, and
  removing any one of them removes either the beat (48, 49), the inbox honesty (50), the
  thesis (51), or the audit (52). No `[Later]` requirements: the OAuth and weekly paths are
  recorded as open questions, not stubs, because neither has a decision behind it.

## 12. Changelog

- **v2 — 2026-08-31:** Cashtag-only matching, Sarah's call on the first live night's
  measured evidence: the delivered line's five tickers (EV, GPU, AGI, API, CI) were all
  acronyms — the §8 minefield firing exactly as predicted, 0/5 precision on the bare-token
  pattern. Bare tokens removed from FR-48; the five false positives added to the config
  stoplist (its first measured entries); §8's minefield row closed and replaced by the
  recall risk; §9 Q1 gains the measurement and flips its open half from precision to
  recall. 623 tests green.
- **v1 built — 2026-08-28:** FR-48 … FR-52 shipped as Steps 51–56 on `feature/wsb-beat`
  (see [BUILD-PROGRESS.md](BUILD-PROGRESS.md)), 622 tests green, spec built as written —
  no FR amended during the build. Real fixture captured at build time (25 entries, one
  request). §9 unchanged: Q1 (extractor precision) remains unmeasured, Q2 (weekly shape)
  remains deferred with the phrasing nuance recorded at DIVERGENCES row 10's closure,
  Q3 (comment depth) remains not proposed.
- **v1 — 2026-08-24:** Initial PRD, from the 2026-08-16 endpoint sweep re-verified at spec
  time (new data: `top?t=week` works under patient spacing; robots.txt is now `Disallow: /`)
  and Sarah's four interview decisions of 2026-08-24: fetch on the FR-20 feed precedent with
  the robots datum recorded verbatim; post-level keyless depth; nightly hot with a nightly
  item; pattern + stoplist extraction. Checkpoint 1's "stock market picks" framing explicitly
  killed in favor of the mention-volume framing Checkpoints 2/3/5 already put on the record.
  Adversarial review folded in before first commit: the counter became a traced tool call so
  delivered counts have an observation for FR-11 to check (the two-hop provenance chain in
  §2(a)); `fetch_feed` gains a `beat` keyword so drop decisions label honestly; quiet-vs-broken
  split out as FR-50; the trace contract pinned in §6; hidden registration edits
  (`load_builtin_beats`, `COVERED_BEATS`, the seam test's name tuple) surfaced into Touches.

# PRD: Need-to-know news beat — observation first, then the bar

**Project:** emeritus (capstone) · **Status:** Draft · **Feature ID:** `need-to-know-news` · **Target path:** `forecaster/forecaster/beats/need_to_know.py`

> Child of [`docs/prd/forecaster/PRD.md`](../forecaster/PRD.md). The parent owns FR-1 … FR-19;
> [`docs/prd/ai-news-beat/PRD.md`](../ai-news-beat/PRD.md) owns FR-20 … FR-30 **and FR-37**.
> This one owns **FR-31 … FR-36 and FR-38 … FR-41**. The parent's FR-17 is amended to point here
> for this beat specifically.
>
> **Numbering note (2026-08-14):** FR-37 is the within-run dedup fix this spec's §4 declared out
> of scope and sequenced as its own increment; it shipped against the AI news beat the same day
> and is numbered there. This spec's v5 requirements were drafted hours earlier as FR-37 … FR-40
> and renumbered to FR-38 … FR-41 when the collision surfaced at rebase — the two specs were
> written concurrently in separate sessions, and the code branch merged first, so its number
> stands (commit messages are immutable; a spec is not).

## 1. Problem & why now

Checkpoint 1 promised *"summarizing any news that I 'need to know' (the bar is higher than the
daily drudgery)."* Five of the six promised beats exist or are specced; this is the sixth that has
neither. It is also the only one whose defining behaviour is **suppression**: the AI news beat
reports everything its topics retrieve, and this beat must report almost nothing, most nights.

**Why this is a beat and not three more `[[news.topics]]` entries.** The question was asked
before writing this spec, because the AI news beat already does feed discovery, article fetch,
chunking, a corpus, and topic retrieval, and its topics are pure config. Three things do not
reduce to a topic entry:

1. **Different sources.** Topics share the `[news]` feed list, which is AI trade press. This beat
   reads general news wires, and "which sources carry a story" is load-bearing for it (FR-33), not
   just a coverage choice.
2. **An inverted delivery contract.** FR-24/FR-25 emit one item per topic that retrieved
   *anything* above a similarity floor. There is no mechanism anywhere in the shipped code for
   "found plenty, delivered none of it because none of it mattered." Similarity measures
   relevance; the bar is about importance, and no config value on the existing beat expresses it.
3. **Corroboration machinery that does not exist.** Counting how many independent outlets carry
   the same story is this beat's only mechanically checkable signal, and nothing computes it.

**And the honest flip side:** the plumbing is ~90% reuse, and the one thing that makes this beat
*itself* — the bar — cannot be specced today, because deciding whether importance is judged by
rules or by a bounded model judgment is parent **§9 Q2**, which is open and is Sarah's call
(see §5 FR-36 and §9). So this increment is deliberately smaller than a delivering beat: it
**observes and measures**. It fetches, indexes, and computes corroboration counts nightly, records
them with full provenance, and delivers nothing. What it produces is the evidence that turns Q2
from a taste argument into a decision made from data — which is this project's entire thesis
applied to its own design process. When Q2 is answered, FR-36 unblocks and the beat starts
delivering; nothing built here is thrown away.

**Amended 2026-08-14, same day — Q2 is answered for this beat.** Sarah decided by structured
interview (eight decisions, recorded verbatim in §9 Q2) rather than waiting for the distribution
data: the FR-9b split transfers to importance. Mechanical gates narrow (corroboration ≥ 2
sources), a model judges, invariants bound the judgment, and the uncertainty default **inverts
from dedup's**: suppress when unsure, with a mechanical watchlist carve-out that may never be
suppressed. FR-36 is therefore no longer a placeholder — it and FR-38 … FR-41 spec the bar as
buildable v5 requirements. The observation substrate (v4) still builds first and keeps measuring:
the *mechanism* is now decided, but every number in it remains reasoned-not-measured (§9 Q1), and
FR-35's distribution is what eventually tunes them.

## 2. Goal & success metric

- **Goal:** Nightly, for every in-window story candidate from the configured general-news sources,
  a recorded corroboration count with full provenance — enough accumulated distribution evidence
  to answer "what does 'widely carried' actually look like on my sources?" before any bar is set.
  Zero new checkable claims in any digest.

- **Success metric.** Three conditions, all computable from `data/runs/*.jsonl` with no other
  input. The parent's §2(a) provenance metric continues to hold unchanged. The hard part is named
  up front: **a beat that correctly stays silent looks identical in the inbox to one that broke**,
  so no delivery-counting metric can measure this beat. All three conditions therefore measure the
  *trace accounting for silence*, not the digest.

  - **(a) Silence is accounted.** Every run in which the beat is enabled and available records
    either at least one corroboration decision or an explicit `no_candidates` decision. A run with
    neither — and no `unavailable` result — fails. This is the machine-checkable discriminator
    between "quiet" and "broken."
  - **(b) Corroboration provenance.** Every recorded count equals the number of distinct sources
    among the contributing chunk observations it lists, and every listed observation id resolves
    in the same trace. Zero orphans.
  - **(c) Evidence accumulates.** At least `TARGET_NIGHTS` nights carry distribution records.
    **Amended 2026-08-16: `TARGET_NIGHTS = 2`, Sarah's call** — two nights of distribution is her
    chosen gate before building the bar, replacing the initial one-night development concession.
    Still a divergence from the parent's fourteen, in the same posture. The original clause, for
    the record: inherits the news metric's honesty posture wholesale — initially **1**, a
    recorded development concession (DIVERGENCES row 9), and only HUMAN-TODO ④ can produce real
    nights. No checkpoint may present accumulated evidence it does not have.

Deliberately **not** a metric: anything about what *should* have cleared a bar. There is no bar
in v4. Also not a metric: the corroboration thresholds themselves — this feature generates the
evidence for setting them; it does not set them (§9 Q1).

- **Amended 2026-08-14 — v5 (the bar) adds three conditions**, same trace-only standard:
  - **(d) No unaccounted judgment.** Every candidate that reached the bar phase ends in exactly one
    recorded outcome — `delivered`, `ntk_suppressed` (with the model's stated reason),
    `ntk_deferred` (FR-40, naming the beat that carried it), or `ntk_judgment_unavailable` — and
    the pulse line's counts (FR-39) match the outcome tally. The FR-25/FR-26 attribution and
    grounded-prose conditions apply unchanged to any delivered item, since its text is
    model-written.
  - **(e) The carve-out held.** Zero watchlist-hit candidates with a `ntk_suppressed` or
    `ntk_deferred` outcome, ever. A single violation fails the metric — this is the beat's FR-19
    analogue.
  - **(f) Calibration band, report-only.** Rolling delivering-nights per 14 reported against
    Sarah's target of **2–3**. Explicitly not pass/fail: a genuinely loud or quiet fortnight is
    reality, not a bug. Drifting outside the band is the signal to retune the gate and floor from
    FR-35's distribution — with evidence, per §9 Q1.

## 3. Users & job-to-be-done

One user: Sarah. The eventual job is "interrupt me only for the rare story I would regret not
knowing." The job of the v4 increment is narrower: "measure my sources so the bar's numbers can be
tuned from evidence." The subordinate capstone job: demonstrate that when a design question is
open, the honest move is to instrument first and decide deliberately — as of 2026-08-14 the bar's
*mechanism* is decided (by interview, §9 Q2) while its *numbers* stay measurement-owned (§9 Q1),
and keeping those two apart is itself the design lesson worth writing about.

## 4. Scope

**In scope:**

- One `Beat` implementation plus one config entry, per FR-2. Zero edits to `planner.py`,
  `synthesizer.py`, or `delivery/`.
- Reuse of the shipped FR-20 feed adapter, FR-21 article fetch, and FR-22 chunking, unchanged,
  over this beat's own feed list.
- Indexing into the **shared** `corpus.db` (FR-23's file), with a config-validation rule that
  keeps the two beats' lifecycle settings from silently fighting.
- A read-time, source-scoped **corroboration counter** — a count, not a judgment, and not a
  stored identity.
- Positive trace accounting for quiet nights, and a metric checker over it.
- Per-source failure handling via the shipped FR-28 path — unavailability status lines are the
  **only** digest items this beat may produce in the v4 increment.

**In scope as of the 2026-08-14 amendment (v5 — the bar):**

- The importance judgment, FR-9b-split shape, suppress-when-unsure (FR-36).
- A config-owned watchlist whose hits bypass the gate and the judgment and escalate via a new
  deterministic FR-10 rule (FR-38) — rules-based, so escalation itself stays rules-only.
- A nightly provenance-checked pulse line on quiet nights (FR-39).
- One-way cross-beat deferral — this beat stays quiet about a story another beat already carries
  (FR-40) — and the calibration band in the metric (FR-41).
- Model calls, therefore, in v5 only. v4 still makes **zero**, and any v5 delivered item is
  model-written, so FR-26 and FR-27 engage for it unchanged.

**Out of scope / non-goals:**

- **Within-run cross-item dedup (same-beat).** FR-9b compares candidates against the *ledger*
  (previous nights) and has no concept of two items in the same run covering one story — observed
  live 2026-08-13, when two topics both wrote up the same Anthropic finding and the *model*
  patched it in prose. The fix (pass the run's already-kept items to `assess_item` as extra
  neighbours, reusing every FR-19 invariant) is a defect fix for the beat that is live *today*,
  and is **its own small increment, sequenced independently** — which **shipped later the same
  day** as the ai-news beat's **FR-37** (merged into `dev` 2026-08-14, PR #12, 455 tests green;
  hence this spec's numbering skips 37, see the header note). FR-36 and
  FR-40 build on it: same-beat within-run dedup is also what collapses five same-story articles
  into one delivered representative, so this spec adds no separate clustering mechanism and still
  stores no identity, consistent with §9 Q3's answer.
- **Answering Q2 for escalation generally.** The watchlist rule is deterministic and *consistent
  with* rules-only escalation; whether judgment ever enters escalation stays open at the parent.
- **Threshold tuning** — every number below is a reasoned starting value with a measuring
  instrument attached, not a tuned one (§9 Q1) — and **paid or key-requiring sources.**

## 5. Functional requirements

- **FR-31 — Need-to-know beat worker (observation mode)** `[MVP]`
  - **Requirement:** One `Beat` implementation, `NeedToKnowBeat` (`name = "need_to_know"`),
    registered by `[beats] need_to_know = true` plus a `[need_to_know]` section carrying its own
    `feeds`, `user_agent`, fetch settings, `chunking`, `corpus`, and `corroboration` blocks. The
    run is: purge → fetch feeds (FR-20, unchanged) → window-filter → fetch bodies (FR-21,
    unchanged) → chunk (FR-22, unchanged) → index into the shared corpus (FR-32) → corroborate
    (FR-33) → record (FR-34). The beat emits **no digest items** except FR-28-style
    source-unavailability status lines, and requests no `agent_client`.
  - **Acceptance:** Done when `tests/test_cli.py::`
    `test_adding_the_dummy_beat_required_no_edit_to_planner_synthesizer_or_delivery` still passes
    with the beat registered and enabled; a full fixture run produces a `BeatResult` with
    `available=True`, empty `checkable_fields`, and zero non-status items; disabling
    `[beats] need_to_know` returns the digest to its prior shape with no other change; and
    recorded fixtures exist for every configured feed, captured in the same change per the repo
    rule.
  - **Touches:** `forecaster/beats/need_to_know.py`, `config.toml`, `cli.py` (opens the corpus
    and passes the already-built embedder when this beat is enabled even if `news` is not — the
    same wiring FR-25 established as a non-seam edit), `tests/fixtures/`
  - **Reuse ledger, per the "every departure needs a reason" rule:** FR-20, FR-21, FR-22 reused
    as-is with zero edits (they are already parameterized by settings). FR-23's *file* is shared
    (FR-32). FR-24's topic retrieval is **not used at all** — this beat has no topics; its
    candidate set is "every in-window article from my sources," and its query shape is
    chunk-against-corpus counting (FR-33), not query-against-corpus selection. No sibling adapter,
    no forked module.

- **FR-32 — Shared corpus, without silent lifecycle fights** `[MVP]`
  - **Requirement:** The beat indexes into the same `data/corpus.db` via the shipped
    `index_article` / `purge_expired`, unchanged. Sharing is safe because articles are keyed by
    canonical url (re-index replaces) and because retrieval-side reads are already
    window-filtered; the one real hazard is lifecycle config: two config blocks naming the same
    corpus path with **different `ttl_days`** would let whichever beat runs first purge the
    other's window. Config validation therefore **errors** when `[news.corpus]` and
    `[need_to_know.corpus]` resolve to the same path with unequal `ttl_days`. Distinct paths with
    distinct TTLs remain valid — the code is path-agnostic and the split-file option stays open.
  - **Acceptance:** Done when both beats indexing an overlapping url leaves exactly one `articles`
    row and one chunk set for it; a config naming one path with two TTLs fails to load with an
    error naming both sections; distinct paths load fine; and every existing FR-23 test passes
    unchanged.
  - **Touches:** `forecaster/config.py`, `tests/test_config.py`
  - **Why shared rather than a second file:** the corpus is a disposable cache of what publishers
    said this week — document-shaped and beat-agnostic, like `ledger.db` is beat-agnostic on the
    durable side. A second file would force `BeatContext` to grow again (per-beat corpus
    connections) for no isolation the `source` column doesn't already provide, and FR-33 scopes
    every read by source anyway. What sharing costs is the TTL rule above, enforced rather than
    remembered. Overlapping urls fetched by both beats in one night cost one duplicate polite
    fetch and one replace — bounded, and visible in the trace.

- **FR-33 — Corroboration counter (a count, not a judgment)** `[MVP]`
  - **Requirement:** A function in `corpus.py` that, for a candidate article, returns the set of
    **distinct sources other than the candidate's own** that have at least one chunk within
    `corroboration.window_days` scoring at or above `corroboration.floor` cosine similarity
    against the candidate's **first chunk** (headline-prefixed lead), restricted to a caller-
    supplied source list — this beat passes its own configured feed names, so AI-trade sources in
    the shared corpus can never inflate a count. It returns the contributing chunk ids and scores,
    not just the number. No identity is stored anywhere: the count is a read-time relation,
    exactly the shape §9 Q3's answer prescribes.
  - **First chunk, deliberately:** the headline-plus-lead is the story's identity; for the many
    entries that fall back to feed summaries it is the *only* chunk; and all-pairs comparison
    would mostly match boilerplate. If the lead-only comparison under-counts in practice, the
    trace will show it — that is Q1 evidence, not a spec change.
  - **Acceptance:** Done when, over a fixture corpus built for `HashingEmbedder` (whose scores do
    not match the real model's — assert set membership, never absolute values), a story carried
    with near-identical text by three configured sources yields count 2 for each carrier, with
    the correct contributing chunk ids; an unrelated article yields 0; a same-story chunk from a
    source *not* in the supplied list contributes nothing; two chunks from one corroborating
    source count once; and a test asserts no new column, table, or stored hash was added.
  - **Touches:** `forecaster/memory/corpus.py`

- **FR-34 — Positive accounting for silence** `[MVP]`
  - **Requirement:** Silence must be provable. Every run records, per candidate article, a
    `corroboration_observed` decision carrying the count, the contributing observation ids, and
    the window and floor in force; a night with zero in-window candidates records a single
    `no_candidates` decision saying so. Feed and fetch failures take the shipped FR-28 path
    unchanged: each dead source is a `source_unavailable` decision plus a dated status item that
    the digest must name — the only lines this beat may put in a digest. Every source down is the
    existing FR-18 `unavailable` shape.
  - **Acceptance:** Done when a fixture run with candidates yields one `corroboration_observed`
    per in-window article and no digest items; a quiet fixture (feeds healthy, nothing in window)
    yields exactly one `no_candidates` and no digest items; two of four feeds failing yields a
    digest naming both, items from nobody, and counts computed over the two that worked; and all
    four feeds failing yields the standard FR-18 unavailability line.
  - **Touches:** `forecaster/beats/need_to_know.py`

- **FR-35 — Observation metric checker** `[MVP]`
  - **Requirement:** A function computing §2's three conditions over one or more traces, plus a
    CLI subcommand printing it — `forecaster/news_metric.py` is the working example and the
    report shape to follow, including its caveat posture: the checker states what it cannot know
    (real nights vs. dev reruns; `TARGET_NIGHTS` = 2 since 2026-08-16, Sarah's gate, per the
    DIVERGENCES row 9 posture) rather than implying
    it. The report also prints the accumulated corroboration distribution (counts per night,
    max, median) — the actual point of the increment — clearly labeled as *evidence for* Q1/Q2,
    not as a result.
  - **Acceptance:** Done when the checker passes over a fixture trace satisfying all three
    conditions and returns the specific failing condition for three fixture traces each violating
    exactly one; and when a trace from a run where the beat was disabled reports n/a rather than
    pass.
  - **Touches:** `forecaster/ntk_metric.py` (or a sibling module in the same shape), `forecaster/cli.py`

> **The v5 requirements below were unblocked on 2026-08-14, the day this spec first marked them
> `[Later]`.** The original FR-36 placeholder laid out the Q2 blocker and the costs of each
> uncertainty default; Sarah answered by structured interview the same day (decisions recorded in
> §9 Q2) rather than waiting for FR-35's distribution. The blocker text is preserved in git and
> summarized in §9; what follows is the buildable form. **Sequencing:** v5 builds only after v4
> *and* the within-run dedup increment have landed. *(The latter shipped the same day as the
> ai-news beat's FR-37, merged PR #12 — so v5 waits only on v4.)*

- **FR-36 — Importance judgment (the FR-9b split, transferred)** `[MVP — v5]`
  - **Requirement:** A candidate that passes the mechanical gate — corroboration count from FR-33
    at or above `corroboration.min_sources` (2) — and is not a watchlist hit (FR-38 delivers
    those without consulting anyone) is assessed by the injected agent client against Sarah's
    definition of the bar, which lives in config as two plain-language lists interpolated into
    the system prompt: `bar.deliver` (local/personal safety for Austin and Texas; national and
    world emergencies; market and economy shocks) and `bar.exclude` (election outcomes; deaths of
    public figures — **deliberate exclusions, decided 2026-08-14**, so the prompt names them
    rather than leaving them to inference). The verdict is DELIVER or PASS with a one-sentence
    reason, and the system prompt states the inverted default: **when uncertain, PASS** — for
    this beat, repeating the drudgery is the larger error, the opposite of dedup's rule.
    Invariants are enforced **around** the model, per FR-19's doctrine: (i) a watchlist hit never
    reaches this judgment; (ii) a judgment failure degrades to **named abstention, not include**
    — nothing is delivered, and the FR-39 pulse line states how many candidates went unassessed
    and why. This deliberately inverts FR-19 invariant (d): include-on-failure is safe for dedup
    (worst case, a repeat) and unsafe here (worst case, the feed Sarah quit), and what makes the
    inversion honest is that the abstention is never silent; (iii) every verdict, reason, and
    outcome is traced (§2(d)). A delivered item's text is written by the model from the
    candidate's own chunks only, declares `text_origin = "synthesized"` with topicless `fields`
    per FR-27, and links every grounding chunk observation — FR-26 and FR-27 govern it with zero
    modification.
  - **Acceptance:** Done when, over fixtures with `FakeAgentClient`: a gate-passing candidate
    judged DELIVER yields an item whose observations all resolve and whose text passes FR-26; one
    judged PASS yields an `ntk_suppressed` decision carrying the model's reason and no item; a
    candidate below the gate never reaches the client, asserted on call count; a client that
    raises yields zero delivered items, an `ntk_judgment_unavailable` decision, and a pulse line
    naming the unassessed count; and the bar lists are read from config, asserted by running the
    same fixtures under two configs and observing the prompt change.
  - **Touches:** `forecaster/beats/need_to_know.py`, `config.toml`

- **FR-38 — Watchlist carve-out (mechanical, and rules-only escalation)** `[MVP — v5]`
  - **Requirement:** `[need_to_know.watchlist] terms` is a config-owned list (seeded: Austin,
    Texas, ERCOT, Austin Water, boil notice, evacuation, grid emergency), matched
    case-insensitively as whole words against a candidate's headline and first chunk. A hit
    **bypasses the corroboration gate and the FR-36 judgment entirely** — a story only Texas
    Tribune carries still delivers — and sets `escalation_candidate = True` with a reason naming
    the matched term, promoted by a new deterministic rule id `need_to_know_watchlist` in
    `[escalation] rules`. This adds no judgment surface to escalation: the rule is as mechanical
    as `freeze_alert`, so parent §9 Q2 *for escalation* stays untouched. Ledger dedup can never
    suppress these items on later nights — FR-19 invariant 2 (escalation candidates are never
    suppressed) already guarantees it, unmodified. The item text is still model-written from
    chunks and FR-26-checked; the carve-out constrains suppression, never phrasing.
  - **Acceptance:** Done when a fixture in which only one configured source carries a
    watchlist-matching story produces a delivered, escalated item at the top of the ordered
    digest with the matched term in the trace and the bar judgment never consulted (call count
    zero for that candidate); the same story with the term absent is gated out; matching is
    case-insensitive and whole-word ("ERCOT" matches, "supercot" does not); and §2(e) passes over
    the run.
  - **Touches:** `forecaster/beats/need_to_know.py`, `forecaster/escalation.py` (a new rule id —
    editable; the FR-2 seam names `planner.py`, `synthesizer.py`, `delivery/`), `config.toml`

- **FR-39 — Quiet-night pulse line** `[MVP — v5]`
  - **Requirement:** On any run where the beat is available and delivers zero story items, it
    emits exactly one code-assembled status item: *"Nothing cleared the need-to-know bar tonight
    (N stories watched, max corroboration M)."* — with N and M copied from the run's own trace
    tallies and declared in `checkable_fields`, so FR-11's existing support check polices them;
    and with an `as_of` date in `fields`, so FR-19's date rule makes the line reframe-only, same
    as the shipped failed-source lines. When FR-36's judgment was unavailable, the line instead
    names the abstention and the unassessed count. This is what makes quiet-vs-broken
    **inbox-visible** — Checkpoint 3's own complaint: *"a beat that never went out looks, in my
    inbox, exactly like a slow night."*
  - **Acceptance:** Done when a quiet fixture yields exactly one pulse item whose N and M equal
    the trace tallies and pass provenance; a delivering fixture yields no pulse line; a
    judgment-outage fixture yields the abstention wording; and the pulse line survives a
    cosine-similar prior night's pulse line as a reframe, never a suppression.
  - **Touches:** `forecaster/beats/need_to_know.py`

- **FR-40 — Cross-beat deferral, one-way** `[MVP — v5]` — **builds on the shipped FR-37 (ai-news PRD)**
  - **Requirement:** A need-to-know candidate that cleared FR-36 is additionally assessed against
    the run's **already-kept items from other beats** before delivery, by handing them to
    `assess_item` as extra neighbours — the same-beat within-run mechanism extended, for this
    beat only and in one direction only (no other beat ever sees need-to-know candidates as
    neighbours). If the model judges it adds nothing over, say, the AI beat's Anthropic item, the
    outcome is `ntk_deferred`, and the trace decision must name the covering beat and item. Every
    FR-19/FR-27 bound applies unchanged — in particular FR-27's veto means a candidate carrying a
    figure or entity the other beat's item lacks is force-reframed and still delivers, leading
    with what is new. That is correct, not a leak: deferral means "already covered," and a story
    with uncovered facts is not covered.
  - **Acceptance:** Done when a fixture where the news beat kept an item and the need-to-know
    candidate restates it with no new grounded values yields `ntk_deferred` naming the news beat
    and no duplicate in the digest; the same candidate carrying one new figure delivers as a
    forced reframe; and a run where the news beat is disabled assesses the candidate against
    nothing and delivers it, proving the one-way coupling is optional at runtime.
  - **Touches:** `forecaster/synthesizer.py` (the FR-9b dedup pass — this is dedup-machinery
    change riding with this feature, **not** a beat-registration edit; the FR-2 seam test
    concerns adding a beat, and FR-9b/FR-11 precedent is that dedup changes touch the
    synthesizer legitimately), `forecaster/memory/dedup.py`

- **FR-41 — Bar-phase metric and calibration band** `[MVP — v5]`
  - **Requirement:** The FR-35 checker grows §2's (d), (e), and (f). The calibration band —
    delivering nights per rolling 14, target **2–3** (Sarah, 2026-08-14) — is **report-only** and
    carries the same honesty posture as `TARGET_NIGHTS`: the report states how many real nights
    back the window, and that drift outside the band is a retuning signal for
    `corroboration.min_sources` and `corroboration.floor` against FR-35's distribution, never an
    automatic adjustment.
  - **Acceptance:** Done when the checker passes a fixture trace set satisfying (d)–(f); returns
    the specific failing condition for a fixture violating each of (d) and (e); and reports —
    without failing — a fixture set whose delivery rate sits outside the band.
  - **Touches:** `forecaster/ntk_metric.py`, `forecaster/cli.py`

## 6. Technical & data notes

- **Sources — verified live 2026-08-14, all free, keyless, no signup:**

  | Feed | URL | Format | Entries | Description length |
  |---|---|---|---|---|
  | BBC News (World) | `https://feeds.bbci.co.uk/news/world/rss.xml` | RSS 2.0 | ~25 | one sentence |
  | NPR News | `https://feeds.npr.org/1001/rss.xml` | RSS 2.0 | ~10 | 1–2 sentences |
  | Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` | RSS 2.0 | ~26 | 1–2 sentences |
  | Texas Tribune | `https://feeds.texastribune.org/feeds/main/` (301 from `www.texastribune.org`) | RSS 2.0 | ~20 | 1–2 sentences |

  The Guardian's feed endpoint **blocked the spec-time fetch outright** — itself a datum: general-
  news publishers gate automated access far harder than the AI beat's trade press. AP and Reuters
  publish no open feed that could be verified at spec time and are not proposed; if Sarah wants
  either, finding a working open endpoint is a build-time task, not an assumption. The list is
  Sarah's taste, exactly like the AI beat's — HUMAN-TODO gets a review item. Texas Tribune is the
  deliberate local counterweight: "need to know" is partly "need to know *here*," and no national
  wire corroborates an Austin story.

- **Every description above is short.** Expect this beat's corpus to skew far more heavily toward
  `text_source = "summary"` one-chunk records than the AI beat's (whose bodies measured
  3,233–6,838 chars). Corroboration therefore mostly compares headline-plus-sentence against
  headline-plus-sentence. Plausibly fine — two outlets' summaries of one event share entities and
  phrasing — but **unmeasured**, which is §9 Q1 and part of why the floor must not be trusted.

- **Config:** own `[need_to_know]` section mirroring `[news]`'s shape (user agent, politeness,
  `min_body_chars`, chunking, corpus path + TTL, corroboration `window_days` and `floor`). No
  `topics` array — this beat has none. Proposed reasoned (not measured) values:
  `corroboration.window_days = 2` (a story being carried *now* is the signal; the corpus TTL is
  retention, not identity), `corroboration.floor = 0.55` — between Q5's 0.60 (delivered line vs.
  delivered line) and Q6's 0.35 (short query vs. long chunk), because same-story summaries from
  two outlets are near the line-vs-line case. Both flagged §9 Q1.
  - *v4 as originally written shipped no `min_sources` knob — nothing consumed a bar-shaped value,
    and shipping one would have been inventing the bar through config.* **Amended 2026-08-14:**
    with the bar decided, v5 adds exactly the values Sarah set, all still reasoned-not-measured:
    `corroboration.min_sources = 2` (the FR-36 gate), `[need_to_know.watchlist] terms` (seed list
    in FR-38 — Sarah's to edit, like the news topics), and `[need_to_know.bar]` `deliver` /
    `exclude` plain-language lists (her categories, in config rather than hardcoded into a prompt,
    for the same reason the topics are: taste is config, not code).

- **Embeddings:** the same injected `StaticEmbedder` instance, loaded once per run. The suite
  keeps `HashingEmbedder`, with the standing fixture-construction constraint (assert membership
  and ordering, never absolute scores).

- **Testing:** recorded fixtures for all four feeds and representative article pages, captured in
  the same change (`capture_fixture.py --raw` for XML/HTML). Socket guard stays on. No
  `FakeAgentClient` needed anywhere in this increment because nothing calls a model.

## 7. Dependencies

- The AI news beat's shipped machinery (FR-20 … FR-24), merged in `dev` at `1927802`. Nothing new
  to install: no new extraction library, no new embedder, no key, no paid tier.
- **Not a dependency of the v4 increment, but of FR-36/FR-40 — and now satisfied:** the
  within-run dedup fix shipped as the ai-news beat's FR-37, merged 2026-08-14 (same-run
  neighbours passed to `assess_item`), which should land as its own increment against the beat
  that exhibits the bug today.
- **Not blocking, but gating §2(c):** HUMAN-TODO ④. Same as every nights-based condition in this
  project — nothing has yet run unattended.

## 8. Risks & edge cases

- **Wire syndication makes corroboration structurally weak.** Ordinary syndicated stories are
  multi-source by construction, so "carried by N outlets" will fire on drudgery daily. This is
  the central honest risk: it is possible the distribution shows corroboration can *narrow* but
  never *be* the bar, making Q2 unavoidable rather than optional. The increment is designed so
  that even that outcome is a success — it would be the measured answer to "can rules alone do
  this?", which is precisely what Q2 needs to be decided well.
- **Summary-skewed corpus** (see §6): if extraction fails broadly across general-news publishers,
  corroboration runs on ~150-char texts. The `text_source` distribution is already in the trace;
  FR-35's report should surface it per source.
- **Publisher gating.** The Guardian blocked a plain fetch at spec time; others may block the
  body fetch, robots-disallow, or paywall. All degrade to summary via the shipped FR-21 fallback
  — visible, not fatal, and never invented text. `robots.txt` measurement is a build-time task
  per feed, per the AI beat's precedent, including its unreachable-robots.txt = disallow rule.
- **Shared-file purge:** whichever beat runs first purges; with the FR-32 TTL-equality rule this
  is idempotent and harmless, and a test should prove a purge by one beat never touches the
  other's in-TTL articles.
- **A beat that is dark indefinitely.** If Q2 stays open, this beat observes forever and never
  delivers. Deliberate, but it must not rot silently: revisit after 14 real nights of
  distribution evidence exist (the same milestone HUMAN-TODO ④ already gates), at which point
  Q2 is decidable from data and staying dark becomes a choice rather than a default.
- **Checkpoint language.** No checkpoint may call this a working need-to-know beat. What exists
  after this increment: the sixth beat's substrate, observing, with a designed-open bar. That is
  a strong essay *if told straight* — instrument first, decide from evidence — and a divergence
  from Checkpoint 1's promise if told loosely. the next increment's conflict gate should
  expect a DIVERGENCES row when this ships.
- **Copyright posture:** inherited unchanged from the AI beat's §8 — personal, single-inbox,
  robots-respecting, rate-limited, TTL-bounded, sources named.
- **Escalation fatigue (new with FR-38).** The watchlist rule joins `freeze_alert` and the dormant
  injury rule, and the parent's warning applies verbatim: escalating everything is the same as
  escalating nothing. An over-broad term ("Texas" alone will match constantly in a corpus that
  includes the Texas Tribune) makes the carve-out fire nightly, which floods both the top of the
  digest *and* the bar bypass. The seed list must be specific (systems and event terms, not bare
  geography), §2(e)'s tally makes fire frequency visible, and the first two weeks deserve a look.
- **The suppress-default has no backstop, by choice.** Sarah chose suppress-when-unsure knowing a
  wrongly passed story has no second channel. The watchlist bounds the worst case for the classes
  she named; for everything else, the trace records every PASS with its reason, so a miss is at
  least auditable after the fact. Named here so no later checkpoint discovers it as a surprise.
- **Judgment abstention inverts FR-19(d), deliberately.** A judgment outage suppresses rather than
  includes (FR-36 invariant ii). The inversion is safe only because it is loud — the pulse line
  names the abstention in the inbox itself. If FR-39 ever regresses to silence, this becomes the
  exact failure FR-18 exists to prevent; the §2(d) accounting is what guards that.
- **Deferral can still near-duplicate.** FR-40's FR-27 veto force-reframes a candidate carrying
  any new grounded value, so a reader may occasionally see an important story twice in different
  framings. Correct-side error, consistent with the project's stated position that repeating beats
  going quiet — recorded so it reads as designed, not broken.

## 9. Open questions

Downstream must not invent answers to these.

1. **Q1 — the numbers are unmeasured, and the interview added more of them.** `floor = 0.55` and
   `window_days = 2` are reasoned and validated by nothing — a sibling of parent Q5 and child Q6,
   a third distinct retrieval problem (same-story chunk vs. chunk, cross-outlet) with its own
   natural floor. Recorded in the parent as §9 Q7. **2026-08-14:** `min_sources = 2` and the 2–3
   nights/fortnight band join this list — they are Sarah's *targets*, chosen by interview, which
   settles what to aim at but measures nothing. FR-35's distribution and FR-41's band report are
   the instruments. No checkpoint may describe any of these as tuned.
   **Amended 2026-08-20 — the floor is now measured, and the reasoning was wrong.** Three live
   nights (162 corpus articles) plus a floor sweep with the shipped counter
   (`scripts/corroboration_sweep.py`): above 0.40 **no candidate ever reached two sources** — the
   reasoned 0.55 made the `min_sources = 2` gate structurally dead — while 0.35 yields ~2
   gate-passing candidates a night, spot-checked as genuinely co-covered stories. Sarah's standing
   instruction ("retune whatever it says") set `floor = 0.35` under the pre-stated rule (highest
   floor with 1–10 gate-passes/night). The coincidental equality with Q6's topic floor is
   measurement, not shared derivation. Status of the family: `floor` is **measured on three
   nights**; `window_days`, `min_sources`, and the band remain reasoned targets; nothing is
   fourteen-night validated, and a checkpoint may say "measured", not "tuned".
2. ~~**Parent §9 Q2 — rules vs judgment — is this beat's blocker.**~~ **Answered for this beat,
   2026-08-14, by Sarah (structured interview, eight decisions):** the FR-9b split transfers to
   importance — mechanical gates narrow, a model judges, invariants bound it. Uncertainty default:
   **suppress**, inverted from dedup, with a mechanical watchlist carve-out that may never be
   suppressed (bypass gate + judgment, escalate via a deterministic rule). Calibration target: 2–3
   delivering nights per 14. Bar categories: local/personal safety (Austin/Texas), national and
   world emergencies, market/economy shocks; **elections outcomes and major-figure deaths
   deliberately excluded**. Quiet nights get a one-line provenance-checked pulse. Overlap: this
   beat defers, one-way. — Note the scope of the answer: Q2 *for escalation generally* remains
   open at the parent; FR-38's escalation contribution is deterministic precisely so this answer
   does not leak into that one.
3. ~~**Cross-beat overlap.**~~ **Answered 2026-08-14 (same interview): need-to-know defers,
   one-way.** FR-40 specs it on top of the within-run dedup mechanism; no other beat ever treats
   this beat's candidates as neighbours.
4. ~~**A personal watchlist as a second gate.**~~ **Answered 2026-08-14 (same interview): bypass
   the bar and escalate**, as a config-owned term list and a deterministic rule. FR-38. The
   escalation-fatigue risk this creates is named in §8.
5. **Q5 (new) — how long does a suppressed story stay suppressed?** Inherited shape from the AI
   beat's §9 Q4, sharper here: a story the bar PASSes on night one may grow into need-to-know by
   night three, and ledger dedup will then see night-three coverage as near night-one's.
   Resurrection is a judgment call this spec does not make. The FR-27 veto (new figures and
   entities force delivery) is the partial mitigation already in place.

## 10. Phasing

- **v4 (first increment): FR-31 … FR-35.** Five requirements, all mechanical, zero model calls,
  zero digest content beyond FR-28 status lines. Coherent and honest on its own: the beat
  observes, accounts for its own silence, and accumulates the evidence the bar's numbers need.
  Still builds first — the bar being decided does not make the substrate skippable.
- **Sequenced separately, between v4 and v5:** the within-run dedup fix, as its own small
  increment against the live AI news beat — **done**: shipped as ai-news FR-37, merged into `dev`
  2026-08-14 (PR #12). FR-36 and FR-40 build on it, so v5 now waits only on v4.
- **v5 (the bar, unblocked 2026-08-14): FR-36 + FR-38 … FR-41.** Buildable now that §9 Q2 is answered for
  this beat. The available cut if a checkpoint deadline forces one: ship v5 **without FR-40**
  (cross-beat deferral) and accept the occasional double-coverage night, recorded as a divergence
  — FR-40 is the v5 requirement most separable from the rest. FR-38 and FR-39 are not
  cuttable: without the carve-out the suppress-default has no bound, and without the pulse line
  the abstention path (FR-36 invariant ii) is silent, which §8 names as the one configuration
  this design must never be in.
- **No smaller cut below v4:** the only smaller increment is a config edit that this spec's §1
  argues would not be the feature.

## 12. Changelog

- **v3 — 2026-08-14 (at rebase onto `dev`):** Renumbered v5 from FR-37 … FR-40 to
  **FR-38 … FR-41**: the within-run dedup fix, built concurrently in its own session, merged first
  as the ai-news beat's FR-37 (PR #12), and its commit messages fix the number. Its landing also
  satisfies v5's only external dependency, so v5 now waits only on v4. No requirement changed
  content — only numbers and dependency status.
- **v2 — 2026-08-14 (later the same day):** The bar decided. Sarah answered §9 Q2 for this beat by
  structured interview — eight decisions, recorded in §9 Q2 — and FR-36 was rewritten from a
  blocked placeholder into five buildable requirements (then numbered FR-36 … FR-40; renumbered at
  v3): the FR-9b split
  transferred with an inverted suppress-when-unsure default, a watchlist carve-out that bypasses
  and escalates via a deterministic rule, a provenance-checked quiet-night pulse line, one-way
  cross-beat deferral, and a report-only 2–3-nights-per-fortnight calibration band. Elections
  outcomes and major-figure deaths recorded as deliberate exclusions. §2 gained conditions
  (d)–(f); §8 gained the escalation-fatigue, no-backstop, abstention-inversion, and near-duplicate
  risks; §9 Q5 (suppression resurrection) added. Every new number is a target, not a measurement —
  §9 Q1 grew rather than shrank.
- **v1 — 2026-08-14:** Initial PRD. Framed as an observation increment after establishing (a) the
  beat is real — inverted delivery contract, distinct sources, corroboration machinery — and
  (b) its defining bar is unwritable without parent §9 Q2, which is surfaced, not answered.
  Sources verified live (four feeds, free and keyless; Guardian blocked the fetch; AP/Reuters
  have no verifiable open feed). Corpus decision: shared file with a TTL-equality validation
  rule. Within-run dedup declared out of scope and recommended as its own increment.

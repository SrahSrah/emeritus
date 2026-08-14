# PRD: Need-to-know news beat — observation first, the bar deferred

**Project:** emeritus (capstone) · **Status:** Draft · **Feature ID:** `need-to-know-news` · **Target path:** `forecaster/forecaster/beats/need_to_know.py`

> Child of [`docs/prd/forecaster/PRD.md`](../forecaster/PRD.md). The parent owns FR-1 … FR-19;
> [`docs/prd/ai-news-beat/PRD.md`](../ai-news-beat/PRD.md) owns FR-20 … FR-30 (FR-30 shipped
> unspecced; it is recorded in DIVERGENCES and `synthesizer.py`, and this spec does not touch it).
> This one owns **FR-31 onward**. The parent's FR-17 is amended to point here for this beat
> specifically.

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
    Inherits the news metric's honesty posture wholesale: `TARGET_NIGHTS` is currently **1**, a
    recorded development concession (DIVERGENCES row 9), and only HUMAN-TODO ④ can produce real
    nights. No checkpoint may present accumulated evidence it does not have.

Deliberately **not** a metric: anything about what *should* have cleared a bar. There is no bar.
Also not a metric: the corroboration thresholds themselves — this feature generates the evidence
for setting them; it does not set them (§9 Q1).

## 3. Users & job-to-be-done

One user: Sarah. The eventual job is "interrupt me only for the rare story I would regret not
knowing." The job of *this increment* is narrower: "measure my sources so the bar, when I set it,
is set from evidence." The subordinate capstone job: demonstrate that when a design question is
open, the honest move is to instrument first and decide second — the same posture as §9 Q5/Q6.

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
  **only** digest items this beat may produce in this increment.

**Out of scope / non-goals:**

- **The bar, and all delivery.** Blocked on parent §9 Q2. See FR-36 — written as the decision
  Sarah must make, not as a requirement anyone can build.
- **Within-run cross-item dedup.** FR-9b compares candidates against the *ledger* (previous
  nights) and has no concept of two items in the same run covering one story — observed live
  2026-08-13, when two topics both wrote up the same Anthropic finding and the *model* patched it
  in prose. This beat's overlapping feeds make that gap worse once it delivers, but the fix (pass
  the run's already-kept items to `assess_item` as extra neighbours, reusing every FR-19 invariant)
  is a defect fix for the beat that is live *today*, and coupling it to a Q2-blocked feature would
  delay it. **Decision: its own small increment, sequenced independently.** This spec's FR-36
  depends on it having landed.
- **Story clustering / grouping.** Deciding which of five same-story articles is the
  representative belongs with delivery (FR-36). The counter records per-article counts and stores
  no identity, consistent with §9 Q3's answer.
- **A personal watchlist.** Mechanically checkable, but what a match should *do* (bypass the bar?
  escalate?) is Q2-shaped. §9 Q4.
- **Model calls.** This increment makes **zero** — the whole beat is mechanical, so FR-26/FR-27
  never engage and the nightly token cost of the increment is nil.
- **Escalation, threshold tuning, paid or key-requiring sources.**

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
    (real nights vs. dev reruns; `TARGET_NIGHTS = 1` per DIVERGENCES row 9) rather than implying
    it. The report also prints the accumulated corroboration distribution (counts per night,
    max, median) — the actual point of the increment — clearly labeled as *evidence for* Q1/Q2,
    not as a result.
  - **Acceptance:** Done when the checker passes over a fixture trace satisfying all three
    conditions and returns the specific failing condition for three fixture traces each violating
    exactly one; and when a trace from a run where the beat was disabled reports n/a rather than
    pass.
  - **Touches:** `forecaster/ntk_metric.py` (or a sibling module in the same shape), `forecaster/cli.py`

- **FR-36 — The bar, and delivery** `[Later]` — **blocked on parent §9 Q2; do not build**
  - **What it will owe when unblocked:** the importance decision itself; story grouping and
    representative selection; the quiet-night digest line ("nothing cleared the bar tonight,"
    with its counts provenance-checked, so quiet-vs-broken becomes inbox-visible and not just
    trace-visible — Checkpoint 3's own words name this failure: *"a beat that never went out
    looks, in my inbox, exactly like a slow night"*); cross-beat overlap precedence with the AI
    news beat (§9 Q3); and FR-26/FR-27 engagement the moment any item text is model-written.
  - **The blocker, stated precisely:** "the bar is higher than the daily drudgery" is a judgment
    about importance. FR-9b resolved the same rules-vs-judgment tension for *dedup* by splitting
    it — retrieval narrows mechanically, a model judges, invariants bound the judgment — and that
    split is shipped, tested precedent. Whether it transfers to importance is untested and is
    Sarah's call, for a reason the dedup case did not have: dedup's uncertainty default is
    settled ("when uncertain, include — repeating is a smaller error than withholding"), and for
    importance the default *inverts and has no backstop either way*. Include-when-uncertain
    rebuilds the drudgery feed the beat exists to suppress; suppress-when-uncertain silently
    drops the one story that mattered, and with social media gone there is no second channel to
    catch it. Corroboration alone cannot substitute: wire syndication means ordinary stories are
    multi-source *by construction* (§8), so a pure count is a weak bar — how weak is exactly what
    FR-33/FR-35's distribution measures. This FR stays unbuildable until Q2 is answered; if a
    build step appears to need an answer, stop and surface it.

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
  `topics` array — this beat has none — and **no `min_sources` knob**: nothing in this increment
  consumes a bar-shaped value, and shipping one would be inventing the bar through config.
  Proposed reasoned (not measured) values: `corroboration.window_days = 2` (a story being carried
  *now* is the signal; the corpus TTL is retention, not identity), `corroboration.floor = 0.55` —
  between Q5's 0.60 (delivered line vs. delivered line) and Q6's 0.35 (short query vs. long
  chunk), because same-story summaries from two outlets are near the line-vs-line case. Both
  flagged §9 Q1.

- **Embeddings:** the same injected `StaticEmbedder` instance, loaded once per run. The suite
  keeps `HashingEmbedder`, with the standing fixture-construction constraint (assert membership
  and ordering, never absolute scores).

- **Testing:** recorded fixtures for all four feeds and representative article pages, captured in
  the same change (`capture_fixture.py --raw` for XML/HTML). Socket guard stays on. No
  `FakeAgentClient` needed anywhere in this increment because nothing calls a model.

## 7. Dependencies

- The AI news beat's shipped machinery (FR-20 … FR-24), merged in `dev` at `1927802`. Nothing new
  to install: no new extraction library, no new embedder, no key, no paid tier.
- **Not a dependency of this increment, but of FR-36:** the within-run dedup fix (same-run
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
  from Checkpoint 1's promise if told loosely. `continue-capstone-build`'s conflict gate should
  expect a DIVERGENCES row when this ships.
- **Copyright posture:** inherited unchanged from the AI beat's §8 — personal, single-inbox,
  robots-respecting, rate-limited, TTL-bounded, sources named.

## 9. Open questions

Downstream must not invent answers to these.

1. **Q1 (new) — corroboration thresholds are unmeasured.** `floor = 0.55`, `window_days = 2` are
   reasoned above and validated by nothing. A sibling of parent Q5 and child Q6 — a third,
   distinct retrieval problem (same-story chunk vs. chunk, cross-outlet) with its own natural
   floor. The distribution FR-35 accumulates is the instrument for measuring it. Recorded in the
   parent as §9 Q7. No checkpoint may describe any of the three sets as tuned.
2. **Parent §9 Q2 — rules vs judgment — is this beat's blocker, not just an inherited note.**
   FR-36 is the first requirement in the project that cannot be written at all without it. The
   costs of each answer are laid out in FR-36; the call is Sarah's.
3. **Cross-beat overlap.** An Anthropic story can legitimately clear both beats once this one
   delivers. Which beat carries it, and does the reader ever see it twice? Deferred with FR-36;
   the within-run dedup fix is the natural substrate, and extending it across beats is new
   semantics (FR-9b retrieval is same-beat by design) that should not be built speculatively.
4. **A personal watchlist as a second gate.** Entity matching is mechanical, but its *effect* is
   not: bypass-the-bar and escalate are both Q2-shaped powers. Unspecced until Q2.

## 10. Phasing

- **v4 (this increment): FR-31 … FR-35.** Five requirements, all mechanical, zero model calls,
  zero digest content beyond FR-28 status lines. Coherent and honest on its own: the beat
  observes, accounts for its own silence, and accumulates the evidence its one open design
  question needs.
- **Sequenced separately, before FR-36:** the within-run dedup fix, as its own small increment
  against the live AI news beat.
- **Later: FR-36**, unblocked only by Sarah answering parent §9 Q2 — ideally with FR-35's
  distribution in hand, which is the point of doing v4 first.
- **No cut list:** v4 is already the cut. The only smaller increment is a config edit that this
  spec's §1 argues would not be the feature.

## 12. Changelog

- **v1 — 2026-08-14:** Initial PRD. Framed as an observation increment after establishing (a) the
  beat is real — inverted delivery contract, distinct sources, corroboration machinery — and
  (b) its defining bar is unwritable without parent §9 Q2, which is surfaced, not answered.
  Sources verified live (four feeds, free and keyless; Guardian blocked the fetch; AP/Reuters
  have no verifiable open feed). Corpus decision: shared file with a TTL-equality validation
  rule. Within-run dedup declared out of scope and recommended as its own increment.

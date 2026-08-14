# PRD: AI news beat with document-shaped RAG

**Project:** emeritus (capstone) · **Status:** Draft · **Feature ID:** `ai-news-beat` · **Target path:** `forecaster/forecaster/beats/news.py`, `forecaster/forecaster/tools/feeds.py`, `forecaster/forecaster/memory/corpus.py`

> Child of [`docs/prd/forecaster/PRD.md`](../forecaster/PRD.md). That spec owns FR-1 … FR-19; this
> one owns **FR-20 onward**. The parent's FR-17 covers the remaining four beats and is amended to
> point here for the news beat specifically.

## 1. Problem & why now

Checkpoint 3 was submitted 2026-08-02 and commits, in writing, to *"Retrieval of the classic kind
arrives with the AI news beat, where the documents are articles."* That sentence is DIVERGENCES
row 6 and is what Checkpoint 4 is measured against. Nothing in the shipped code retrieves over a
document it did not write: FR-9b searches the sent-item ledger, whose records are single delivered
sentences that needed no chunking at all. Checkpoint 3 says so in as many words ("How did I chunk
it? I didn't"). Writing that a second time would be the checkpoint admitting the promise slipped.

Two further items close here. **DIVERGENCES row 4** records that FR-9b's dedup has only ever been
demonstrated against a hand-seeded ledger, because a score and a forecast are new every night and
never repeat. News repeats, so this is where dedup gets its first organic test. **PRD §9 Q5** notes
that `k = 5`, `similarity_floor = 0.60`, `window_days = 14` are reasoned rather than measured; news
traffic is the thing that eventually lets them be measured, though this build produces the traffic,
not the measurement.

## 2. Goal & success metric

- **Goal:** A nightly AI-news item per configured interest, written from passages retrieved out of a
  multi-day corpus of article text, where every number and every quoted phrase in the prose traces
  to a specific chunk observation in that run's trace.

- **Success metric.** Four conditions, all computable from `data/runs/*.jsonl` with no other input,
  measured across 14 consecutive nights. The parent PRD's §2(a) provenance metric continues to hold
  unchanged and unweakened; these sit inside it.

  - **(a) Grounded prose.** **Zero** `ungrounded_number` and **zero** `ungrounded_quote` violations
    in any run. A single violation fails the metric, exactly as §2(a) does.
  - **(b) Retrieval attribution.** 100% of delivered news items carry at least one chunk observation
    id in `observations`, and every one of those ids resolves to an `observation` record in the same
    trace. Zero orphans, zero items with an empty set.
  - **(c) Organic dedup evidence.** At least one news item is suppressed or reframed against a ledger
    that was **never seeded**, with its neighbours, their similarity scores, and the stated reason in
    the trace. This is the condition that retires DIVERGENCES row 4, and it is the only one of the
    four that cannot be satisfied by a single run.
  - **(d) No silent loss.** For every run,
    `items_assessed == items_delivered + dedup_suppressed + preference_suppressed`, where every
    suppression on either path carries a recorded reason in the trace, and a reframed item counts as
    delivered. Any discrepancy fails.

Deliberately **not** a metric: digest quality, topical relevance, or whether the summary is any good.
Those are opinions. Also not a metric: anything about `k`, the similarity floor, or the window. This
feature generates the evidence for tuning them; it does not tune them. See §9.

## 3. Users & job-to-be-done

One user: Sarah. The job is "tell me what actually happened in AI today, in a few sentences, without
putting me back on a feed, and without three consecutive nights of *Fable rocks but is expensive*."

The subordinate job is the capstone's: produce the first place in this system where retrieval is
load-bearing for **grounding** rather than only for **selection**, because that is the distinction
Module 3 named and the one Checkpoint 3 promised to demonstrate next.

## 4. Scope

**In scope:**

- An RSS/Atom feed adapter, keyless, over a configured feed list.
- An article-body fetch that respects `robots.txt`, sends an identifying `User-Agent`, and rate
  limits itself, with an explicit fallback when a body cannot be extracted.
- Paragraph-aware chunking with overlap, and a headline prefix on every chunk.
- A **second** vector collection for article chunks, in its own database file, with its own TTL.
- Topic-query retrieval against that corpus, one query per configured interest.
- One `Beat` implementation, registered by one config entry, changing no shared pipeline module.
- An extension to FR-11's provenance checker covering model-synthesized item text.
- A news-shaped replacement for FR-19's first safety invariant (see §5 FR-27 and §8).
- Per-source failure handling at feed granularity.

**Out of scope / non-goals:**

- **Escalation rules for news.** Parent PRD §9 Q2 (rules vs judgment for escalation) is open and this
  spec does not answer it. Escalation stays deterministic and news contributes no rule. A news item
  is never an `escalation_candidate` in this increment.
- **Tuning any retrieval threshold.** Parent §9 Q5 stays open, and this feature adds a sibling
  question rather than closing it.
- **The other three FR-17 beats** (r/WallStreetBets, need-to-know news, live music). "Need-to-know
  news" in particular needs a *bar*, which is a judgment problem, and it stays where it is.
- **Cross-publisher story clustering.** Deciding that a TechCrunch piece and an Ars piece are "the
  same story" is item identity as a stored property, which parent §9 Q3 explicitly rejected.
- **Re-ranking, hybrid BM25, or query expansion.** A corpus of roughly 1,400 chunks does not need
  them, and adding them would be gold-plating a demonstration.
- **Full-archive retention.** The corpus is disposable and rebuildable from the feeds.
- **Any paid or key-requiring dependency.** See §6.

## 5. Functional requirements

- **FR-20 — RSS/Atom feed adapter** `[MVP]`
  - **Requirement:** A keyless client over a configured list of feed URLs, returning per entry a
    normalized record: `url` (canonical, redirect-resolved), `source` (the configured feed name),
    `headline`, `published` (parsed to the configured local timezone), and `summary` (the feed's own
    body text, whatever length it is). Both RSS 2.0 and Atom are parsed. An entry with no resolvable
    publication date is dropped, with the drop recorded in the trace.
  - **Acceptance:** Done when a recorded fixture set containing one RSS 2.0 feed, one Atom feed, and
    one feed with a malformed entry yields the correct entry count and normalized fields, the
    malformed entry is dropped with a trace record naming it, and a test asserts the outgoing
    `User-Agent` is the configured identifying string.
  - **Touches:** `forecaster/tools/feeds.py`, `tests/fixtures/feed_*.xml`
  - **Note:** measured live 2026-08-04 — feed summary bodies run 111 to 975 median characters
    depending on publisher. That is one chunk, which is exactly why FR-21 exists.

- **FR-21 — Article body fetch and extraction** `[MVP]`
  - **Requirement:** Entries are **first filtered to those published inside `[news.retrieval]
    window_days`**, and only the survivors are fetched. For each surviving entry, fetch the article
    page and extract its body text. The fetch (a) checks the host's `robots.txt` and skips a
    disallowed URL, (b) sends the configured identifying `User-Agent`, (c) waits at least
    `fetch_delay_seconds` between requests to the same host, and (d) times out. When extraction yields
    fewer than `min_body_chars`, the record falls back to the feed summary and is marked
    `text_source = "summary"`; a successful extraction is marked `text_source = "article"`.
    **No body is ever synthesized to fill the gap.**
  - **Acceptance:** Done when, over recorded fixtures, (i) an article page yields
    `text_source="article"` with a body over `min_body_chars`, (ii) a paywalled page whose extracted
    body falls under the floor yields `text_source="summary"` carrying the feed summary verbatim and
    no invented text, (iii) a URL disallowed by a fixture `robots.txt` is skipped with a trace record,
    (iv) a fetch that times out leaves the entry at `text_source="summary"` rather than dropping it,
    and (v) **a fixture feed of 1,108 entries of which 12 fall inside the window issues exactly 12
    article fetches** — the date filter runs before the fetch, not after.
  - **Touches:** `forecaster/tools/feeds.py`
  - **Note:** measured live 2026-08-04 — extracted article bodies run 3,233 to 6,838 characters, and
    `robots.txt` on arstechnica.com and techcrunch.com permits the fetch with an identifying agent and
    declares no crawl delay. See §8 for the copyright posture.

- **FR-22 — Paragraph-aware chunking** `[MVP]`
  - **Requirement:** Split each article body into chunks of about `target_chars`, never exceeding
    `max_chars`, with `overlap_chars` of trailing context carried into the next chunk. Splits fall on
    paragraph boundaries; a single paragraph is only split internally when it alone exceeds
    `max_chars`. Every chunk is prefixed with its headline on its own line, because a mid-article
    chunk carries no subject otherwise and static embeddings are close to bag-of-words. Each chunk
    records its ordinal and its character offsets in the source body.
  - **Acceptance:** Done when a 6,000-character fixture body yields chunks each at or under
    `max_chars`, every chunk after the first begins with `overlap_chars` of the previous chunk's tail,
    every chunk's first line is the headline, concatenating the chunks with overlaps removed
    reproduces the source body byte for byte, and a 400-character body yields exactly one chunk.
  - **Touches:** `forecaster/memory/corpus.py`

- **FR-23 — Article chunk corpus (second vector collection)** `[MVP]`
  - **Requirement:** A **separate** SQLite file, `data/corpus.db`, holding `articles` (keyed by
    canonical url), `chunks` (keyed by surrogate id, foreign key to url, carrying ordinal, text, and
    offsets), and a `sqlite-vec` `vec_chunks` table keyed by chunk id. It uses the **same `Embedder`
    instance** as FR-9b, so the model loads once per run. Rows older than `ttl_days` are purged at run
    start, before indexing. Re-fetching a url already present replaces its chunks rather than
    duplicating them.
  - **Acceptance:** Done when indexing an article writes one `chunks` row and one `vec_chunks` row per
    chunk; re-indexing the same url leaves the chunk count unchanged; an article whose `fetched_at` is
    older than `ttl_days` is gone after a purge while `ledger.db`'s `sent_items` count is unchanged by
    every one of these operations; and a test asserts `corpus.db` and `ledger.db` are distinct files.
  - **Touches:** `forecaster/memory/corpus.py`, `data/corpus.db` (gitignored)
  - **Rationale for the split file:** the two corpora have opposite lifecycles. `sent_items` is the
    permanent record of what was actually delivered and cannot be rebuilt if lost; article chunks are
    disposable and reconstructible from the feeds in one run. At roughly 40 articles a night times 5
    chunks times 7 days, the chunk corpus is about 1,400 vectors against the ledger's roughly 35 a
    week, so sharing the file would have the disposable corpus dwarfing the durable one. A corpus you
    can delete without losing anything does not belong in the file holding the record you cannot
    rebuild.

- **FR-24 — Topic-query retrieval over the corpus** `[MVP]`
  - **Requirement:** For each interest configured in `[[news.topics]]`, embed its `query` string and
    retrieve the top `k` chunks from `corpus.db` scoring at or above `similarity_floor`, restricted to
    articles published within `window_days`. Retrieval returns chunk text, its article's url, source,
    headline, and publication date, and the similarity score. At most `max_chunks_per_article` chunks
    from any one article may be returned for a single topic, so one long article cannot fill the whole
    context. An empty result for a topic means that topic produces no item tonight, and the emptiness
    is recorded in the trace.
  - **Acceptance:** Done when a seeded fixture corpus returns, for a given topic query, exactly the
    chunks above the floor in descending similarity, never more than `k`, never more than
    `max_chunks_per_article` from one article, and never a chunk from an article outside the window;
    and when a topic matching nothing produces zero items plus a `topic_empty` trace decision rather
    than an error or a fabricated line.
  - **Touches:** `forecaster/memory/corpus.py`
  - **Note:** these thresholds are **separate from FR-9b's** and are also unmeasured. See §9 Q6.
  - **Test construction constraint:** the suite embeds with `HashingEmbedder`, whose scores are a
    hashed bag of words and do **not** match the shipped model's. Fixture corpora must therefore be
    built so the expected result set holds under `HashingEmbedder`, and the acceptance test must assert
    ordering and set membership rather than any absolute similarity value.

- **FR-25 — News beat worker** `[MVP]`
  - **Requirement:** One `Beat` implementation, `NewsBeat`, registered by `[beats] news = true` plus a
    `[news]` section, that runs FR-20 → FR-21 → FR-22 → FR-23 → FR-24 and emits one `BeatItem` per
    topic that retrieved anything. The item's `text` is written by the injected agent client from the
    retrieved chunks only, and its `observations` list carries the observation id of every chunk it was
    grounded in. The item declares `fields = {"topic": <id>, "text_origin": "synthesized"}` and
    nothing else — see FR-27 for why no url or date belongs there. The beat adds **zero** edits to
    `planner.py`, `synthesizer.py`, or `delivery/`.
  - **Acceptance:** Done when the existing `ast` seam test in `tests/test_cli.py` still passes with the
    news beat registered and enabled; a full pipeline run over fixtures produces one item per
    non-empty topic; every item's `observations` are non-empty and every id resolves to an observation
    record in the same trace; and disabling `[beats] news` returns the digest to its two-beat shape
    with no other change.
  - **Touches:** `forecaster/beats/news.py`, `config.toml`, plus two wiring edits that are **not**
    seam violations: `beats/base.py` gains optional `BeatContext` fields, and `cli.py` opens
    `corpus.db` and passes the same `StaticEmbedder` instance it already builds for FR-9b. FR-2's
    zero-edit clause names `planner.py`, `synthesizer.py`, and `delivery/` specifically, and none of
    those change — verified on the branch with `git diff --name-only dev...HEAD` over those paths.
  - **Amended 2026-08-04, during the build (Step 32).** `BeatContext` needed a third field this
    spec did not anticipate: **`agent_client`**. Through FR-25 every beat turned a typed API
    response into a sentence *in code*, so only the synthesizer ever held a client; a beat that
    summarizes retrieved passages cannot. This is the first crack in "beats do not talk to the
    model", and it is worth naming rather than burying. What makes it safe is that FR-11's
    guarantee is unchanged and FR-26 now extends it: the model phrases, and the run fails if a
    figure it wrote is absent from a passage the item points at.

- **FR-26 — Grounded-text provenance check (extends FR-11)** `[MVP]`
  - **Requirement:** `check_provenance` gains one case, scoped to items declaring
    `fields["text_origin"] == "synthesized"`. For such an item: every number in `item.text` must appear
    in at least one payload of the observations that item links to, else `ungrounded_number`; and every
    double-quoted span of four characters or more in `item.text` must appear verbatim, case-insensitively,
    in at least one such payload, else `ungrounded_quote`. A number counts as grounded if it appears in a
    payload **as digits or as its English word form for 0 through 20** (a fixed, closed mapping), because
    a model handed "3 papers" may legitimately write "three papers". Items without the flag are
    untouched, so the Astros and weather beats are unaffected.
  - **Acceptance:** Done when a synthesized item whose text states a number absent from every linked
    chunk produces exactly one `ungrounded_number` violation and fails the run; a synthesized item whose
    every number and quote appears in a linked chunk passes; an item writing "three" where the chunk
    says "3" passes, and one writing "four" where the chunk says "3" fails; an unflagged item containing
    an unsupported number produces no new violation (proving the case is scoped); and the two existing
    beats' provenance tests pass unchanged.
  - **Known false-positive mode, accepted deliberately:** a legitimate number the model derives rather
    than copies (a sum, a count of items, a year computed from "last year") fails the check and fails the
    run. That is the correct-side error for this project: the check never lets a fabrication through, and
    a loud failure is fixable where a silent invention is not. If it fires often in practice, the fix is
    to constrain the summary prompt, not to loosen the check.
  - **Touches:** `forecaster/trace.py`
  - **Why the checker grows rather than the item shrinking:** FR-11's support check runs over declared
    `checkable_fields`, and its fidelity check templates `item.text` for altered numbers. Neither
    catches a number the model *invented* into a synthesized sentence, because the two shipped beats
    build their item text from typed API fields in code, so that failure could not previously occur.
    A summary written from a passage is the first place it can. The check has to grow.

- **FR-27 — Grounded-value suppression veto (transplants FR-19 invariant 1)** `[MVP]`
  - **Requirement:** For a news item, dedup may not suppress when the candidate's text introduces any
    of three things that appear in **none** of its retrieved ledger neighbours' `rendered_text`:
    a **number**, a **quoted phrase**, or a **proper noun** (a capitalized token of three or more
    characters that is not sentence-initial). Such an item may be reframed but never dropped, the
    decision is `forced`, and the model is not consulted. When the candidate introduces none of the
    three, the model judges as normal and may suppress. News items therefore carry **no date, url, or
    source in `fields`**, and `tests/test_time_scoped_items.py` is amended to exempt items declaring
    `text_origin = "synthesized"`, with the exemption pointing at this requirement.
  - **Acceptance:** Done when (i) a news item quoting a benchmark figure no neighbour stated survives
    against a cosine-1.0 neighbour with the model never consulted, (ii) a news item naming an entity no
    neighbour named survives the same way, (iii) a news item restating the same story with the same
    figures and the same entities reaches the model and is suppressible, (iv) a test asserts no news
    item's `fields` contains any of `published`, `url`, `source`, `date`, `game_date`, `as_of`, and
    (v) the four existing `test_time_scoped_items.py` cases still pass for the Astros and weather beats.
  - **Why the proper-noun clause is not gold-plating:** without it, "Anthropic shipped a new agent
    framework" against the neighbour "Anthropic shipped a new model" carries no new number and no new
    quote, so the model alone decides whether a real story reaches the digest. That is the failure
    FR-19 exists to make impossible. The clause is also what keeps §2(c) satisfiable: a genuine repeat
    of the same story reuses its entities, so it stays suppressible. If the veto over-fires in practice
    the digest repeats itself, which the trace records and which is the correct-side error here — the
    project's stated position is that going quiet is worse than repeating.
  - **Touches:** `forecaster/memory/dedup.py`, `tests/test_time_scoped_items.py`
  - **This is the load-bearing requirement in the spec.** See §8 for the failure it prevents.
  - **Amended 2026-08-04, during the build (Step 31).** As built, the grounded-value branch
    **short-circuits** the typed comparison rather than running alongside it: for an item declaring
    `text_origin="synthesized"`, `_checkable_values_differ` is never reached. That is stronger than
    this requirement asked for. The "no date, url, or source in `fields`" rule was written as a
    *necessity* — a leaked artifact key would fire the typed invariant nightly and kill dedup. It is
    now belt-and-braces: a stray key cannot disable dedup, because nothing consults it. The
    convention still holds (those keys are meaningless noise on a news item) and acceptance clause
    (iv) still asserts it, but the failure mode it guarded against is now impossible rather than
    merely forbidden. Enforcing rather than requesting is the same reasoning as FR-11 and FR-19.

- **FR-28 — Per-source failure handling (FR-18 at feed granularity)** `[MVP]`
  - **Requirement:** A feed or article fetch that fails does not fail the beat. Each failed source is
    recorded as a `source_unavailable` trace decision naming the source and the error, and the digest
    must name every such source. When **every** configured feed fails, the beat returns
    `BeatResult.unavailable(...)` and the existing FR-18 path handles it unchanged.
  - **Acceptance:** Done when a fixture set in which two of five feeds 500 produces a digest naming both
    failed sources, carrying items built only from the three that worked, and **no** substitute content
    for the two that did not; when all five failing produces the standard FR-18 unavailability line and
    no news content; and when `check_provenance` reports a new `unnamed_failed_source` violation for a
    trace whose digest omits a source that failed.
  - **Touches:** `forecaster/beats/news.py`, `forecaster/trace.py`

- **FR-29 — News-beat metric checker** `[MVP]`
  - **Requirement:** A function that computes §2's four conditions over one or more trace files and
    returns a structured report, plus a CLI subcommand that prints it. Conditions (a), (b) and (d) are
    computable from a single run; (c) requires a set of runs and reports how many nights have
    accumulated so far.
  - **Acceptance:** Done when the checker returns all-pass over a fixture trace satisfying every
    condition, and returns the specific failing condition for four fixture traces each violating exactly
    one of them.
  - **Touches:** `forecaster/trace.py`, `forecaster/cli.py`

- **FR-30 — Item-level provenance quarantine (narrows FR-11)** `[MVP]`
  - **Recorded retroactively 2026-08-14.** This requirement shipped 2026-08-04 (PR #6, `25184f6`,
    Sarah's call during the first live news runs) without ever being written into a spec — it was
    logged in STATUS.md and DIVERGENCES row 8 at the time, but no PRD carried it until now. The text
    below describes what shipped, written from `synthesizer.py`, `trace.py`, and
    `tests/test_item_quarantine.py`, not from intent. FR-30 is the last number this spec owns; FR-31
    onward are claimed by the need-to-know news spec.
  - **Requirement:** A provenance violation the checker can pin to **one item** costs that item, not
    the night. The item-level kinds are exactly `ungrounded_number`, `ungrounded_quote` (FR-26's two
    cases), and `ungrounded_item` (a synthesized item that points at no observation at all); each
    carries the offending item's text, and only items declaring `text_origin = "synthesized"` can
    produce one, so the two structured beats cannot be quarantined. When a composed digest's
    provenance report contains item-level violations **and nothing else**, the synthesizer, instead
    of raising: (a) withholds each pinned item, recording an `item_quarantined` trace decision that
    carries the full detail and the exact item text; (b) recomposes the digest **exactly once**,
    with a withholding notice per item that names the beat and the kind of failure but **never
    repeats the ungrounded words** — echoing the unverifiable phrase inside the notice would put it
    in front of the reader anyway, so the specifics go to the trace only; (c) re-runs
    `check_provenance` with the withheld texts passed as `excluded_items` — an item the reader was
    never shown states nothing to them — and records the second verdict as `provenance_rechecked`.
    Any violation that is *not* item-level (an unsupported or altered checkable field, a failed beat
    missing from the digest, an unnamed failed source), alone or mixed in, still fails the run
    outright, because nothing smaller can be dropped to fix it. If the single recomposition still
    fails, the run fails.
  - **Why this narrows FR-11 rather than weakening it:** the motivating failure was one punctuation
    mark inside one quotation in one news item costing the Astros score, the forecast, and the entire
    night's digest — and FR-18's whole position is that going quiet is worse than saying less. The
    guarantee is unchanged: nothing unverifiable reaches the reader, and every withholding is named.
    The one-recomposition cap is load-bearing — a loop that kept dropping items until something
    passed would be a machine for producing an empty, confident digest.
  - **Acceptance:** Done — asserted by `tests/test_item_quarantine.py`, shipped in the same change:
    (i) of two news items with one ungrounded, the grounded item is delivered, the ungrounded one is
    absent, and the final report is clean; (ii) the digest names the withholding and the beat;
    (iii) the `item_quarantined` decision carries the offending value and the verbatim item text;
    (iv) both `provenance_checked` and `provenance_rechecked` appear in the trace; (v) an unsupported
    checkable field still raises `ProvenanceError`; (vi) when every item is ungrounded, every one is
    withheld and each withholding is named; (vii) a client that fabricates on every call is called
    exactly twice — one composition, one recomposition, no more; (viii) `check_provenance` with
    `excluded_items` passes over a trace it fails without them, with an explanatory note; (ix) a
    structured weather item quarantines nothing; (x) the withholding notice does not echo the
    ungrounded phrase while the trace record keeps it in full.
  - **Touches:** `forecaster/synthesizer.py`, `forecaster/trace.py`, `tests/test_item_quarantine.py`
  - **Cross-reference:** DIVERGENCES row 8 records this as one of four narrowings of the provenance
    check made before any checkpoint mentions them, and its constraint binds writing about this
    requirement: a checkpoint may say the guarantee held; it may not yet say the guarantee was
    tested, because nothing has yet tried to fabricate and been caught in the wild. FR-29's metric
    reads a run's **final** provenance verdict, which after a quarantine is the recheck (PR #8).

## 6. Technical & data notes

- **Source decision (Sarah, 2026-08-04): RSS discovery plus article-body fetch.** Free, keyless, no
  signup, which keeps the standing rule that every external dependency in this project is free and
  keyless. The rule was raised rather than assumed, and the measurement is what settled it:

  | Option | Body text per item | Key / cost | Verdict |
  |---|---|---|---|
  | RSS summaries only | 111–975 chars (median, by publisher) | none | one chunk; chunking stays a no-op |
  | **RSS + article fetch** | **3,233–6,838 chars** | **none** | **chosen** |
  | arXiv abstracts | 1,000–2,000 chars | none, 1 req / 3 s | research, not news |
  | NewsAPI.org, any plan | truncated snippet at every tier | $449/mo minimum | fails the promise *and* costs money |

  The decisive fact is that no NewsAPI.org plan returns full article content, at $0, $449/mo, or
  $1,749/mo, so paying would not have bought the feature. Measured 2026-08-04 against
  [newsapi.org/pricing](https://newsapi.org/pricing) and the live feeds.

- **New dependencies:** an HTML body extractor. Prefer `trafilatura` if it installs without pulling a
  large tree; otherwise a hand-rolled readability pass over `<p>` elements, which is what produced the
  measured 3,233–6,838 character range above. `feedparser` for RSS/Atom, or stdlib `xml.etree` plus
  `email.utils.parsedate_to_datetime` if that stays small. **No torch, no paid service, no key.**

- **Embeddings:** the same `model2vec` `StaticEmbedder` (`minishlab/potion-retrieval-32M`, 512-dim)
  FR-9b already uses, instantiated once per run and passed to both the ledger retriever and the corpus.
  `HashingEmbedder` remains the offline double for the whole test suite.

- **Two vector collections, one embedder, two files.** `ledger.db` keeps `sent_items` and
  `vec_sent_items`; `corpus.db` gets `articles`, `chunks`, and `vec_chunks`. Both gitignored. See
  FR-23's rationale.

- **Why retrieval is necessary here and was not for the v1 beats.** One night's 40 articles could be
  handed to the model directly. The corpus spans `ttl_days`, which at roughly 1,400 chunks is on the
  order of 350k tokens, and the nightly run shares subscription rolling-window limits with interactive
  Claude Code use. Retrieval is required by the **multi-day** corpus, not by any single night. The PRD
  states this plainly rather than implying a vector index is needed for 40 articles, because the
  honest version is also the better argument.

- **Config lives in `config.toml`**, following the `[team]` and `[location]` precedent, so FR-2's
  "one class plus one config entry" stays literally true and `preferences.py` needs no edit:

  ```toml
  [beats]
  news = true

  [news]
  user_agent = "forecaster/0.1 (sarah.rachel.hernandez@gmail.com)"
  fetch_delay_seconds = 1.0
  timeout_seconds = 15
  min_body_chars = 600
  feeds = [
    { name = "Ars Technica",  url = "https://feeds.arstechnica.com/arstechnica/index" },
    { name = "TechCrunch AI", url = "https://techcrunch.com/category/artificial-intelligence/feed/" },
    { name = "The Verge",     url = "https://www.theverge.com/rss/index.xml" },
    { name = "OpenAI",        url = "https://openai.com/news/rss.xml" },
    { name = "DeepMind",      url = "https://deepmind.google/blog/rss.xml" },
  ]

  [news.chunking]
  target_chars = 900
  max_chars = 1200
  overlap_chars = 150

  [news.corpus]
  path = "data/corpus.db"
  ttl_days = 7

  [news.retrieval]
  k = 6
  similarity_floor = 0.35
  window_days = 3
  max_chunks_per_article = 2

  [[news.topics]]
  id = "claude"
  query = "Anthropic Claude model releases, capabilities, and pricing"

  [[news.topics]]
  id = "agents"
  query = "AI agents, tool use, and agent frameworks"

  [[news.topics]]
  id = "evals"
  query = "model evaluations, benchmarks, and safety testing"
  ```

  All five feeds returned HTTP 200 keyless on 2026-08-04. The topic list is Sarah's taste and is meant
  to be edited freely; nothing in the code knows these three ids.

- **Testing:** recorded fixtures for every feed and every article page, captured in the same change as
  the adapter, per the repo rule. The socket guard stays on. `FakeAgentClient` writes the synthesized
  summaries; no model call in the suite.

## 7. Dependencies

- The parent PRD's FR-9b retrieval layer, merged into `dev` as `f452153` on 2026-08-04.
- An HTML extraction library, or the hand-rolled fallback described in §6.
- Nothing else new. No key, no account, no paid tier, no network at test time.
- **Not blocking:** HUMAN-TODO ③ (SMTP app password) and ④ (scheduled task). Neither gates this build.
  But see §8 — ④ does gate the *metric*.

## 8. Risks & edge cases

- **FR-19's first invariant does not generalize to a document-shaped beat, and getting this wrong
  silently disables the feature.** Invariant 1 forbids suppressing an item whose checkable value
  differs from its nearest neighbour's. It was designed for recurring status items, where identical
  wording on a different day means a genuinely different fact. News inverts that: the same story on a
  different day *is* the repeat, and it is precisely what should be suppressed. Any per-artifact field
  in a news item's `fields` therefore breaks dedup permanently and invisibly:
  - `date` or `as_of` set to the run date differs every night, so invariant 1 fires on every item and
    nothing is ever suppressed;
  - `published` differs whenever tonight's top article is newer than last night's, which is the normal
    case, so the same outcome;
  - `url` differs whenever the same story is picked up by a second publisher, which is exactly the
    "three days of *Fable rocks but is expensive*" case this build exists to fix.

  FR-27 is the resolution: transplant the invariant from typed fields to grounded prose, so the veto
  fires on a **new number or a new quoted phrase**, which is the thing that actually means the reader
  is learning something. This was found while writing the spec, not during a build, and it is the
  most interesting design content in the increment.

- **Copyright and terms of service for the article fetch.** The digest is personal, goes to one inbox,
  and is not redistributed; the fetch respects `robots.txt`, identifies itself, and rate limits. That
  is the same posture as a full-text RSS reader. It is still a fetch of copyrighted text and the risk
  is low rather than zero. Mitigations that belong in the build: quote sparingly, always carry the
  source name and a link in the item, and never store more than `ttl_days`. If any publisher's
  `robots.txt` disallows it, that publisher degrades to summary-only rather than being scraped anyway.

- **Extraction is per-publisher fragile.** A site redesign silently drops a source to `text_source =
  "summary"`. FR-21 makes that visible rather than fatal, but the corpus quietly thins. The metric's
  condition (b) does not catch it. Worth a periodic look at the `text_source` distribution in the trace.

- **§2(c) is gated on HUMAN-TODO ④.** Organic dedup evidence needs 14 consecutive nights, which needs
  the scheduled task registered. This build produces the traffic; it cannot produce the nights. No
  checkpoint may describe the thresholds as tuned, or the organic test as done, before those nights
  exist.

- **The corpus and the ledger can drift out of the same vector space.** Both use one embedder per run
  by construction (FR-23), but changing `[retrieval] model` would invalidate `vec_sent_items` and
  `vec_chunks` differently, since the corpus rebuilds in a night and the ledger does not. A model
  change needs a ledger reindex, and nothing currently enforces that.

- **A topic that matches nothing produces no item, which looks identical to a broken beat.** FR-24
  records `topic_empty` so the trace distinguishes them, but the digest reader cannot. Acceptable for
  v1; worth watching whether a quiet topic is quiet or broken.

- **Feed volume is unbounded.** OpenAI's feed returned 1,108 entries in one fetch on 2026-08-04. The
  publication-date window in FR-24 bounds what is *retrieved*, but FR-21 would try to fetch every entry
  before that filter applies. The build must filter entries by `published` **before** fetching bodies,
  or a single run makes a thousand HTTP requests.

- **Escalation stays silent on news by design.** A genuinely urgent AI story gets no promotion, because
  parent §9 Q2 is open. That is a deliberate gap, not an oversight.

## 9. Open questions

Downstream must not invent answers to these.

1. **Q6 (new) — the corpus-retrieval thresholds are unmeasured.** `k = 6`,
   `similarity_floor = 0.35`, `window_days = 3`, `max_chunks_per_article = 2` are reasoned, not
   measured. The floor is set well below FR-9b's 0.60 because a topic query against an article chunk is
   a much weaker match than line against line, and the window is shorter than the corpus TTL because
   news goes stale faster than it should be forgotten. Nothing has validated any of that. This is a
   **sibling** of parent §9 Q5, not an answer to it; a checkpoint must not describe either set as tuned.

2. **Parent §9 Q2 — rules vs judgment for escalation — remains open** and this feature does not touch
   it. No news escalation rule is specified. If a build step appears to need one, stop.

3. **Parent §9 Q5 — FR-9b's dedup thresholds — remains open.** This feature generates the traffic that
   makes measuring them possible. It does not measure them.

4. **How long should a suppressed story stay suppressed?** A story judged "adds nothing" on night two
   might become significant on night five. Resurrection is a judgment call, which is Q2 again, so this
   increment does not implement one. Flagged because it is the first thing a real user notices.

## 10. Phasing

- **v3 (this increment): FR-20 … FR-29.** Ten requirements, all MVP. It is a larger increment than the
  FR-9b one and it is coherent: FR-25 depends on FR-20 through FR-24, and FR-26 and FR-27 are what keep
  it honest, so a cut that ships the beat without them ships a beat that can fabricate and can silently
  drop a real story.
- **The available cut, if it has to shrink:** drop **FR-24 and FR-26**, keep everything else. Items
  become verbatim headlines rather than synthesized summaries, so FR-11 needs no extension and the
  corpus is built but not queried. FR-27 survives the cut intact, because its veto operates on any item
  text and a headline has numbers, quotes, and proper nouns just as a summary does. This ships faster
  and still gives dedup its organic traffic, but it does **not** pay DIVERGENCES row 6, since retrieval
  would again be selecting rather than grounding. Take the cut only if the checkpoint deadline forces
  it, and record it as a new divergence row.
- **Not in this increment:** FR-16 (feedback loop), the other three FR-17 beats, any threshold tuning.

## 12. Changelog

- **v1 — 2026-08-04:** Initial PRD. Source decision made by Sarah after measurement (RSS discovery plus
  article-body fetch; no paid API, since none returns full article text). Item shape and grounded-summary
  provenance case also chosen by Sarah. FR-27 added during drafting after finding that FR-19's first
  invariant inverts for a document-shaped beat.
- **v2 — 2026-08-14:** FR-30 recorded retroactively, ten days after it shipped (2026-08-04, PR #6,
  `25184f6`). The requirement was Sarah's call during the first live news runs and went straight to
  code; STATUS.md and DIVERGENCES row 8 carried it, no spec did. Written from the shipped code and
  tests. No other section changed, and nothing was renumbered.

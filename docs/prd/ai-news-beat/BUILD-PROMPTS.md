# BUILD PROMPTS — AI news beat with document-shaped RAG

**Source PRD:** [`PRD.md`](PRD.md) (v1, 2026-08-04) · **Feature ID:** `ai-news-beat` ·
**Parent spec:** [`../forecaster/PRD.md`](../forecaster/PRD.md) (owns FR-1 … FR-19)

> **Driving this across multiple sessions?** Keep a `BUILD-LOG.md` in this folder updated after
> **every** step (step status + its verify result, deviations/decisions, new blockers, run notes),
> and resume per that log — re-verify the last done step against the actual repo before continuing.
> Never hand off mid-step.

---

## How to run these

- **12 steps, numbered 23–34**, continuing the parent build's ledger. Steps 1–22 are done and on
  `dev` (`f452153`, 265 tests green). **Do not regenerate them.**
- **Branching.** `feature/ai-news-beat` cut from **`dev`**, one commit per completed step, PR into
  **`dev`**. Never commit to `main`. This repo has no `scripts/new-worktree.mjs`; make the worktree
  by hand if you want isolation.
- **Windows 11 / PowerShell.** All commands below assume `cd forecaster` first.
- **Verify before moving on.** A step is done when its **Verify** block passes, not when the code
  looks right. `uv run pytest -q` must stay green at every step boundary — 265 tests is the floor.

## Non-negotiable constraints (every step inherits these)

1. **Auth is subscription OAuth, never an API key.** `CLAUDE_CODE_OAUTH_TOKEN` only.
   `assert_subscription_auth()` refuses to start if `ANTHROPIC_API_KEY` is present. No fallback, no
   convenience flag.
2. **No paid dependency, no API key, no signup.** The source decision is settled and is in PRD §6:
   RSS discovery plus an article-body fetch, both keyless. **Do not swap in a news API** — no plan at
   any price returns full article content, so it would cost money and still fail the feature.
3. **No live network in the test suite.** Recorded fixtures plus the socket guard (loopback allowed
   so asyncio works on Windows). **A new adapter means capturing its fixtures in the same step.**
4. **No model calls in tests.** `FakeAgentClient` everywhere. Same for embeddings: `HashingEmbedder`
   is the offline double, `StaticEmbedder` is the real one.
5. **Never fabricate a fact to fill a gap.** A failed source produces an explicit unavailability line
   and no substitute value. That is FR-18 and it is the point of the project.
6. **No secrets in the diff.** Nothing in this increment needs a credential; if a step reaches for
   one, that is the signal something is wrong.
7. **In scope only.** The PRD's §4 non-goals are out: no news escalation rule, no cross-publisher
   story clustering, no re-ranking or hybrid BM25, no threshold tuning, no other FR-17 beat.

## Open questions — none block a step, but three bind every step

Checked against PRD §9. **No FR in this increment is withheld**, which is worth stating plainly
rather than manufacturing a blocker. But these constrain what a step may do:

| Q | Question | Effect on this build |
|---|---|---|
| Parent Q2 | Rules vs judgment for escalation | **Still open.** No news escalation rule exists. A news item is never an `escalation_candidate`. If a step starts wanting one, stop and surface it. |
| Parent Q5 | FR-9b's dedup thresholds unmeasured | **Still open.** This increment creates the repeat traffic; it does not measure. No step may change `k`, `similarity_floor`, or `window_days` under `[retrieval]`. |
| Child Q6 | Corpus-retrieval thresholds unmeasured | **Still open.** `[news.retrieval]` ships the PRD's reasoned defaults. Build to them, instrument them, do not tune them, and never describe them as tuned. |
| Child Q4 | How long a suppressed story stays suppressed | Not implemented this increment. No resurrection logic. |

## One decision the implementing agent makes by measuring

**The HTML body extractor** (PRD §6). Prefer `trafilatura` **only if** `uv add trafilatura` pulls a
small tree with **no torch and no ML runtime** — check with `uv tree` before committing to it. If it
does not, hand-roll a readability pass over `<p>` elements after stripping
`script/style/nav/header/footer/aside`, which is what produced the PRD's measured 3,233–6,838
character range. Record the choice and the measured dependency count in `BUILD-LOG.md`. Either way
the extraction interface is the same, so this decision does not leak past Step 26.

## Two things Sarah owns, neither blocking

- **The feed list and topic queries** in PRD §6 are a starting proposal, not a design decision.
  Ship them as the committed defaults; she edits `config.toml`. Nothing in the code knows those ids.
- **§2(c), the organic dedup metric, needs 14 consecutive nights**, which needs HUMAN-TODO ④ (the
  scheduled task). This build produces the traffic; it cannot produce the nights. Step 34 reports how
  many nights have accumulated and must never report the condition as met before they have.

---

# Build steps

### Step 23 — Text and bytes fixtures in the test harness  (infrastructure; enables FR-20, FR-21, FR-28)

**Context:** `tests/conftest.py` and `scripts/capture_fixture.py` are **JSON-only** today.
`load_fixture` calls `json.loads`, `Route.payload()` returns a parsed object, `mock_transport` builds
`httpx.Response(status, json=payload)`, and `capture_fixture.capture()` calls `response.json()` and
writes `.json`. RSS is XML, article pages are HTML, and `robots.txt` is plain text. **Without this
step, constraint 3 cannot be honored for any of the new adapters** — there is no way to serve them
from a recorded fixture.

**Task:** Widen the harness to non-JSON payloads, changing no existing behavior.

- `tests/conftest.py`:
  - `load_text_fixture(name) -> str` reading `tests/fixtures/<name>` verbatim as UTF-8, with the
    extension required (`.xml`, `.html`, `.txt`) so it can never collide with `load_fixture`'s
    optional-`.json` convention.
  - Extend `Route` with `text: str | None` and `content_type: str | None`. When `text` is set (or a
    `fixture` whose name carries a non-`.json` extension), the handler returns
    `httpx.Response(status, text=..., headers={"content-type": ...})` instead of `json=`. Default the
    content type from the extension: `.xml` → `application/xml`, `.html` → `text/html`, `.txt` →
    `text/plain`.
  - `Route.payload()` keeps its current signature and behavior for JSON routes. Existing callers must
    not change.
- `scripts/capture_fixture.py`: add `--raw` writing `response.text` verbatim to
  `tests/fixtures/<name>` (the name now carries its own extension), sending
  `Accept: */*` rather than `application/json`, and accepting `--user-agent` so a feed or article can
  be captured with the same identifying string the adapter will send. Keep the default JSON path
  untouched.
- Add one hand-built `tests/fixtures/sample.xml` so the new path has something to prove itself on,
  and note its synthetic provenance in `tests/fixtures/README.md`.

**Verify:** Done when `uv run pytest tests/test_harness.py -q` passes with two new cases — an XML
fixture and an HTML fixture each served through a real `httpx.Client` with the correct
`content-type` — **and** `uv run pytest -q` still reports 265 passed plus the new ones, proving no
existing JSON route changed behavior. The socket guard still fires on a real connection attempt.

**Guardrails:** Harness only, no adapter logic. Do not change `load_fixture`'s signature or the JSON
`Route` path. Do not add a dependency — `httpx` already does everything needed here.

---

### Step 24 — News config schema  (implements FR-1 for the news beat; prerequisite for FR-20 … FR-25)

**Context:** Parent FR-1 — every run parameter lives in `config.toml`, not in code. PRD §6 gives the
exact block to add. Touches `forecaster/config.py`, `config.toml`. Python 3.12's `tomllib` is stdlib;
no TOML dependency.

**Task:** Add and validate the news configuration.

- Copy PRD §6's `[news]`, `[news.chunking]`, `[news.corpus]`, `[news.retrieval]`, and the three
  `[[news.topics]]` blocks into `config.toml` verbatim, including the five feeds. All five returned
  HTTP 200 keyless on 2026-08-04.
- **Leave `[beats] news = false`.** `get_beats()` raises `LookupError` on a config that enables an
  unregistered beat, so flipping it before Step 32 registers `NewsBeat` turns the suite red. Step 32
  flips it.
- `forecaster/config.py`: typed dataclasses `NewsConfig`, `ChunkingConfig`, `CorpusConfig`,
  `NewsRetrievalConfig`, `TopicConfig`, loaded by the existing `load_config`. Validate loudly, never
  silently default a value that changes behavior:
  - `overlap_chars < target_chars <= max_chars`, all positive;
  - `k > 0`, `0.0 <= similarity_floor <= 1.0`, `window_days > 0`, `max_chunks_per_article > 0`;
  - `window_days <= corpus.ttl_days` (retrieving outside what is retained is a config bug);
  - feed names unique and non-empty, feed urls non-empty;
  - topic ids unique, non-empty, and each carrying a non-empty `query`;
  - at least one feed and one topic **when `[beats] news` is true** — an empty list with the beat off
    is fine.
- Tests in `tests/test_config.py`: the real `config.toml` parses into the typed fields; each
  validation rule above has a malformed-config case that raises with a message naming the key.

**Verify:** Done when `uv run pytest tests/test_config.py -q` passes every validation case, and this
returns nothing — no news parameter is hardcoded outside `config.py`:
```powershell
Get-ChildItem forecaster -Recurse -Filter *.py |
  Where-Object { $_.Name -ne 'config.py' } |
  Select-String -Pattern 'arstechnica|techcrunch|theverge|potion-retrieval|corpus\.db'
```

**Guardrails:** Config only — no adapter, no beat, no corpus code. Do not invent keys the PRD does not
call for. Do not flip `[beats] news` on. Do not put a credential in `config.toml`.

---

### Step 25 — RSS/Atom feed adapter + fixtures  (implements FR-20)

**Context:** PRD FR-20. A keyless client over the configured feed list, returning normalized entries.
Touches `forecaster/tools/feeds.py`. Follows the same contract as `tools/mlb.py` and
`tools/weather.py`: injectable `httpx.Client`, typed result, typed `AdapterError` on failure, never a
partial or guessed value. Measured 2026-08-04: feed summary bodies run 111–975 median characters
depending on publisher, which is why FR-21 exists.

**Task:** Build the adapter and record its fixtures.

- `forecaster/tools/feeds.py`: `FeedEntry` dataclass — `url`, `source`, `headline`, `published`
  (timezone-aware, converted to the configured local timezone), `summary` — and
  `fetch_feed(url, source, *, client) -> list[FeedEntry]`.
- Parse **both** shapes with stdlib `xml.etree.ElementTree`; do not add `feedparser` unless the
  stdlib genuinely cannot cope, and record the reason in `BUILD-LOG.md` if you do:
  - RSS 2.0: `<item>`, `<link>` as element text, `<pubDate>` in RFC 822 via
    `email.utils.parsedate_to_datetime`, body from `<content:encoded>` then `<description>`;
  - Atom: `<entry>`, `<link rel="alternate" href="...">`, `<published>` then `<updated>` in ISO 8601,
    body from `<content>` then `<summary>`.
- Strip tags and unescape entities out of the summary so it is plain text. Redirect resolution is
  **not** this step's job — FR-21 resolves the canonical url at fetch time.
- An entry with no resolvable publication date is **dropped**, with a `decision` trace record naming
  the entry's headline and the reason. An entry with no url is dropped the same way.
- HTTP error, timeout, or unparseable XML raises `AdapterError` carrying the status or reason.
- Every request sends the `[news] user_agent` string from config.
- **Capture fixtures** with the Step 23 `--raw` mode and commit them. Capture at least one real RSS
  2.0 feed and one real Atom feed — Ars Technica is RSS 2.0, The Verge's `/rss/index.xml` is Atom, but
  verify rather than assume. Hand-build `feed_malformed.xml` (one good entry, one entry missing its
  date, one entry missing its link) and record its synthetic provenance in
  `tests/fixtures/README.md`.
- Tests, all off fixtures: correct entry count and normalized fields per shape; `published` is
  timezone-aware and converted to `America/Chicago`; the malformed fixture yields only the good entry
  plus two `decision` records naming the dropped ones; a 500 raises `AdapterError`; a test inspects
  `RecordingTransport.requests` and asserts the configured `User-Agent` was sent on every request.

**Verify:** Done when `uv run pytest tests/test_feeds.py -q` passes, specifically FR-20's criterion:
the RSS fixture, the Atom fixture, and the malformed fixture each yield the correct entry count and
fields, the malformed entry is dropped with a trace record naming it, and the `User-Agent` assertion
holds. Socket guard confirms zero live calls.

**Guardrails:** Adapter only — no fetching of article bodies (Step 26), no chunking, no relevance
judgment about which entries matter. No API key, no paid tier, no news API. Do not add caching; the
scratchpad owns that.

---

### Step 26 — Article body fetch and extraction + fixtures  (implements FR-21)

**Context:** PRD FR-21. This is the step that makes the documents document-shaped: feed summaries are
one chunk, fetched article bodies are 3,233–6,838 characters. Touches `forecaster/tools/feeds.py`.
`robots.txt` on arstechnica.com and techcrunch.com permits the fetch with an identifying agent and
declares no crawl delay, verified 2026-08-04.

**Read this before you build — three things that will bite:**

- **The window filter runs before the fetch, not after.** OpenAI's feed returned **1,108 entries** in
  one request on 2026-08-04. Filtering after fetching would issue a thousand HTTP requests per run.
  FR-21's acceptance criterion (v) tests exactly this.
- **`urllib.robotparser.RobotFileParser.read()` opens its own URL** and bypasses the injected client,
  so the socket guard kills it in tests and it dodges the configured `User-Agent` in production.
  Fetch `robots.txt` **through the injected `httpx.Client`** and hand the text to
  `RobotFileParser.parse(text.splitlines())`.
- **The rate limit must not actually sleep in tests.** Inject the sleep function (or a clock) so the
  suite asserts the delay was requested without spending it.

**Task:** Build the fetch-and-extract path.

- `fetch_article_body(entry, *, client, robots_cache, sleep, config) -> FeedEntry` returning the entry
  with `body` and `text_source` populated.
- Order of operations: filter by `published` within `[news.retrieval] window_days` → check
  `robots.txt` for the host (cached per host per run) → wait `fetch_delay_seconds` since the last
  request to that host → `GET` with the configured `User-Agent`, `follow_redirects=True`, and
  `timeout_seconds` → set `url` to the final redirected url → extract.
- Extraction per the decision rule in the header above. The interface is
  `extract_body(html) -> str` either way.
- **Outcomes, none of which invent text:**
  - extracted body ≥ `min_body_chars` → `text_source = "article"`, `body` = extracted text;
  - extracted body < `min_body_chars` (paywall, truncation, extractor miss) → `text_source =
    "summary"`, `body` = the feed summary **verbatim**;
  - timeout or HTTP error → `text_source = "summary"`, entry **kept**, failure recorded as a
    `decision` in the trace;
  - `robots.txt` disallows → entry **skipped entirely**, with a `decision` record naming the host.
- **Capture fixtures:** one real article page per publisher shape (`article_arstechnica.html`,
  `article_techcrunch.html`), one hand-built `article_paywalled.html` whose extractable body is under
  the floor, and `robots_disallow.txt`. Record synthetic provenance in `tests/fixtures/README.md`.
- Tests, all off fixtures, covering FR-21's five acceptance clauses (i)–(v). For (v), build a
  synthetic feed fixture with 1,108 entries of which 12 fall inside the window, and assert
  `len(recorder.requests)` for article pages is exactly 12.

**Verify:** Done when `uv run pytest tests/test_feeds.py -q` passes all five FR-21 clauses, and the
1,108-entry case asserts exactly 12 article fetches. `uv run pytest -q` stays green overall.

**Guardrails:** Never synthesize a body. Never retry-with-fallback in a way that masks a failure. Do
not ignore `robots.txt`, do not remove the rate limit, do not send a `User-Agent` that misrepresents
the client. Do not add a headless browser or a scraping service. Quote sparingly downstream — PRD §8
sets the copyright posture and this step must not widen it.

---

### Step 27 — Paragraph-aware chunking  (implements FR-22)

**Context:** PRD FR-22. The existing corpus needed no chunking because one delivered line was one
atomic record; articles are the first thing here that genuinely needs it. Touches
`forecaster/memory/corpus.py`. Pure functions, no I/O, no embedder — this step is independently
testable and depends only on Step 24's config.

**Task:** Build the chunker.

- `Chunk` dataclass: `ordinal`, `body_text` (the raw slice), `char_start`, `char_end`, and `text`
  (the embedded/stored form).
- `chunk_article(headline, body, *, target_chars, max_chars, overlap_chars) -> list[Chunk]`.
- **`text` is `f"{headline}\n{body_text}"`; `char_start`/`char_end` index into `body` only and
  exclude the headline prefix.** Keeping the two separate is what makes the round-trip assertion
  below possible, and the headline prefix is what stops a mid-article chunk from retrieving with no
  subject — static embeddings are close to bag-of-words, which the parent build already measured.
- Split on paragraph boundaries (blank-line separated). Accumulate paragraphs until adding the next
  would exceed `max_chars`; aim for `target_chars`. Split a single paragraph internally **only** when
  it alone exceeds `max_chars`, on a sentence boundary if one is available, otherwise on whitespace.
- Each chunk after the first carries `overlap_chars` of the previous chunk's tail as leading context;
  the overlap is part of `body_text` and `text`, and `char_start` reflects it.
- A body at or under `target_chars` yields exactly one chunk.
- Tests: a 6,000-character fixture body yields chunks each at or under `max_chars`; every chunk after
  the first begins with the previous chunk's trailing `overlap_chars`; every chunk's `text` first line
  is the headline; **reconstruction** — walking chunks in ordinal order and taking
  `body[chunk.char_start:chunk.char_end]` with overlapping regions counted once reproduces `body`
  byte for byte; a 400-character body yields exactly one chunk; a single 5,000-character paragraph
  still yields chunks at or under `max_chars`.

**Verify:** Done when `uv run pytest tests/test_corpus.py -q` passes all six cases, with the
byte-for-byte reconstruction assertion green. That assertion is the one that catches an off-by-one in
the overlap arithmetic, which is otherwise invisible until retrieval quality degrades.

**Guardrails:** Pure functions only — no database, no embedder, no network. Do not add a token-based
splitter or a tokenizer dependency; character counts are what the PRD specifies. Do not strip or
normalize the body text beyond what Step 26 already produced.

---

### Step 28 — Article chunk corpus, the second vector collection  (implements FR-23)

**Context:** PRD FR-23. A **separate** SQLite file from `ledger.db`, because the two corpora have
opposite lifecycles: `sent_items` is the permanent record of what was delivered and cannot be rebuilt;
article chunks are disposable and reconstructible from the feeds in one run, and at roughly 1,400
vectors a week would dwarf the ledger's roughly 35. Touches `forecaster/memory/corpus.py`. Reuses the
existing `Embedder` protocol, `load_vec`, and the distance-to-similarity convention from
`forecaster/memory/retrieval.py`.

**Task:** Build the store.

- `data/corpus.db` (gitignored, alongside `ledger.db`), with:
  - `articles(url TEXT PRIMARY KEY, source, headline, published, fetched_at, text_source, body_chars)`
  - `chunks(id INTEGER PRIMARY KEY AUTOINCREMENT, url TEXT REFERENCES articles(url), ordinal, text, char_start, char_end)`
  - a `sqlite-vec` `vec_chunks(chunk_id INTEGER PRIMARY KEY, embedding FLOAT[dim])`
- **Generalize `retrieval.create_vector_schema(connection, dimensions, table="vec_sent_items")`** with
  the existing name as the default, so no current caller changes and the corpus gets
  `table="vec_chunks"`. Reuse `load_vec` unchanged.
- `index_article(conn, entry, chunks, embedder)`: upsert the `articles` row, **delete the url's
  existing `chunks` and their `vec_chunks` rows first**, then insert the new ones. Re-fetching a url
  must not duplicate.
- `purge_expired(conn, *, ttl_days, now)`: delete `articles` whose `fetched_at` is older than the TTL,
  cascading to their chunks and vectors. Called at run start, **before** indexing.
- The embedder is **passed in**, never constructed here — the run builds one `StaticEmbedder` and
  hands the same instance to the ledger retriever and the corpus, so the model loads once.
- Tests: indexing an article writes one `chunks` row and one `vec_chunks` row per chunk; re-indexing
  the same url leaves the chunk count unchanged and the vector count unchanged; an article older than
  `ttl_days` is gone after a purge and its vectors with it; **`ledger.db`'s `sent_items` count is
  unchanged by every one of these operations**; a test asserts the two database paths are distinct
  files and that `corpus.py` never opens `ledger.db`.

**Verify:** Done when `uv run pytest tests/test_corpus.py -q` passes, including the ledger-untouched
assertion and the distinct-file assertion, and `uv run pytest tests/test_ledger.py -q` still passes
unchanged — in particular the existing `ast` guard that no module outside `ledger.py` computes a
content hash or persists a dedup verdict. The corpus stores no verdict either.

**Guardrails:** Do **not** put article chunks in `ledger.db`. Do not add an identity column, a
fingerprint, or a content hash to either store — parent §9 Q3's answer stands: identity is a read-time
relation, not a stored property. Do not add a second embedder or a second model.

---

### Step 29 — Topic-query retrieval over the corpus  (implements FR-24)

**Context:** PRD FR-24. This is the classic-RAG half: a query goes in, passages come out. Touches
`forecaster/memory/corpus.py`. The distance-to-similarity conversion is `1 - d²/2` over unit vectors,
the same as `retrieval.retrieve_neighbours` — **it is easy to get backwards, and backwards means
everything scores as a match.** Parent Step 20's note applies verbatim.

**Task:** Build the retrieval.

- `retrieve_for_topic(conn, query_vector, *, k, similarity_floor, window_days, max_chunks_per_article,
  now) -> list[RetrievedChunk]`, where `RetrievedChunk` carries the chunk text, its article's url,
  source, headline, and `published`, plus the similarity score.
- Over-fetch from the vec table, then filter in SQL by `published >= cutoff`, then apply
  `similarity_floor`, then cap at `max_chunks_per_article` per url, then take the top `k` in
  descending similarity. Order matters: capping before the floor would let a weak second chunk from a
  strong article displace a strong chunk from another.
- An empty result is a normal outcome, not an error. The caller records `topic_empty`.
- **Test-construction constraint:** the suite embeds with `HashingEmbedder`, a hashed bag of words
  whose scores do **not** match the shipped model's. Build fixture corpora so the expected set holds
  under `HashingEmbedder`, and assert **ordering and set membership**, never an absolute similarity
  value.
- Tests: a seeded fixture corpus returns exactly the chunks above the floor in descending similarity;
  never more than `k`; never more than `max_chunks_per_article` from one article (seed an article with
  five near-identical chunks to prove it); never a chunk from an article outside `window_days`; a
  topic matching nothing returns `[]`; an identical-text query against an identical-text chunk scores
  approximately 1.0 (the backwards-conversion canary).

**Verify:** Done when `uv run pytest tests/test_corpus.py -q` passes all six cases, with the
approximately-1.0 canary green and the per-article cap proven against a five-chunk article.

**Guardrails:** **Do not tune `k`, `similarity_floor`, `window_days`, or `max_chunks_per_article`** —
child §9 Q6 is open, the values come from config, and this step ships the PRD's reasoned defaults and
instruments them. Do not add a re-ranker, query expansion, or a BM25 hybrid (PRD §4 non-goals). Do not
let retrieval decide what the item says; it returns passages.

---

### Step 30 — Grounded-text provenance check  (implements FR-26; extends parent FR-11)

**Context:** PRD FR-26. `check_provenance`'s support check runs over declared `checkable_fields`, and
its fidelity check templates `item.text` for **altered** numbers. Neither catches a number the model
**invented** into a synthesized sentence, because both shipped beats build their item text from typed
API fields in code, so that failure could not previously occur. A summary written from a passage is
the first place it can. Touches `forecaster/trace.py`. Build the guarantee **before** the beat it
guards — same reasoning as the parent build putting the provenance checker in Step 6.

**Task:** Grow the checker one case.

- In `check_provenance`, for each `beat_result` item whose `fields["text_origin"] == "synthesized"`,
  gather the payloads of the observations **that item** links to, and:
  - every number in `item.text` must appear in at least one such payload, else a
    `ungrounded_number` violation;
  - every double-quoted span of four characters or more in `item.text` must appear verbatim,
    case-insensitively, in at least one such payload, else `ungrounded_quote`.
- A number counts as grounded if it appears **as digits or as its English word form for 0 through
  20** — a fixed, closed mapping in the module. A model handed "3 papers" may legitimately write
  "three papers", and without this the check fires constantly on correct output.
- Items **without** the flag are untouched. The existing violation kinds, notes, and `ProvenanceReport`
  shape are unchanged.
- Tests with hand-built fixture traces, no beat required: a synthesized item stating a number absent
  from every linked chunk produces exactly one `ungrounded_number` and `report.ok` is False; one whose
  numbers and quotes all appear passes; "three" against a chunk saying "3" passes and "four" against
  "3" fails; a synthesized item quoting a phrase no chunk contains produces `ungrounded_quote`; an
  **unflagged** item containing an unsupported number produces no new violation.

**Verify:** Done when `uv run pytest tests/test_trace.py -q` passes the new cases **and**
`uv run pytest tests/test_synthesizer.py tests/test_tool_failure.py tests/test_beat_astros.py
tests/test_beat_weather.py -q` all pass unchanged — proving the new case is scoped to the flag and the
two existing beats are unaffected.

**Guardrails:** Do not widen the check to unflagged items. Do not soften a violation to a note or a
warning; it fails the run, like every other provenance violation. **The known false-positive mode is
accepted deliberately** — a number the model derives rather than copies fails the run, and the fix
when that happens is to constrain the summary prompt in Step 32, not to loosen this check.

---

### Step 31 — Grounded-value suppression veto  (implements FR-27; transplants parent FR-19 invariant 1)

**Context:** PRD FR-27 and §8. **This is the load-bearing step in the increment.** Parent FR-19's
first invariant forbids suppressing an item whose checkable value differs from its nearest
neighbour's. It assumes a *recurring status item*, where identical wording on a different day means a
genuinely different fact. News inverts that: the same story on a different day **is** the repeat, and
is exactly what should be suppressed. So any per-artifact field in a news item's `fields` disables
dedup for that beat, permanently and invisibly:

- `date`/`as_of` at the run date differs every night → the invariant fires on every item;
- `published` differs whenever tonight's top article is newer than last night's, the normal case;
- `url` differs whenever a second publisher picks up the story, which **is** the
  "three days of *Fable rocks but is expensive*" case this increment exists to fix.

Touches `forecaster/memory/dedup.py`, `tests/test_time_scoped_items.py`.

**Task:** Transplant the invariant from typed fields to grounded prose.

- In `assess_item`, before the existing invariant-1 check, branch on
  `item.fields.get("text_origin") == "synthesized"`. For such an item, compute against the union of
  all neighbours' `rendered_text`:
  - the set of numbers in the candidate's text;
  - the set of double-quoted spans;
  - the set of **proper nouns** — capitalized tokens of three or more characters that are not
    sentence-initial.
  If the candidate introduces any element absent from every neighbour, return a `DedupDecision` of
  `reframe` with `forced=True`, a reason naming what was new, **and the model not consulted**.
  If it introduces none of the three, fall through to the model judgment as normal.
- The existing typed-field invariant 1 continues to run for unflagged items, unchanged.
- Invariants 2 through 5 (escalation never suppressed, unavailability never suppressed, retrieval
  failure degrades to include, everything traced) apply to news items unchanged.
- **Amend `tests/test_time_scoped_items.py` to be registry-driven rather than a hardcoded beat list.**
  The standing assertion becomes: for every registered beat, every item either carries one of
  `DATE_KEYS` **or** declares `text_origin = "synthesized"`; and any item declaring that flag carries
  **none** of `published`, `url`, `source`, `date`, `game_date`, `as_of` in `fields`. Written this way
  the test is vacuously true for the news beat today and covers it automatically the moment Step 32
  registers it — which is better than a list someone has to remember to update.
- Tests in `tests/test_dedup.py`: a news item quoting a benchmark figure no neighbour stated survives
  a cosine-1.0 neighbour with a hard-coded `SUPPRESS` client **never called**; a news item naming an
  entity no neighbour named survives the same way; a news item restating the same story with the same
  figures and entities reaches the model and is suppressible; a sentence-initial capitalized word is
  **not** treated as a new proper noun.

**Verify:** Done when `uv run pytest tests/test_dedup.py tests/test_time_scoped_items.py -q` passes,
with the suppressor client's call count asserted at **0** for both forced cases. An invariant that can
be talked out of is not an invariant. The four existing time-scoped cases for the Astros and weather
beats must still pass.

**Guardrails:** Do not remove or weaken parent FR-19's typed-field invariant for the existing beats.
Do not give news items a date, url, or source field to "make the existing test pass" — that is the
exact bug this step prevents. If the veto over-fires in practice the digest repeats itself, which the
trace records and which is the **correct-side error**: this project's stated position is that going
quiet is worse than repeating.

---

### Step 32 — News beat worker  (implements FR-25)

**Context:** PRD FR-25. One class plus one config entry, with zero edits to `planner.py`,
`synthesizer.py`, or `delivery/` — the seam the parent FR-2 exists to protect, asserted mechanically
by the `ast` test in `tests/test_cli.py`. Touches `forecaster/beats/news.py`, `config.toml`. Every
piece it needs now exists.

**Two wiring details the beat cannot work without — name them in `BUILD-LOG.md`:**

- **`BeatContext` has no embedder.** It carries config, preferences, now, scratchpad, trace, and
  `http_client`, and nothing else. Add an optional `embedder: Any = None` field to `BeatContext` in
  `beats/base.py`. This is additive, breaks no existing beat, and is **not** a violation of FR-2's
  seam — `base.py` is the contract, not one of the three modules the `ast` test polices. The
  alternative, having the beat construct its own `StaticEmbedder`, would load the model twice per run
  and would reach for the network inside the test suite.
- **`cli.py` is edited, and that is fine.** FR-25's "zero edits" clause names `planner.py`,
  `synthesizer.py`, and `delivery/` specifically. The runner already builds the `StaticEmbedder` and
  the ledger retriever for FR-9b; it now also opens `corpus.db` and passes the **same embedder
  instance** into `BeatContext`. If you find yourself editing one of the three named modules, stop.

**Task:** Assemble the beat.

- `NewsBeat` implementing the `Beat` protocol: `name = "news"`, `should_run(context)` from config
  enablement, `run(context) -> BeatResult`. Register it, and add it to `load_builtin_beats()`.
- Run sequence, each stage recorded in the trace as a `tool_call` plus its `observation`:
  1. purge the corpus (Step 28) of entries older than `ttl_days`;
  2. fetch each configured feed (Step 25);
  3. filter to the publication window, then fetch and extract bodies (Step 26);
  4. chunk (Step 27) and index (Step 28), using the **same embedder instance** the run already built
     for the ledger retriever;
  5. for each configured topic, retrieve (Step 29) and emit one `BeatItem`, or record `topic_empty`.
- **Each retrieved chunk is written to the trace as its own observation**, and the item's
  `observations` list carries those observation ids. This is what makes FR-26's check computable and
  §2(b)'s attribution metric non-vacuous.
- The item's `text` is written by the **injected** agent client from the retrieved chunks only, with a
  prompt that instructs it to reuse figures verbatim, to quote sparingly, and to name the source. It
  carries `fields = {"topic": <id>, "text_origin": "synthesized"}` and **nothing else** — no date, no
  url, no source, per Step 31.
- `escalation_candidate` is always `False`. Parent §9 Q2 is open and news contributes no rule.
- Flip `[beats] news = true` in `config.toml`.
- Tests off fixtures with `FakeAgentClient` and `HashingEmbedder`: one item per non-empty topic; every
  item's `observations` non-empty and every id resolving to an observation in the same trace; a run
  through the full pipeline passes `check_provenance` including Step 30's new case; disabling
  `[beats] news` returns the digest to its two-beat shape with nothing else changed.

**Verify:** Done when `uv run pytest -q` passes the whole suite, **including the existing
`test_adding_the_dummy_beat_required_no_edit_to_planner_synthesizer_or_delivery` `ast` test with the
news beat registered and enabled** — that test passing is FR-25's acceptance, not a formality. Confirm
by inspection that `git diff` for this step touches no file under `forecaster/delivery/` and neither
`planner.py` nor `synthesizer.py`.

**Guardrails:** If the beat seems to need a change to the planner, synthesizer, or delivery, **stop** —
that is the seam failing and it is a design problem, not a step to push through. No escalation rule.
No story clustering. The model phrases what retrieval found; it never originates a figure. If Step
30's check starts firing on legitimate output, constrain this prompt, do not loosen the check.

---

### Step 33 — Per-source failure handling  (implements FR-28; extends parent FR-18)

**Context:** PRD FR-28. Parent FR-18 is binary — a beat is available or it is not — because both v1
beats make one API call. The news beat reads five feeds, so it can be **partially** available, and a
partial failure is currently invisible to `check_provenance` (its `missing_unavailability_line` case
only fires for `available=False`). Touches `forecaster/beats/news.py`, `forecaster/trace.py`.

**Task:** Make a partial failure impossible to hide.

- Every feed or article failure is recorded as a `decision` of type `source_unavailable` naming the
  source and the error.
- The beat emits an explicit line naming each failed source, and carries items built only from the
  sources that worked. **No substitute content for a source that failed.**
- `check_provenance` gains an `unnamed_failed_source` violation: for every `source_unavailable`
  decision in the trace, the digest must name that source. Same shape and severity as the existing
  `missing_unavailability_line`.
- When **every** configured feed fails, the beat returns `BeatResult.unavailable(...)` and the
  existing FR-18 path handles it unchanged — no new mechanism for the total-failure case.
- Tests: a fixture set where two of five feeds 500 produces a digest naming **both** failed sources,
  carrying items from the three that worked, and containing no invented content for the two; all five
  failing produces the standard FR-18 unavailability line and no news content; a hand-built trace
  whose digest omits a failed source produces exactly one `unnamed_failed_source` violation.

**Verify:** Done when `uv run pytest tests/test_tool_failure.py tests/test_trace.py -q` passes the
three cases, and the two-of-five run's `check_provenance` reports zero violations while the
digest-omits-a-source case reports exactly one.

**Guardrails:** No retry that masks a failure, no cached-from-yesterday substitute, no "based on
recent coverage" hedge. A source that failed is named, and that is the correct output. Do not change
parent FR-18's behavior for the two existing beats.

---

### Step 34 — News-beat metric checker  (implements FR-29)

**Context:** PRD §2 and FR-29. The four success conditions must be computable from
`data/runs/*.jsonl` with no other input, so they are checkable rather than a matter of opinion —
the same standard parent §2(a) set. Touches `forecaster/trace.py`, `forecaster/cli.py`.

**Task:** Build the checker and expose it.

- `check_news_metric(trace_paths) -> NewsMetricReport` computing:
  - **(a)** zero `ungrounded_number` and zero `ungrounded_quote` across all runs;
  - **(b)** every delivered news item carries at least one chunk observation id and every one
    resolves to an `observation` record in the same trace — zero orphans, zero empty sets;
  - **(c)** at least one news item suppressed or reframed, with neighbours, scores, and reason in the
    trace, **and the count of nights accumulated so far**;
  - **(d)** `items_assessed == items_delivered + dedup_suppressed + preference_suppressed`, with a
    recorded reason on every suppression on either path, and a reframed item counted as delivered.
- A CLI subcommand printing the report per condition, pass or fail, with the failing detail.
- **Condition (c) must report "N of 14 nights accumulated" and never report itself met before the
  nights exist.** It also must not count a seeded ledger — the whole point of §2(c) and DIVERGENCES
  row 4 is that the history is organic. If the checker cannot tell seeded from organic, say so in the
  report rather than assuming.
- Tests: an all-pass fixture trace set; four fixture sets each violating exactly one condition, each
  reporting that condition and only that one; a single-run set reports (a), (b), (d) and reports (c)
  as "1 of 14 nights".

**Verify:** Done when `uv run pytest tests/test_news_metric.py -q` passes all six cases, and
```powershell
uv run python -m forecaster.cli --news-metric
```
prints a per-condition report against whatever traces exist locally without erroring on an empty
`data/runs/`.

**Guardrails:** Reporting only — the checker changes no behavior and gates no run. Do not let it
report (c) as met on a seeded ledger or before 14 nights. Do not add a quality, relevance, or
"is the summary good" measure; PRD §2 rules those out as opinions.

---

# Coverage

| FR | Phase | Step(s) | Where its acceptance is actually asserted |
|---|---|---|---|
| FR-20 Feed adapter | MVP | 25 | Step 25 (`test_feeds.py`, RSS + Atom + malformed + User-Agent) |
| FR-21 Article fetch | MVP | 26 | Step 26 (five clauses; 1,108 entries → 12 fetches) |
| FR-22 Chunking | MVP | 27 | Step 27 (`test_corpus.py`, byte-for-byte reconstruction) |
| FR-23 Chunk corpus | MVP | 28 | Step 28 (re-index idempotent, TTL purge, ledger untouched) |
| FR-24 Topic retrieval | MVP | 29 | Step 29 (ordering, caps, window, ~1.0 canary) |
| FR-25 News beat worker | MVP | **32** | Step 32 (the `ast` seam test, green with news enabled) |
| FR-26 Grounded-text provenance | MVP | **30** | Step 30 (`test_trace.py`, scoped to the flag) |
| FR-27 Suppression veto | MVP | **31** | Step 31 (`test_dedup.py`, model call count 0) |
| FR-28 Per-source failure | MVP | **33** | Step 33 (two-of-five named; five-of-five → FR-18 path) |
| FR-29 Metric checker | MVP | **34** | Step 34 (`test_news_metric.py`, one fixture per condition) |
| — Text/bytes fixtures | infra | 23 | Step 23 (XML + HTML served, 265 existing tests unchanged) |
| — News config | infra | 24 | Step 24 (every validation rule has a raising case) |

**No MVP FR is uncovered, and none is withheld** — unusually for this project, no §9 open question
blocks a requirement this increment. Q2, Q5, Q6, and child Q4 constrain *how* steps are built (see the
table at the top) rather than *whether* they can be.

Two conditions end outside the build by design: **§2(c)'s 14 nights** needs HUMAN-TODO ④, and
**Q6's thresholds** need those nights plus Sarah's judgment. Step 34 reports progress toward the first
and must never claim either is met.

# What this increment closes

- **DIVERGENCES row 6** — the Checkpoint 3 forward commitment, *"Retrieval of the classic kind arrives
  with the AI news beat, where the documents are articles."* Retires when Step 32 lands, because
  FR-24 makes retrieval ground the prose rather than only select it.
- **DIVERGENCES row 4** — FR-9b's seeded-ledger demonstration. Retires only when §2(c) is met on
  organic history, which is Step 34's report, not Step 32's merge. **Do not mark row 4 closed at
  merge.**

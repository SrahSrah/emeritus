# PRD: Forecaster

**Project:** emeritus (capstone) · **Status:** Draft · **Feature ID:** `forecaster` · **Target path:** `emeritus/forecaster/`

## 1. Problem & why now

Sarah removed social media and, with it, her whole information intake. The optimal amount of
information to consume is not zero: she now misses AI news, Astros results, and weather that
changes what she wears on a 6 am run. A general chatbot can't fill the gap — it has no access to
last night's score or tomorrow's forecast, and it will fabricate both rather than admit it doesn't
know.

Why now: this is the build half of an Emeritus AI capstone. Checkpoints 1.1 and 2.x are submitted
and describe this agent's architecture; a new written checkpoint is due roughly weekly for several
more weeks. The code needs to exist to write credibly about, and it needs to absorb requirements
that haven't been announced yet.

## 2. Goal & success metric

- **Goal:** A nightly digest that tells Sarah exactly what she needs to know, where every checkable
  fact came from a tool call rather than from a language model's memory.
- **Success metric:** Across 14 consecutive nights:
  - **(a) Provenance — the load-bearing one.** **Zero** checkable claims (scores, game state,
    temperature, wind, precipitation) appear in any digest without a matching tool observation in
    that run's trace. Machine-checkable over the run ledger; a single violation fails the metric.
  - **(b) Delivery.** Of runs that fire, ≥95% deliver within 5 minutes of 7 pm CT. Runs that never
    fire (laptop asleep) are counted separately as *missed*, not as failures of the pipeline — the
    two have different fixes.
  - **(c) Honest degradation.** Every night an upstream API fails, the digest says so explicitly and
    contains no substitute value.

Metric (a) is what the capstone actually argues for, and it is checkable rather than a matter of
opinion. Note that "no repeats" is deliberately **not** a v1 metric — see FR-9b.

## 3. Users & job-to-be-done

One user: Sarah. The job is "keep me informed enough to make today's decisions without putting me
back on a feed." Secondary job, real but subordinate: produce a system whose design decisions are
worth writing about each week.

## 4. Scope

**In scope (v1):**
- Two beats: Astros game state, and next-morning Austin weather.
- Planner → per-beat ReAct workers → synthesizer pipeline.
- Short-term scratchpad; long-term sent-item ledger.
- Rules-based escalation (freeze alert, injury to a watched player).
- Email delivery, nightly at 7 pm CT.
- A run trace rich enough for a later evaluation module to analyze.

**Out of scope / non-goals:**
- The other four beats (AI news, r/WallStreetBets, need-to-know news, live music) — deliberately
  deferred; they are the FR-Later queue that feeds the coming weeks.
- SMS delivery. The submitted checkpoints promise SMS; v1 ships email. See §9.
- Any web UI or dashboard. This is a cron job that sends a message.
- Learned/embedding-based preference modelling. The profile is a rules file a human edits.
- Multi-user support, accounts, or anything resembling a product.

## 5. Functional requirements

- **FR-1 — Config-driven run** `[MVP]`
  - **Requirement:** All run parameters — enabled beats, location, delivery target, send time,
    escalation rules, watched-player list — live in a single `config.toml`, not in code.
  - **Acceptance:** Done when disabling a beat, changing the city, or adding a watched player
    requires editing only `config.toml`, proven by a test that runs the pipeline twice with two
    configs and asserts different beat sets executed.
  - **Touches:** `forecaster/config.py`, `config.toml`

- **FR-2 — Beat interface** `[MVP]`
  - **Requirement:** Every beat implements one `Beat` protocol (`name`, `should_run(context)`,
    `run(context) -> BeatResult`). The planner and synthesizer know only the protocol.
  - **Acceptance:** Done when a new beat can be added by writing one class and one config entry,
    with zero edits to planner, synthesizer, or delivery code — proven by a test that registers a
    dummy beat and sees it in the output.
  - **Touches:** `forecaster/beats/base.py`

- **FR-3 — MLB Stats API adapter** `[MVP]`
  - **Requirement:** A client for `statsapi.mlb.com` returning, for a given date and team, each
    game's `abstractGameState`, UTC start time, score, and per-game ID — normalized into a typed
    object, with UTC converted to the configured local timezone.
  - **Acceptance:** Done when, given a recorded fixture containing a doubleheader and an in-progress
    game, the adapter returns the correct game count, states, and localized start times.
  - **Touches:** `forecaster/tools/mlb.py` (verified live 2026-07-26: free, no key)

- **FR-4 — NWS weather adapter** `[MVP]`
  - **Requirement:** A client for `api.weather.gov` returning the hourly forecast covering the next
    morning's run window for the configured grid point, including temperature and precipitation.
  - **Acceptance:** Done when, given a lat/long, the adapter resolves the grid point and returns a
    forecast covering 5–8 am local; a test asserts the required `User-Agent` header is sent, since
    NWS rejects requests without it.
  - **Touches:** `forecaster/tools/weather.py` (verified live 2026-07-27: Austin = EWX 156,91)

- **FR-5 — Astros beat worker (ReAct loop)** `[MVP]`
  - **Requirement:** A worker that calls the schedule first and branches on the returned game state:
    *final and none tonight* → report final, preview next; *tonight in progress* → report last
    completed game and flag tonight live with its current score; *no game* → say so briefly. It
    decides whether it has enough or needs another call.
  - **Acceptance:** Done when three fixtures (final-only, in-progress, no-game) each produce the
    correct branch, asserted on the structured `BeatResult` rather than on prose.
  - **Touches:** `forecaster/beats/astros.py`

- **FR-6 — Weather beat worker** `[MVP]`
  - **Requirement:** A worker that produces the run-window forecast and evaluates the freeze
    threshold from config.
  - **Acceptance:** Done when a fixture below the threshold yields a `BeatResult` with
    `escalation_candidate=True`, and one above yields `False`.
  - **Touches:** `forecaster/beats/weather.py`

- **FR-7 — Planner** `[MVP]`
  - **Requirement:** Reads date, day of week, and the preference profile; decides which beats run
    tonight and what "done" means for each. Performs no research itself.
  - **Acceptance:** Done when the planner emits a run plan naming each beat and its completion
    criterion, and a test confirms it makes zero tool calls.
  - **Touches:** `forecaster/planner.py`

- **FR-8 — Per-run scratchpad (short-term memory)** `[MVP]`
  - **Requirement:** Each worker gets a scratchpad recording what it searched, what it found, and
    what is still missing. Discarded once the digest sends.
  - **Acceptance:** Done when a worker that would repeat an identical tool call within one run is
    served from the scratchpad instead, asserted by counting adapter invocations.
  - **Touches:** `forecaster/memory/scratchpad.py`

- **FR-9 — Sent-item ledger, write path** `[MVP]`
  - **Requirement:** Every item included in a delivered digest is durably recorded with its beat,
    timestamp, rendered text, and source observation. Write-only in v1 — nothing reads it to make
    decisions yet.
  - **Acceptance:** Done when a completed run appends one ledger row per delivered item, and a
    second run appends its own rows without collision.
  - **Touches:** `forecaster/memory/ledger.py`, SQLite at `forecaster/data/ledger.db`
  - **Amended 2026-08-02:** no longer write-only. FR-9b reads it. The row also carries
    `checkable_fields` — the observed values the line stated — because FR-19's first invariant
    cannot be checked without them. Still **no identity column**: see §9 Q3's answer.

- **FR-9b — Retrieval-backed dedup / "what's new" framing** `[MVP]`
  - **Requirement:** Before an item is included, embed it and semantically search the ledger for the
    `k` nearest previously-delivered items from the same beat inside a configured window. Retrieval
    finds candidates; a model judgment decides include / reframe / suppress. The check is a judgment
    about whether the item adds anything to what the reader already knows — not string equality, and
    not a similarity threshold.
  - **Acceptance:** Done when a fixture pair representing the same story on consecutive nights
    produces a suppression or a reframe, with the decision and its reason in the run trace.
  - **Touches:** `forecaster/memory/retrieval.py`, `forecaster/memory/dedup.py`,
    `forecaster/synthesizer.py`
  - **Unblocked 2026-08-02** by the answer to §9 Q3. Implemented, tested, and shipped in the
    Module 3 increment.

- **FR-19 — Retrieval safety invariants (no silent suppression)** `[MVP]`
  - **Requirement:** Five invariants hold whatever the embedding scores and whatever the model says,
    enforced *around* the model rather than requested of it: (a) an item whose checkable value
    differs from its nearest neighbour's recorded value may be reframed but **never** suppressed;
    (b) an escalation candidate is never suppressed; (c) an empty neighbour set means "nothing
    known", not "nothing new"; (d) any retrieval or judgment failure degrades to *include*;
    (e) every retrieval, its neighbours, their scores, the action and its reason are written to the
    run trace.
  - **Rationale:** static embeddings are near-blind to numerals — two different Astros games score
    **cosine 0.9859** on the shipped model. A threshold-only design would drop tonight's real result.
    For an agent whose only promise is that its facts are real, going quiet is a worse failure than
    repeating, and much harder to notice.
  - **Acceptance:** Done when a candidate whose score differs from a 0.98-similar neighbour survives
    the check with the model never consulted, asserted on the structured decision; and when a broken
    retriever still produces a delivered digest with the failure named in the trace.
  - **Amended 2026-08-02 (time-scoped items).** Invariant (a) fires on a *differing value*, so an
    item about a particular day must carry that day in `BeatItem.fields` or the invariant cannot
    fire: two off days, or two different games sharing a scoreline inside the retrieval window,
    otherwise look identical and reach the model as candidates for suppression. Every shipped beat
    now carries a date (`morning`, `game_date`, `date`, `as_of`), enforced by
    `tests/test_time_scoped_items.py`. Note this is `BeatItem.fields`, which dedup compares, not
    `BeatResult.checkable_fields`, which FR-11 polices; the two are deliberately separate.
  - **Amended 2026-08-04 (invariant 1 does not generalize to document-shaped beats).** The date rule
    above assumes a *recurring status item*, where identical wording on a different day means a
    genuinely different fact. A news item inverts that: the same story on a different day **is** the
    repeat, so any per-artifact field in its `fields` — run date, publication date, or url — makes
    invariant 1 fire every night and silently disables dedup for that beat. The child spec's **FR-27**
    transplants the invariant from typed fields to grounded prose (veto on a new number, quoted phrase,
    or proper noun) and exempts `text_origin="synthesized"` items from the date guard. Read FR-27 before
    adding any beat whose item text is model-written rather than assembled in code.
  - **Touches:** `forecaster/memory/dedup.py`, `forecaster/beats/astros.py`

- **FR-10 — Escalation rules engine** `[MVP]`
  - **Requirement:** Deterministic rules over `BeatResult`s promote items to the top of the digest.
    v1 rules: freeze alert within N days; any injury to a configured watched player.
  - **Acceptance:** Done when a run containing one escalation candidate produces a digest whose
    first item is that candidate, asserted on the ordered structure.
  - **Touches:** `forecaster/escalation.py`

- **FR-11 — Synthesizer** `[MVP]`
  - **Amended 2026-08-02:** "applies the ledger check" is now literally true — that check is FR-9b,
    and it runs between suppression and escalation ordering. The synthesizer still opens no database
    and names no table: the retriever is injected, and `retriever=None` is exactly the v1 pipeline.
  - **Requirement:** Collects all `BeatResult`s, applies the ledger check and escalation ordering,
    and composes the final message. Every checkable value it emits is copied from a `BeatResult`
    field — the model phrases, it does not originate.
  - **Acceptance:** Done when a provenance test asserts that every value in a `BeatResult`'s declared
    `checkable_fields` (scores, game state, temperature, wind, precipitation probability) appears in
    the rendered digest **only if** it matches the observation it came from. Scoped to declared
    fields rather than "every number" — inning counts, dates, and "6 am" are prose, not claims.
  - **Touches:** `forecaster/synthesizer.py`

- **FR-12 — Delivery interface + email implementation** `[MVP]`
  - **Requirement:** A `Deliverer` interface with one `send(digest)` method and an SMTP
    implementation. Credentials come from a gitignored `.env`.
  - **Acceptance:** Done when the digest arrives in Sarah's inbox from a real run, and a fake
    deliverer lets the full pipeline be tested without sending anything.
  - **Touches:** `forecaster/delivery/base.py`, `forecaster/delivery/email.py`

- **FR-13 — Run trace / ledger of runs** `[MVP]`
  - **Requirement:** Every run writes a structured trace: per beat, the plan, each tool call and its
    observation, each decision with its reason, timings, and token usage. Records more than v1
    consumes, on purpose.
  - **Acceptance:** Done when a completed run produces a trace file from which the §2 provenance
    check can be computed with no other input.
  - **Touches:** `forecaster/trace.py`, `forecaster/data/runs/`

- **FR-14 — Nightly scheduler** `[MVP]`
  - **Requirement:** The pipeline runs unattended at 7 pm CT via Windows Task Scheduler, with
    `CLAUDE_CODE_OAUTH_TOKEN` set and `ANTHROPIC_API_KEY` explicitly unset in the job environment.
  - **Acceptance:** Done when three consecutive scheduled runs complete without manual intervention
    and the traces confirm subscription auth was used.
  - **Touches:** `scripts/run_nightly.ps1`

- **FR-15 — Preference profile (read-only)** `[MVP]`
  - **Requirement:** A human-edited rules file the planner and synthesizer read (topic weights,
    watched players, suppressions).
  - **Acceptance:** Done when adding a suppression rule removes a matching item from the next digest.
  - **Touches:** `forecaster/memory/preferences.py`, `preferences.toml`

- **FR-18 — Tool-failure handling (no-fabrication guarantee)** `[MVP]`
  - **Requirement:** When an adapter errors, times out, or returns an unparseable payload, the beat
    yields a `BeatResult` marked unavailable carrying the error. The synthesizer renders an explicit
    "couldn't reach X tonight" line. The model is never asked to fill the gap, and a failed beat
    never silently drops out of the digest.
  - **Acceptance:** Done when a fixture that 500s on the MLB call produces a digest containing an
    explicit unavailability line and **no** score, asserted by the FR-11 provenance test passing on
    that run.
  - **Touches:** `forecaster/beats/base.py`, `forecaster/synthesizer.py`

- **FR-16 — Reply-driven feedback loop** `[Later]`
  - **Requirement:** Replying to the digest in plain English is parsed into a durable preference
    rule appended to the profile.
  - **Acceptance:** Done when replying "less WSB, more on the bullpen" produces a corresponding rule
    and the next digest reflects it.

- **FR-17 — Remaining four beats** `[Later]`
  - **Requirement:** AI/Claude news, r/WallStreetBets mention volume, need-to-know news, Austin live
    music — each a `Beat` implementation plus a config entry.
  - **Acceptance:** Done when each is added without modifying planner, synthesizer, or delivery.
  - **Amended 2026-08-04 — the AI/Claude news beat is specced separately.** It is no longer `[Later]`
    here: it has its own child spec at [`docs/prd/ai-news-beat/PRD.md`](../ai-news-beat/PRD.md), which
    owns **FR-20 … FR-29**. It is broken out because it is the only one of the four that carries a
    submitted forward commitment (DIVERGENCES row 6: *"Retrieval of the classic kind arrives with the
    AI news beat, where the documents are articles"*), and because it is the first beat whose items are
    model-synthesized from retrieved passages rather than assembled from typed API fields — which
    requires FR-11's provenance check to grow a case (child FR-26) and FR-19's first invariant to be
    transplanted from typed fields to grounded prose (child FR-27). The other three — r/WallStreetBets,
    need-to-know news, Austin live music — stay `[Later]` under this requirement, unspecced.
  - **Amended 2026-08-14 — need-to-know news is specced separately.** Child spec at
    [`docs/prd/need-to-know-news/PRD.md`](../need-to-know-news/PRD.md), which owns **FR-31 onward**.
    It is broken out because its defining behaviour inverts the other beats' — they report what they
    find; it must suppress nearly everything — and because its bar ("higher than the daily
    drudgery") lands directly on §9 Q2, which stays open. The child therefore specs an
    **observation-only** increment (mechanical corroboration counting with full provenance, no
    digest content) and defers the bar as its FR-36, explicitly blocked on Q2. r/WallStreetBets and
    Austin live music remain `[Later]` here, unspecced. *Later the same day, Sarah answered Q2 for
    this beat by interview and the child's FR-36 and FR-38 … FR-41 spec the bar as buildable v5 —
    see the child's §9 Q2 and the Q2 note below. FR-37 is the within-run dedup fix, numbered in the
    ai-news-beat spec where it shipped.*
  - **Amended 2026-08-16 — live music/theatre is specced separately, re-scoped.** Child spec at
    [`docs/prd/venue-listings/PRD.md`](../venue-listings/PRD.md), which owns **FR-42 … FR-47**.
    Sarah re-scoped the promised beat from discovery ("live music in Austin") to **named-venue
    listings** ("what's playing in the next two weeks at Bass Concert Hall and ZACH Theatre"),
    with dedup deliberately off for it — repeats are the point of a standing listing. v1 is
    ZACH-only (measured: ZACH is a clean keyless scrape; Bass's sites WAF-block the identifying
    client, and the Ticketmaster fallback is gated on a developer account whose signup failed
    2026-08-16 — child FR-47 `[Later]`). Only **r/WallStreetBets** now remains `[Later]` here,
    unspecced.
  - **Amended 2026-08-24 — r/WallStreetBets is specced separately, and FR-17 is now fully
    delegated.** Child spec at [`docs/prd/wsb-beat/PRD.md`](../wsb-beat/PRD.md), which owns
    **FR-48 … FR-52**. The framing decision is the spec: Checkpoint 1's "stock market picks"
    cannot survive the honesty rules (a pick is a judgment the model would have to originate,
    and adjacent to investment guidance this project will not give), so the beat is
    **mention-volume reporting** — the framing Checkpoints 2/3/5 already put on the record —
    counted in code from the one keyless path that measured open (`.rss`, Atom, 25 hot posts;
    the JSON endpoints 403). Structured and venues-shaped: zero model calls, counts as
    `checkable_fields`, a counts-not-picks invariant enforced by test (child FR-51). Nightly
    hot with a nightly item, per Sarah's 2026-08-24 interview; the checkpoints' "this week"
    phrasing is tracked as the child's §9 Q2. With this, all four FR-17 beats have child
    specs; this requirement closes when the wsb build increment merges (DIVERGENCES row 10).

## 6. Technical & data notes

- **Runtime:** Python 3.12, `uv` for dependency management.
- **Agent layer:** `claude-agent-sdk` (Python), authenticated via `CLAUDE_CODE_OAUTH_TOKEN` against
  Sarah's Claude subscription. Agent SDK usage currently draws from subscription usage limits (the
  announced separate Agent-SDK credit is paused as of 2026-06-15). `ANTHROPIC_API_KEY` **must be
  unset** in the job environment — if set, it shadows the OAuth token and silently bills per-token.
- **Model/effort:** default `effort: "low"` for routine beats; the nightly run shares rolling-window
  limits with interactive Claude Code use.
- **Framework portability:** beat logic lives in plain functions the agent layer calls. A future
  module mandating LangGraph or CrewAI touches `planner.py` and the runner, not the beats.
- **External services:** `statsapi.mlb.com` (no key), `api.weather.gov` (no key, `User-Agent`
  required). Neither needs a paid signup.
- **Storage:** SQLite for the ledger; JSON-lines for run traces. Both local, both gitignored.
- **Retrieval (added 2026-08-02):** `model2vec` static embeddings (`minishlab/potion-retrieval-32M`,
  512-dim) with a `sqlite-vec` index inside the existing `ledger.db`. Chosen over
  `sentence-transformers` because it needs no torch — a multi-gigabyte install for a nightly job
  that embeds a handful of one-line items is not a trade worth making — and over a hosted embeddings
  API because that would be a paid signup and would send the digest off the machine. Model weights
  are fetched once to the local HF cache; the `Embedder` protocol keeps that out of the tests.
- **Testing:** recorded HTTP fixtures — no live network in the test suite. The embedder is injected
  for the same reason the agent client is: `HashingEmbedder` is deterministic and offline, and
  reproduces the numeral collision the real model has.

## 7. Dependencies

- Claude Pro/Max subscription with a valid `CLAUDE_CODE_OAUTH_TOKEN`.
- An SMTP account with an app password, in a gitignored `.env`.
- A machine awake at 7 pm CT (this laptop) — or the run silently doesn't happen.

## 8. Risks & edge cases

- **`statsapi.mlb.com` is an undocumented public endpoint** under MLB's copyright terms. Fine for a
  personal capstone; it could change shape or rate-limit without notice. The adapter must fail
  loudly into the trace rather than emit a plausible score.
- **Offseason.** From November to March there are no games. The Astros beat must degrade to
  "no games" rather than error, and the demo value of the centerpiece drops — worth knowing before
  a later checkpoint leans on it.
- **Doubleheaders and rainouts** produce more or fewer games than expected; FR-3's acceptance
  covers the doubleheader case explicitly.
- **NWS rejects requests without a `User-Agent`** — a silent 403 that looks like an outage.
- **Missed run.** Laptop asleep at 7 pm means no digest and no error. The trace should record
  intended-but-missed runs so the §2 delivery metric is honest.
- **Escalating everything is the same as escalating nothing** — if rules fire most nights, the
  ordering carries no signal. Worth watching in the first two weeks.
- **Subscription limit exhaustion** from heavy daytime Claude Code use could starve the nightly run.

## 9. Open questions

Downstream must not invent answers to these.

1. ~~**SMS divergence.**~~ **Resolved 2026-08-02.** Framed as a deliberate scope cut and
   acknowledged in Checkpoint 3: real SMS needs Twilio plus A2P 10DLC registration — paperwork and a
   multi-day approval outside Sarah's control — and email makes FR-16's reply-based feedback loop
   work natively instead of needing a webhook. DIVERGENCES row 1 is closed.
2. **Rules vs judgment for escalation** — carried forward from the Assignment 2 submission, still
   open. **Partially informed 2026-08-02:** FR-9b settled the same question for *dedup* by splitting
   it — retrieval narrows mechanically, the model judges, and safety invariants bound what the
   judgment is allowed to do. Whether that split transfers to escalation is untested and still open.
   **Further narrowed 2026-08-14:** Sarah transferred the split to the need-to-know beat's
   *importance bar* by structured interview (child PRD §9 Q2), with the uncertainty default
   deliberately inverted to suppress. Escalation itself remains rules-only — the child's watchlist
   rule (`need_to_know_watchlist`) is deterministic on purpose, so this question stays open for
   escalation while now being answered for selection.
3. ~~**Item identity for the ledger.**~~ **Answered 2026-08-02 by Sarah:** *item identity is not a
   property of an item; it is a relation computed at read time between a candidate and what has
   already been sent.* Hence no identity column, no fingerprint, no content hash — a stored key would
   freeze a judgment that only makes sense in context. FR-9b implements the read-time comparison.
4. **Unknown syllabus.** Modules 4+ are unannounced. The architecture is built for additive change
   (FR-2, FR-13) rather than for specific anticipated requirements, because guessing them would be
   fabrication. Module 3 (RAG) landed as FR-9b/FR-19 with no change to the beat contract, which is
   some evidence the bet is paying.
5. **New — retrieval thresholds are unvalidated in the wild.** `k = 5`, `similarity_floor = 0.60`,
   `window_days = 14` are reasoned defaults, not measured ones. Nothing has run against a real
   multi-week ledger. The trace records every neighbour and score specifically so these can be tuned
   from evidence later; do not treat them as settled. **Still open 2026-08-04:** the AI news beat
   generates the repeat traffic that makes measuring them possible, but producing traffic is not
   measuring it, and the measurement needs the nights that HUMAN-TODO ④ gates.
6. **New — the news beat's *corpus* retrieval has its own unmeasured thresholds.** `k = 6`,
   `similarity_floor = 0.35`, `window_days = 3`, `max_chunks_per_article = 2`, specified in
   [`docs/prd/ai-news-beat/PRD.md`](../ai-news-beat/PRD.md) §9 Q6. A **sibling** of Q5, not an answer
   to it: Q5 is about comparing a candidate line to past lines, Q6 is about matching a topic query to
   article chunks, and the two are different retrieval problems with different natural floors.
7. **New — the need-to-know beat's *corroboration* thresholds are unmeasured.** `floor = 0.55`,
   `window_days = 2`, specified in
   [`docs/prd/need-to-know-news/PRD.md`](../need-to-know-news/PRD.md) §9 Q1. A third sibling, not an
   answer to Q5 or Q6: this one matches same-story chunks against each other across outlets, which
   is yet another retrieval problem with its own natural floor. The child's FR-35 exists to measure
   it before anything consumes it. **Partially answered 2026-08-20:** the floor was measured over
   three live nights and moved 0.55 → **0.35** — the reasoned value made the two-source gate
   structurally dead; cross-outlet same-story prose is looser than line-vs-line reasoning assumed.
   First threshold in the Q5/Q6/Q7 family to graduate from reasoned to measured (child §9 Q1 has
   the numbers). Q5 and Q6 remain unmeasured.

## 10. Phasing

- **v1 (MVP):** FR-1 … FR-9, FR-10 … FR-15, FR-18 — two beats, end to end, delivered, traced, and
  honest when a tool fails. **Shipped 2026-07-27.**
- **v2 (Module 3 increment):** FR-9b + FR-19 — retrieval-backed dedup and the safety invariants that
  keep it from silencing a real fact. **Shipped 2026-08-02.**
- **Later:** FR-16 (feedback loop), FR-17 (remaining four beats). FR-17's AI-news beat is where
  repetition actually becomes frequent, so it is also where FR-9b's thresholds get their first real
  workout — see §9 Q5.

## 12. Changelog

- **v2 — 2026-08-02:** Module 3 increment. §9 Q3 answered (item identity is a read-time relation,
  not a stored property), which unblocked **FR-9b** — promoted `[Later]` → `[MVP]` and rewritten
  around semantic retrieval rather than an unspecified "check". Added **FR-19** (retrieval safety
  invariants) because the measured 0.9859 cosine between two different games makes silent
  suppression a real risk rather than a theoretical one. FR-9 amended: the ledger is no longer
  write-only and carries `checkable_fields`. §9 Q1 resolved (email, acknowledged in Checkpoint 3);
  §9 Q2 partially informed; §9 Q5 added (thresholds unvalidated). §10 gains a v2 row.
- **v1 — 2026-07-27:** Initial PRD.

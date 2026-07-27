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
  - **Note:** deliberately split from FR-9b. See §9 Q3 — item identity is unresolved, and the
    repetition failure mode this was designed for does not occur in the v1 beat set.

- **FR-9b — Ledger-based dedup / "what's new" framing** `[Later]`
  - **Requirement:** Before an item is included, check it against the ledger; suppress it or reframe
    it around what changed. The check is a judgment about whether the item adds anything to what the
    reader already knows — not string equality.
  - **Acceptance:** Done when a fixture pair representing the same story on consecutive nights
    produces a suppression or a reframe, with the decision and its reason in the run trace.
  - **Blocked on:** §9 Q3 (item identity). Land alongside FR-17's AI-news beat, where repetition
    actually occurs.

- **FR-10 — Escalation rules engine** `[MVP]`
  - **Requirement:** Deterministic rules over `BeatResult`s promote items to the top of the digest.
    v1 rules: freeze alert within N days; any injury to a configured watched player.
  - **Acceptance:** Done when a run containing one escalation candidate produces a digest whose
    first item is that candidate, asserted on the ordered structure.
  - **Touches:** `forecaster/escalation.py`

- **FR-11 — Synthesizer** `[MVP]`
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
- **Testing:** recorded HTTP fixtures — no live network in the test suite.

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

1. **SMS divergence.** Checkpoints 1.1 and 2.x both state the report arrives as a text message.
   v1 delivers email. A future checkpoint needs one sentence acknowledging the revision — decide
   whether to frame it as a deliberate scope cut or to restore SMS before then.
2. **Rules vs judgment for escalation** — carried forward from the Assignment 2 submission, still
   open, and still the most interesting unresolved design question.
3. **Item identity for the ledger.** What makes two items "the same story"? URL, entity plus date,
   or a model judgment. FR-9 depends on this and it is not yet decided.
4. **Unknown syllabus.** Modules 3+ are unannounced. The architecture is built for additive change
   (FR-2, FR-13) rather than for specific anticipated requirements, because guessing them would be
   fabrication.

## 10. Phasing

- **v1 (MVP):** FR-1 … FR-9, FR-10 … FR-15, FR-18 — two beats, end to end, delivered, traced, and
  honest when a tool fails.
- **Later:** FR-9b (ledger dedup, blocked on §9 Q3), FR-16 (feedback loop), FR-17 (remaining four
  beats) — the natural weekly increments as new checkpoints land.

## 12. Changelog

- **v1 — 2026-07-27:** Initial PRD.

# BUILD PROMPTS — Forecaster

**Source PRD:** [`PRD.md`](PRD.md) (v1, 2026-07-27) · **Feature ID:** `forecaster` ·
**Target path:** `emeritus/forecaster/` (greenfield — nothing exists yet)

> **Driving this across multiple sessions?** Keep a `BUILD-LOG.md` in this folder updated after
> **every** step (step status + its verify result, deviations/decisions, new blockers, run notes),
> and resume per that log — re-verify the last done step against the actual repo before continuing.
> See the `build-build-prompts` skill's `references/driving-and-handoff.md` for the format and the
> resume protocol. Never hand off mid-step.

---

## How to run these

- **19 steps, in order.** Each is self-contained: copy one into a fresh agent session and it has
  everything it needs. Later steps assume earlier ones landed; nothing depends on a step that
  comes after it.
- **Branching.** This playground repo has **no `dev` branch** and no `scripts/new-worktree.mjs`.
  Work on a `feature/forecaster` branch cut from `main`, one commit per completed step, and open a
  PR into `main` for Sarah to merge — do **not** commit to `main` directly. (If a `dev` branch gets
  created first, use the standard model: branch off `dev`, PR into `dev`.)
- **Everything runs on Windows 11 / PowerShell.** Commands below are written for PowerShell.
- **Verify before moving on.** A step is done when its **Verify** block passes — not when the code
  looks right.

## Non-negotiable constraints (every step inherits these)

1. **Auth is subscription OAuth, never the API key.** The agent layer is `claude-agent-sdk`
   (Python) authenticated by `CLAUDE_CODE_OAUTH_TOKEN`. **`ANTHROPIC_API_KEY` must be explicitly
   unset** in any environment that runs the pipeline — if it is set it shadows the OAuth token and
   silently bills per-token. Any step that executes the pipeline (manually or scheduled) has to
   honor this.
2. **No paid signups, ever.** Both external APIs are free and keyless: `statsapi.mlb.com` and
   `api.weather.gov` (the latter **rejects requests without a `User-Agent` header** — a silent 403
   that looks like an outage). Both verified working 2026-07-27. Do not introduce a third-party
   service, an API key, or a paid tier for anything.
3. **No live network in the test suite.** Tests run entirely off recorded HTTP fixtures. Any step
   that adds an adapter must also capture that adapter's fixtures via the capture script and commit
   them. The socket guard from Step 1 stays on.
4. **Never answer a PRD §9 open question.** Q1 (SMS vs email framing), Q2 (rules vs judgment for
   escalation), Q3 (item identity for the ledger), Q4 (unknown syllabus) are unresolved by design.
   If a step would require an answer, **stop and surface it as a blocker** rather than guessing.
   In particular: **FR-9 is write-only in v1** and nothing may read the ledger to make a decision —
   that's FR-9b, blocked on Q3.
5. **No secrets in the diff.** Real values (`CLAUDE_CODE_OAUTH_TOKEN`, SMTP password) live only in
   a gitignored `.env`; `.env.example` carries placeholder keys with empty values. Never print a
   secret into a trace, a log line, a test, or a commit.
6. **In scope only.** The PRD's non-goals are out: no SMS, no web UI or dashboard, no learned or
   embedding-based preference modelling, no multi-user support, no beats beyond Astros + weather.

## Out of scope for this pass

`[Later]` FRs get **no build steps** here — do not implement them, do not stub them speculatively:

- **FR-9b** — ledger-based dedup / "what's new" framing. **Blocked on §9 Q3** (item identity).
  Lands alongside FR-17's AI-news beat, where repetition actually occurs.
- **FR-16** — reply-driven feedback loop.
- **FR-17** — the remaining four beats (AI/Claude news, r/WallStreetBets, need-to-know news, Austin
  live music).

## Known spec ambiguities — read before Step 13/14

These are places where the PRD's prose and its acceptance criteria don't fully line up. The steps
below build to the **acceptance criterion** (the testable half) and flag the rest rather than
inventing. Each needs a one-line decision from Sarah before it can go further:

- **FR-10's injury rule has no data source in v1.** FR-10 lists "any injury to a configured watched
  player" as a v1 rule, but the only v1 MLB adapter (FR-3) returns schedule/state/score/game-ID —
  no injury data. Step 13 builds the rule against a declared `BeatResult` field that **no v1 beat
  populates**, so it is implemented but dormant. Adding an injury feed would be new scope.
- **FR-10's "freeze alert within N days" vs FR-6's next-morning window.** FR-6 (which has the
  testable acceptance criterion) evaluates the freeze threshold over the *next morning's run
  window* only. FR-10's prose implies a multi-day horizon the weather adapter never fetches.
  Step 13 implements the FR-6 horizon and reads `N` from config; extending the forecast horizon is
  a separate decision.
- **FR-11 says the synthesizer "applies the ledger check"** — but the ledger check *is* FR-9b,
  which is `[Later]` and blocked on Q3, and FR-9 states plainly that "nothing reads it to make
  decisions yet." Step 14 therefore applies **escalation ordering and preference suppression only**.
  Do not add a ledger read.

---

# MVP build steps

### Step 1 — Scaffold `emeritus/forecaster/` and the no-network test harness  (infrastructure; enables every FR)

**Context:** Greenfield. Nothing exists under `emeritus/forecaster/` yet. PRD §6 fixes the runtime:
**Python 3.12**, **`uv`** for dependency management, SQLite for the ledger, JSON-lines for run
traces, both local and gitignored, and **recorded HTTP fixtures — no live network in the test
suite**. The repo root is `C:\Users\Sarah\Documents\28_playground`; the project's existing
`.gitignore` is at that root.

**Task:** Create the project skeleton and the test harness the rest of the build stands on.

- `uv init` a Python 3.12 project at `emeritus/forecaster/` with `pyproject.toml`. Runtime deps:
  `httpx`, `claude-agent-sdk`, `python-dotenv`. Dev deps: `pytest`. Add nothing else yet — later
  steps add what they need.
- Package layout (empty modules with docstrings are fine; later steps fill them):
  ```
  emeritus/forecaster/
    forecaster/__init__.py
    forecaster/config.py
    forecaster/planner.py
    forecaster/synthesizer.py
    forecaster/escalation.py
    forecaster/trace.py
    forecaster/agent.py
    forecaster/cli.py
    forecaster/beats/__init__.py      forecaster/beats/base.py
    forecaster/tools/__init__.py
    forecaster/memory/__init__.py
    forecaster/delivery/__init__.py
    config.toml                        preferences.toml
    .env.example
    scripts/capture_fixture.py
    tests/__init__.py  tests/conftest.py  tests/fixtures/
  ```
- **Fixture harness.** Adapters must accept an injectable `httpx.Client` (or transport) so tests can
  serve recorded JSON. Add `tests/conftest.py` helpers: `load_fixture(name) -> dict` reading
  `tests/fixtures/<name>.json`, and a `mock_transport(routes)` helper built on
  `httpx.MockTransport` that maps URL patterns to fixture payloads and status codes.
- **Socket guard.** Add an `autouse=True` fixture in `conftest.py` that blocks real network
  connections for the whole suite (patch `socket.socket.connect` to raise, or use
  `pytest-socket --disable-socket` if you prefer a dep). A test that tries to reach the network must
  fail loudly, not slowly.
- `scripts/capture_fixture.py`: a **manually run** script (the only thing allowed to touch the
  network) that hits a real endpoint and writes a pretty-printed JSON fixture into
  `tests/fixtures/`. Later steps call it to record their fixtures.
- `.env.example` with placeholder keys only, empty values: `CLAUDE_CODE_OAUTH_TOKEN=`,
  `SMTP_HOST=`, `SMTP_PORT=`, `SMTP_USER=`, `SMTP_PASSWORD=`, `SMTP_FROM=`, `SMTP_TO=`.
- Append to the repo-root `.gitignore`: `emeritus/forecaster/.env`, `emeritus/forecaster/data/`,
  `emeritus/forecaster/**/__pycache__/`, `.venv/`, `.pytest_cache/`.
- Add `emeritus/forecaster/README.md`: how to install (`uv sync`), run tests, and run the pipeline
  (fill the run command in as later steps define it).

**Verify:** Done when, from `emeritus/forecaster/`:
```powershell
uv sync
uv run pytest -q
```
passes with at least two tests: one asserting `load_fixture` + `mock_transport` serve a checked-in
sample fixture through an `httpx.Client`, and one asserting that an attempted **real** network call
raises (the socket guard fires). `git status` shows no `.env` and no `data/` staged.

**Guardrails:** Scaffolding only — no beat, adapter, or pipeline logic here. **No secrets in the
diff**: `.env` is gitignored, `.env.example` carries placeholders with empty values. Don't add
dependencies beyond the four named; don't add a linter/formatter/CI config unless a later step
needs it. The PRD's non-goals (no UI, no SMS, no multi-user) are out.

---

### Step 2 — Agent client + hard auth guard  (infrastructure; supports FR-5, FR-11, FR-13, FR-14)

**Context:** PRD §6 *Technical & data notes*. The agent layer is **`claude-agent-sdk` (Python)**,
authenticated via **`CLAUDE_CODE_OAUTH_TOKEN`** against Sarah's Claude subscription. Agent SDK usage
draws from subscription usage limits (the separate Agent-SDK credit is paused as of 2026-06-15).
**`ANTHROPIC_API_KEY` must be unset** in the job environment — if set, it shadows the OAuth token
and silently bills per-token. Default `effort: "low"` for routine beats. Touches
`forecaster/agent.py`. FR-14's acceptance later requires that traces *confirm* subscription auth was
used, so record the auth mode here.

**Task:** Build the one place the rest of the code talks to the model through.

- `forecaster/agent.py` exposing a small client wrapper over `claude-agent-sdk` — a function/class
  that takes a prompt (plus optional tool definitions and an `effort` setting defaulting to
  `"low"`), runs it, and returns the response text along with **token usage** and **timings** so
  Step 6's trace can record them.
- **`assert_subscription_auth()`**, called at client construction and at process start:
  - if `ANTHROPIC_API_KEY` is present in `os.environ`, **raise a loud, explicit error** naming the
    shadowing problem and telling the operator to unset it — never silently continue;
  - if `CLAUDE_CODE_OAUTH_TOKEN` is missing, raise a distinct explicit error;
  - return an `auth_mode` value (e.g. `"subscription_oauth"`) that Step 6 stamps into every trace.
- Load `.env` via `python-dotenv` from `emeritus/forecaster/.env`, but **never** log, print, echo,
  or trace the token value itself — only its presence and the resulting `auth_mode`.
- **`FakeAgentClient` — build it here, every later test depends on it.** A deterministic in-memory
  double implementing the same interface: it returns a canned response derived from the structured
  input it was handed (so a synthesizer test can assert the model *phrased* rather than *originated*
  values), records every call for assertion, and reports zero token usage. **No model call, ever.**
  Which client a run uses is injected — production code never constructs the client inline.
  Steps 8, 14, 15, and 18 all test against this; without it the suite would either hit the network
  or die on Step 1's socket guard.
- Unit tests with the SDK call itself stubbed (no network, no model call): env with
  `ANTHROPIC_API_KEY` set → raises; env with neither var → raises; env with only
  `CLAUDE_CODE_OAUTH_TOKEN` → constructs and reports `auth_mode == "subscription_oauth"`.
- A **secret-leak test**: construct the client with a sentinel token value, exercise it with
  `FakeAgentClient`, capture everything the module writes (stdout, logging, any trace record), and
  assert the sentinel string appears **nowhere** in the captured output.

**Verify:** Done when `uv run pytest tests/test_agent.py -q` passes all three auth cases **plus** the
secret-leak test (sentinel token absent from all captured output), and `FakeAgentClient` satisfies
the same interface as the real client (assert via a shared interface test parametrized over both,
with the real one's SDK call stubbed).

**Guardrails:** **No secrets in the diff or in any log/trace line.** Do not fall back to
`ANTHROPIC_API_KEY` under any condition, do not add a "convenience" flag that allows it, and do not
make a real model call in a test. Keep this module thin — beat logic lives in plain functions the
agent layer calls (PRD §6 framework portability), not in here.

---

### Step 3 — Config loader (`config.toml`)  (implements FR-1, structural half)

**Context:** PRD FR-1. All run parameters — enabled beats, location, delivery target, send time,
escalation rules, watched-player list — live in a single `config.toml`, **not in code**. Touches
`forecaster/config.py`, `config.toml`. Python 3.12 has `tomllib` in the stdlib; no TOML dependency
needed. Location is Austin, TX (NWS grid EWX 156,91 — see FR-4); send time is 7 pm CT.

**Task:** Define and load the config.

- `config.toml` with, at minimum: `[run]` send time + timezone (`America/Chicago`); `[beats]` an
  enable flag per beat name (`astros`, `weather`); `[location]` lat/long, city, timezone;
  `[delivery]` target address + deliverer kind; `[escalation]` freeze threshold temperature,
  freeze horizon `N`, watched-player list, **and an ordered `rules` list naming the enabled rules
  in priority order** (FR-1 explicitly puts "escalation rules" in config; Step 13 uses that order
  to break ties deterministically); `[team]` the MLB team identifier for the Astros beat.
- `forecaster/config.py`: typed dataclasses (`Config`, `RunConfig`, `LocationConfig`,
  `EscalationConfig`, …), `load_config(path) -> Config`, and `enabled_beats(config) -> list[str]`.
  Fail loudly with a clear message on a missing or malformed key — never silently default a value
  that changes behavior.
- **No credentials in `config.toml`** — those live in `.env` (Step 1).
- Tests: load the real `config.toml` and assert the typed fields; load two temp configs with
  different `[beats]` flags and assert `enabled_beats` differs; a malformed config raises.

**Verify:** Done when `uv run pytest tests/test_config.py -q` passes, including the two-config test
showing `enabled_beats` differs by config alone, and this returns nothing (no hardcoded location or
timezone anywhere but `config.py`):
```powershell
Get-ChildItem forecaster -Recurse -Filter *.py |
  Where-Object { $_.Name -ne 'config.py' } |
  Select-String -Pattern 'Austin|America/Chicago|EWX'
```

> **FR-1's full acceptance criterion** — "a test that runs the **pipeline** twice with two configs
> and asserts different beat sets executed" — cannot complete until a pipeline exists. It lands in
> **Step 18**. This step is the structural half; note that in `BUILD-LOG.md`.

**Guardrails:** Config only — no beat, planner, or delivery logic. Don't invent config keys the PRD
doesn't call for (no gold-plating: no retry counts, log levels, or feature flags nobody asked for).
Don't put secrets in `config.toml`.

---

### Step 4 — Preference profile loader (`preferences.toml`)  (implements FR-15, loader half)

**Context:** PRD FR-15. A **human-edited rules file** the planner and synthesizer read: topic
weights, watched players, suppressions. Touches `forecaster/memory/preferences.py`,
`preferences.toml`. PRD §4 non-goal: **no learned or embedding-based preference modelling** — this
is a rules file a human edits, full stop. Read-only in v1 (writing rules from replies is FR-16,
`[Later]`).

**Task:** Define and load the profile.

- `preferences.toml`: `[topics]` weights per beat/topic, `[watched_players]` a list,
  `[[suppressions]]` a list of rules, each with enough structure to match an item (e.g. `beat` plus
  a `contains` string or a simple field/value match). Keep matching **deterministic and
  explainable** — a suppression that fires must be able to say which rule fired and why (Step 6's
  trace records the reason).
- `forecaster/memory/preferences.py`: typed `Preferences` dataclass, `load_preferences(path)`, and
  `suppression_match(item, preferences) -> SuppressionDecision | None` returning the matching rule
  so the caller can record it.
- Tests: load the real file; a synthetic item matching a suppression rule returns a decision naming
  the rule; a non-matching item returns `None`; a missing `preferences.toml` fails with a clear
  error rather than silently proceeding with no preferences.

**Verify:** Done when `uv run pytest tests/test_preferences.py -q` passes all four cases, and the
returned `SuppressionDecision` carries a human-readable reason string.

> **FR-15's acceptance criterion** — "adding a suppression rule removes a matching item from the
> next digest" — requires the synthesizer. It lands in **Step 14**.

**Guardrails:** Read-only. No writing, learning, weighting-by-history, or embedding anything. Don't
wire this into the planner or synthesizer yet — those steps consume it.

---

### Step 5 — `Beat` protocol, `BeatResult`, and the beat registry  (implements FR-2; defines the shape FR-18 needs)

**Context:** PRD FR-2 — every beat implements one `Beat` protocol (`name`, `should_run(context)`,
`run(context) -> BeatResult`), and the planner and synthesizer know **only the protocol**. Touches
`forecaster/beats/base.py`. This is the load-bearing extensibility seam: FR-17's four future beats
must land without touching planner, synthesizer, or delivery. Two other FRs depend on the shape you
define here — **FR-11** needs a declared `checkable_fields` set for the provenance test, and
**FR-18** needs an "unavailable, here's the error" result that never silently drops out.

**Task:** Define the contract everything else is written against.

- `Beat` protocol: `name: str`, `should_run(context) -> bool`, `run(context) -> BeatResult`.
- `BeatResult` dataclass carrying at least:
  - `beat: str`, `items: list[BeatItem]` (each with rendered text plus its structured fields),
  - **`checkable_fields: dict[str, Any]`** — the values the synthesizer is allowed to state as fact
    (scores, game state, temperature, wind, precipitation probability), each traceable to the
    observation it came from. Inning counts, dates, and "6 am" are prose, not claims — keep them out.
  - **`available: bool`** and **`error: str | None`** — the FR-18 unavailability shape,
  - `escalation_candidate: bool` plus an `escalation_reason: str | None` (FR-10 consumes these),
  - **`escalation_signals: dict[str, Any]`** — a beat-agnostic bag of structured signals the rules
    engine may read (Step 13's dormant watched-player rule looks for an `"injuries"` key here). This
    keeps `BeatResult` free of sport-specific fields while still giving FR-10 something to match on.
  - `observations: list[ObservationRef]` — pointers to the trace records the values came from.
- **Define the two collaborator interfaces here as `typing.Protocol`s**, so nothing forward-references
  a module that doesn't exist yet: `TraceWriter` (the methods a beat calls to record a tool call, an
  observation, a decision) and `ScratchpadLike` (`get_or_call` plus the note-taking methods). Step 6
  and Step 7 implement these protocols; `base.py` never imports those modules.
- A `context` dataclass the pipeline passes in: config, preferences, run date/time, plus
  `scratchpad: ScratchpadLike` and `trace: TraceWriter` typed against the protocols above.
- A **registry**: `register_beat(cls)` / `get_beats(config)` returning the beat instances the config
  enables, so adding a beat = one class + one config entry.
- Tests: a dummy beat registered via the registry and enabled by config appears in `get_beats`;
  a `BeatResult` with `available=False` requires a non-empty `error`; `checkable_fields` defaults to
  empty rather than to `None`.

**Verify:** Done when `uv run pytest tests/test_beats_base.py -q` passes, and a dummy beat class plus
one `config.toml` entry is genuinely all it takes to get that beat into `get_beats()` — with zero
edits to any other module (there are no other modules yet; the point is the protocol allows it).

> **FR-2's full acceptance criterion** — "registers a dummy beat and **sees it in the output**" —
> needs the pipeline's output. It lands in **Step 18**.

**Guardrails:** Contract only — no beat implementations here (Astros is Step 11, weather is Step 12).
Don't add beat-specific fields to `BeatResult` — anything sport- or domain-specific goes in the
item's structured payload or in `escalation_signals`, never as a named column on the universal
contract. Beat logic must stay plain functions/classes the agent layer calls (PRD §6 portability) —
don't couple `base.py` to `claude-agent-sdk`.

---

### Step 6 — Run trace + the provenance checker  (implements FR-13)

**Context:** PRD FR-13 — every run writes a structured trace: **per beat**, the plan, **each tool
call and its observation**, each decision with its reason, timings, and token usage. It deliberately
records more than v1 consumes, so a later evaluation module has data. Touches `forecaster/trace.py`,
`forecaster/data/runs/` (JSON-lines, gitignored). This is what makes PRD §2's success metric (a) —
zero checkable claims without a matching tool observation — **machine-checkable**, so build the
checker here too; Steps 14, 15, and 18 all reuse it.

**Task:** Build the trace writer and the checker that reads it.

- `forecaster/trace.py`: a `Trace` object opened per run, writing JSON-lines to
  `forecaster/data/runs/<run_id>.jsonl`. Record types, at minimum: `run_start` (run id, timestamp,
  config digest, **`auth_mode` from Step 2**), `plan` (per beat: name + completion criterion),
  `tool_call` (beat, adapter, arguments, an observation id), `observation` (the returned payload or
  the error), `decision` (what was decided, the reason, which beat), `beat_result`, `escalation`,
  `delivery`, `run_end` (timings, aggregate token usage).
- Every `tool_call` gets a stable `observation_id` that a `BeatResult.observations` entry can point
  at — that link is what makes the provenance check computable.
- **`check_provenance(trace_path, digest_text) -> ProvenanceReport`**: for each beat's declared
  `checkable_fields`, assert the value appears in the rendered digest **only if** it matches the
  observation it came from; report any claim with no matching observation as a violation. Must be
  computable from the trace file **with no other input** beyond the digest the trace itself records.
- Never write a secret into a trace record (the token, SMTP password, or any `.env` value).
- Tests: a synthetic run writes each record type and round-trips; `check_provenance` passes on a
  clean synthetic run and **fails** on a hand-built run where a digest states a score with no
  matching observation.

**Verify:** Done when `uv run pytest tests/test_trace.py -q` passes, including the negative case
(fabricated claim → violation reported), and a synthetic run's trace file is valid JSON-lines
(`Get-Content data\runs\<id>.jsonl | ForEach-Object { $_ | ConvertFrom-Json }` succeeds on every
line).

> **FR-13's full acceptance criterion** — "a **completed run** produces a trace from which the §2
> provenance check can be computed with no other input" — lands in **Step 18** on a real run.

**Guardrails:** Recording only — the trace makes no decisions and changes no behavior. Don't build
an evaluation/analysis module on top of it (that's a future module, explicitly not v1). Don't prune
fields to "keep it small"; over-recording is the point. `data/` stays gitignored.

---

### Step 7 — Per-run scratchpad (short-term memory)  (implements FR-8)

**Context:** PRD FR-8 — each worker gets a scratchpad recording what it searched, what it found, and
what is still missing; **discarded once the digest sends**. Touches
`forecaster/memory/scratchpad.py`. PRD §4 puts short-term scratchpad and long-term ledger on
opposite sides of the run boundary: this one is in-memory and dies with the process.

**Task:** Build the scratchpad and route tool calls through it.

- `Scratchpad`: in-memory per run. Records, per beat, each search performed (adapter + normalized
  arguments), each observation returned, and open questions ("still missing").
- **Call memoization**: a `get_or_call(key, fn)` (or equivalent wrapper) such that an identical tool
  call within one run is **served from the scratchpad instead of re-invoking the adapter**. The
  cache key must be the normalized call signature, not object identity.
- Every scratchpad hit and miss is written to the trace (Step 6) as a `decision` record with its
  reason — a served-from-cache call must be visible.
- **Not persisted.** No file, no SQLite, no cross-run reuse; it goes out of scope when the run ends.
- Tests: a stub worker that issues the same adapter call twice, with a counting fake adapter,
  invokes the adapter **once**; two different calls invoke it twice; the scratchpad reports its
  "still missing" entries; nothing is written to disk.

**Verify:** Done when `uv run pytest tests/test_scratchpad.py -q` passes and the repeat-call test
asserts `fake_adapter.call_count == 1` after two identical requests. Confirm no file appears under
`data/` after the test run.

**Guardrails:** Short-term only — do **not** touch the sent-item ledger (FR-9, Step 16) or read
anything from a previous run. Don't add a TTL, a size limit, or disk spillover; one run is the
lifetime.

---

### Step 8 — Planner  (implements FR-7)

**Context:** PRD FR-7 — the planner reads date, day of week, and the preference profile, and decides
which beats run tonight and what "done" means for each. It **performs no research itself**. Touches
`forecaster/planner.py`. It consumes Step 3's config, Step 4's preferences, and Step 5's beat
registry — and only the `Beat` protocol, never a concrete beat.

**Task:** Build the plan-emitting layer.

- `plan_run(config, preferences, now) -> RunPlan`. `RunPlan` names each beat that will run and its
  **completion criterion** ("done when" for that beat), derived from config enablement +
  `should_run(context)` + preference weights.
- Write the plan into the trace as a `plan` record (Step 6), one entry per beat with its criterion.
- **Zero tool calls.** The planner must not touch an adapter, the network, or the agent client.
- Tests: with two beats enabled the plan names both with a criterion each; disabling a beat in
  config removes it from the plan; a test asserts the planner makes **zero** tool calls — inject
  counting fake adapters plus Step 2's `FakeAgentClient` and assert every call count is 0.

**Verify:** Done when `uv run pytest tests/test_planner.py -q` passes, including the zero-tool-call
assertion, and the emitted `RunPlan` contains a non-empty completion criterion for every named beat.

**Guardrails:** Planning only — no fetching, no summarizing, no model call to "enrich" the plan. The
planner imports the `Beat` protocol and registry, never `beats/astros.py` or `beats/weather.py`
directly (FR-2's seam). Don't encode the Astros/weather specifics here.

---

### Step 9 — MLB Stats API adapter + fixtures  (implements FR-3)

**Context:** PRD FR-3 — a client for `statsapi.mlb.com` returning, for a given date and team, each
game's `abstractGameState`, UTC start time, score, and per-game ID, **normalized into a typed
object, with UTC converted to the configured local timezone**. Touches `forecaster/tools/mlb.py`.
Free, no key — verified live 2026-07-26/27. PRD §8: this is an **undocumented public endpoint** under
MLB's copyright terms; it can change shape or rate-limit without notice, so the adapter must **fail
loudly into the trace rather than emit a plausible score**. FR-5's "preview next game" branch means
the adapter should accept a date **range**, not only a single date.

**Task:** Build the adapter and record its fixtures.

- `forecaster/tools/mlb.py`: `fetch_schedule(team_id, start_date, end_date=None, *, client)` hitting
  the schedule endpoint and returning a typed `Game` list — `game_pk`, `abstract_game_state`
  (`Final` / `In Progress` / `Preview`), `detailed_state`, `start_time_utc`, `start_time_local`
  (converted via `zoneinfo` to the configured timezone), `home`/`away` team + score, `is_doubleheader`.
- Accepts an injectable `httpx.Client` (Step 1) so tests serve fixtures.
- **Failure behavior:** an HTTP error, timeout, or unparseable payload raises a typed
  `AdapterError` carrying the status/reason — it never returns a partial or guessed `Game`. (Step 15
  turns that into an unavailable `BeatResult`.)
- **Capture fixtures** with `scripts/capture_fixture.py` (the only network-touching code) and commit
  them under `tests/fixtures/`: `mlb_doubleheader.json`, `mlb_in_progress.json`, `mlb_final.json`,
  `mlb_no_game.json`. If a live payload for a state isn't available on the day you build (e.g. no
  in-progress game right now), copy a **real** captured payload and hand-edit the state fields —
  and label the file's provenance in a `tests/fixtures/README.md` so nobody mistakes a synthetic
  fixture for a recorded one.
- Tests, all off fixtures: the doubleheader fixture returns the correct **game count**, the correct
  **states**, and correctly **localized start times**; an in-progress fixture exposes the live score;
  the no-game fixture returns an empty list (not an error); a 500 response raises `AdapterError`.

**Verify:** Done when `uv run pytest tests/test_mlb.py -q` passes — specifically the FR-3 criterion:
given the recorded doubleheader + in-progress fixtures, the adapter returns the correct game count,
states, and localized start times. The socket guard confirms zero live calls during the suite.

**Guardrails:** Adapter only — no beat logic, no branching on what the score *means* (that's FR-5).
Don't add caching (Step 7's scratchpad owns that), don't add retries with silent fallback, and never
substitute a value when the call fails. No API key, no paid tier, no alternative provider.

---

### Step 10 — NWS weather adapter + fixtures  (implements FR-4)

**Context:** PRD FR-4 — a client for `api.weather.gov` returning the hourly forecast covering the
next morning's run window for the configured grid point, including temperature and precipitation.
Touches `forecaster/tools/weather.py`. Free, no key. **NWS rejects requests without a `User-Agent`
header** — PRD §8 calls this out as "a silent 403 that looks like an outage," and FR-4's acceptance
requires a test asserting the header is sent. Austin resolves to grid **EWX 156,91** (verified live
2026-07-27), but the adapter must resolve it from lat/long rather than hardcoding it.

**Task:** Build the adapter and record its fixtures.

- `forecaster/tools/weather.py`: `fetch_hourly_forecast(lat, lon, *, client)` — two hops: `GET
  /points/{lat},{lon}` to resolve the grid office + x/y, then the returned
  `properties.forecastHourly` URL. Returns a typed list of hourly periods with local start time,
  temperature (+ unit), wind speed/direction, and probability of precipitation.
- A helper that slices the periods covering **5–8 am local** on the next morning, per the run window.
- Every request sends a descriptive **`User-Agent`** header (contact string, from config or a module
  constant — no secrets in it).
- Same failure contract as Step 9: HTTP error / timeout / unparseable payload → typed
  `AdapterError`, never a substituted value.
- **Capture fixtures** via `scripts/capture_fixture.py`: `nws_points_austin.json`,
  `nws_hourly_austin.json`. You will also need a **below-freezing** hourly fixture for FR-6 — Austin
  in July won't produce one live, so hand-edit a copy of the real payload's temperatures and record
  its synthetic provenance in `tests/fixtures/README.md`.
- Tests, all off fixtures: given a lat/long the adapter resolves the grid point (EWX 156,91) and
  returns periods covering 5–8 am local; **a test asserts the `User-Agent` header is present on
  every outgoing request** (inspect the request in `MockTransport`); a 403 with no `User-Agent`
  surfaces as an `AdapterError` naming the header, not as an empty forecast.

**Verify:** Done when `uv run pytest tests/test_weather.py -q` passes, including the `User-Agent`
assertion and the 5–8 am window slice.

**Guardrails:** Adapter only — the freeze-threshold judgment belongs to FR-6 (Step 12). Don't
hardcode the Austin grid, don't extend to multi-day forecasts (see the ambiguity note above — that's
an open decision, not this step's call), don't add a second weather provider or any keyed service.

---

### Step 11 — Astros beat worker (ReAct loop)  (implements FR-5)

**Context:** PRD FR-5 — a worker that calls the schedule first and **branches on the returned game
state**: *final and none tonight* → report the final, preview next; *tonight in progress* → report
the last completed game and flag tonight live with its current score; *no game* → say so briefly.
It decides whether it has enough or needs another call. Touches `forecaster/beats/astros.py`.
Consumes Step 9's adapter through Step 7's scratchpad, implements Step 5's `Beat` protocol, and
writes each call/observation/decision into Step 6's trace. PRD §8: **offseason** (November–March)
must degrade to "no games", not error.

**Task:** Build the beat.

- `AstrosBeat` implementing `Beat`: `name = "astros"`, `should_run(context)` from config
  enablement, `run(context) -> BeatResult`.
- **ReAct loop**: fetch today's schedule → inspect the state → decide whether the result is
  sufficient or a second call is needed (e.g. the next game's date for the preview, or the last
  completed game when tonight is in progress) → call again through the scratchpad → stop. Every
  decision, with its reason, goes into the trace.
- Populate `BeatResult.checkable_fields` with exactly the values the synthesizer may state as fact:
  score, game state, opponent, localized start time. Point `observations` at the trace observation
  ids they came from.
- The offseason / no-game path returns a normal `available=True` result whose item says there's no
  game — **not** an error and not an empty result.
- Tests off the Step 9 fixtures, asserting on the **structured `BeatResult`, not on prose**:
  `mlb_final.json` → the final-reported + next-previewed branch; `mlb_in_progress.json` → last
  completed game reported *and* tonight flagged live with its current score; `mlb_no_game.json` →
  the brief no-game branch. Plus: a repeated identical schedule call inside one run hits the
  scratchpad (adapter invoked once).

**Verify:** Done when `uv run pytest tests/test_beat_astros.py -q` passes and the three fixtures each
produce the correct branch **asserted on `BeatResult` fields**, not on rendered text.

**Guardrails:** This beat may not import the planner, synthesizer, or delivery — only the protocol,
the adapter, the scratchpad, and the trace (FR-2's seam). Keep the logic as plain functions the
agent layer calls (PRD §6 portability). **Never** synthesize a score, an opponent, or a start time
that didn't come from an observation — a missing value is a missing value. **No injury data**: the
MLB adapter returns schedule/state/score/game-ID only, and adding an injury feed or scraping a
roster page is new scope requiring Sarah's decision — leave `escalation_signals["injuries"]`
unpopulated.

---

### Step 12 — Weather beat worker  (implements FR-6)

**Context:** PRD FR-6 — a worker that produces the run-window forecast and **evaluates the freeze
threshold from config**. Touches `forecaster/beats/weather.py`. Consumes Step 10's adapter through
Step 7's scratchpad, implements Step 5's `Beat` protocol, and writes to Step 6's trace. The
motivating job (PRD §1) is "weather that changes what she wears on a 6 am run," so the run window is
the 5–8 am slice.

**Task:** Build the beat.

- `WeatherBeat` implementing `Beat`: `name = "weather"`, `should_run(context)` from config
  enablement, `run(context) -> BeatResult`.
- Produce the next-morning run-window forecast: temperature range across 5–8 am, precipitation
  probability, wind. Populate `checkable_fields` with **temperature, wind, precipitation
  probability** — the values FR-11's provenance test polices — each pointing at its observation.
- Read the **freeze threshold from config** (Step 3's `[escalation]`) and set
  `escalation_candidate=True` with an `escalation_reason` when the run-window low is at or below it;
  `False` otherwise. Record the comparison as a `decision` in the trace.
- Tests off the Step 10 fixtures: the below-freezing (synthetic) fixture yields
  `escalation_candidate=True`; the real above-threshold fixture yields `False`; the threshold comes
  from config (changing the config value flips the outcome on the same fixture).

**Verify:** Done when `uv run pytest tests/test_beat_weather.py -q` passes the FR-6 criterion
exactly: a fixture below the threshold → `escalation_candidate=True`, one above → `False`.

**Guardrails:** Same seam as Step 11 — protocol, adapter, scratchpad, trace only. The threshold value
lives in config, never in code. **Don't implement the multi-day "freeze within N days" horizon**
that FR-10's prose implies: the NWS adapter fetches the next morning's window only, FR-6's
acceptance criterion is scoped to that window, and extending the forecast range is an open decision
for Sarah — not this step's call. Don't add "what to wear" advice beyond what the numbers support.

---

### Step 13 — Escalation rules engine  (implements FR-10)

**Context:** PRD FR-10 — **deterministic** rules over `BeatResult`s promote items to the top of the
digest. v1 rules: freeze alert within N days; any injury to a configured watched player. Touches
`forecaster/escalation.py`. Rules read config (Step 3's `[escalation]`) and the `escalation_candidate`
/ `escalation_reason` fields Step 5 defined. PRD §8 warns: **escalating everything is the same as
escalating nothing** — if rules fire most nights the ordering carries no signal, so record every
firing in the trace so that's observable in the first two weeks.

**Read this before you build — two spec gaps, do not paper over them:**

- **The injury rule has no v1 data source.** The MLB adapter (FR-3) returns schedule, state, score,
  and game ID — no injury information, and no v1 beat populates one. Implement the rule against the
  `escalation_signals["injuries"]` key defined in Step 5 and test it with a **synthetic**
  `BeatResult`, so the rule exists and is correct but is **dormant in v1**. Do **not** add an injury
  feed, scrape a roster page, or introduce a new endpoint — that is new scope requiring Sarah's
  decision.
- **"Within N days" exceeds the fetched horizon.** FR-6 (the criterion with a test) evaluates the
  freeze threshold over the next morning's run window only. Read `N` from config and apply the rule
  to the horizon the data actually covers; note in `BUILD-LOG.md` that a multi-day horizon needs a
  forecast-range decision first.

**Task:** Build the rules engine.

- `apply_escalation(results, config) -> OrderedItems`: pure, deterministic, no model call. Evaluate
  each rule against the `BeatResult`s, promote matching items to the top, and return an **ordered**
  structure with each promotion's rule name and reason attached.
- Write each rule evaluation (fired / didn't fire, and why) to the trace as a `decision` /
  `escalation` record.
- Ties and multiple escalations: order deterministically using the **`[escalation] rules` list from
  config** (Step 3) as rule priority, then beat order, so the same inputs always produce the same
  output. Read the priority from config — don't hardcode it.
- Tests: a run with one escalation candidate produces an ordered result whose **first item is that
  candidate** (FR-10's criterion, asserted on the ordered structure); a run with none preserves the
  base order; a synthetic `BeatResult` whose `escalation_signals["injuries"]` names a watched player
  promotes it; a run with two candidates orders them deterministically per the config rule order.

**Verify:** Done when `uv run pytest tests/test_escalation.py -q` passes, with the FR-10 criterion
asserted on the ordered structure (not on rendered prose), and every fired rule appears in the trace
with its reason.

**Guardrails:** **Deterministic rules only** — no model judgment. PRD §9 **Q2 (rules vs judgment for
escalation) is explicitly open**; if the implementation starts to want a judgment call, stop and
surface it rather than deciding it here. Watched players and thresholds come from config/preferences,
never from code. Don't invent new rules beyond the two named.

---

### Step 14 — Synthesizer + the provenance guarantee  (implements FR-11; completes FR-15; re-checks FR-10 at digest level)

**Context:** PRD FR-11 — the synthesizer collects all `BeatResult`s, applies escalation ordering, and
composes the final message. **Every checkable value it emits is copied from a `BeatResult` field —
the model phrases, it does not originate.** Touches `forecaster/synthesizer.py`. This is where PRD
§2's load-bearing metric (a) is enforced, using Step 6's `check_provenance`. It also completes
**FR-15**: adding a suppression rule to `preferences.toml` removes a matching item from the digest.

**Scope correction — read it:** FR-11's prose says the synthesizer "applies the ledger check." The
ledger check **is FR-9b**, which is `[Later]` and **blocked on §9 Q3 (item identity)**, and FR-9
states plainly that nothing reads the ledger to make decisions in v1. So this step applies
**escalation ordering + preference suppression only**. Do not read the ledger. Do not invent an
identity/dedup key.

**Task:** Build the composer.

- `synthesize(results, config, preferences, trace) -> Digest`:
  1. apply Step 4's suppression rules, recording each suppression and its reason in the trace;
  2. apply Step 13's escalation ordering;
  3. compose the message via Step 2's agent client, **injected, not constructed inline** — the model
     receives the structured values and **phrases** them; it is never asked to supply a number, a
     score, or a state.
- **Every test in this step injects Step 2's `FakeAgentClient`.** No test makes a real model call —
  Step 1's socket guard is on and a real call would both fail the suite and draw down subscription
  usage.
- Enforce provenance **structurally, not by prompt alone**: after composition, run
  `check_provenance` (Step 6) over the trace + rendered digest and **fail the run** (loudly, into
  the trace) if any declared `checkable_field` value appears without a matching observation, or
  appears altered. A prompt instruction is not a guarantee; the check is.
- Scope the check to **declared `checkable_fields`** (scores, game state, temperature, wind,
  precipitation probability), per FR-11 — inning counts, dates, and "6 am" are prose, not claims.
- Tests: **the FR-11 provenance test** — a full synthetic run's digest passes `check_provenance`,
  and a deliberately tampered digest (a score changed by one) **fails** it; the **FR-15 test** —
  adding a suppression rule to a temp `preferences.toml` removes the matching item from the digest
  and the trace names the rule; escalated items appear first in the rendered output.

**Verify:** Done when `uv run pytest tests/test_synthesizer.py -q` passes, with (a) the provenance
test green on a clean run **and** red on the tampered digest, and (b) the FR-15 suppression test
showing the item present without the rule and absent with it.

**Guardrails:** The model phrases; it never originates a checkable value — no "reasonable estimate,"
no rounding, no filling a gap. **No ledger read** (FR-9b is blocked on Q3). Don't widen
`checkable_fields` to "every number" — FR-11 deliberately scopes it. Don't let a failed provenance
check degrade to a warning; it fails the run.

---

### Step 15 — Tool-failure handling (the no-fabrication guarantee)  (implements FR-18)

**Context:** PRD FR-18 — when an adapter errors, times out, or returns an unparseable payload, the
beat yields a `BeatResult` marked **unavailable** carrying the error; the synthesizer renders an
explicit "couldn't reach X tonight" line; **the model is never asked to fill the gap**, and a failed
beat **never silently drops out** of the digest. Touches `forecaster/beats/base.py`,
`forecaster/synthesizer.py`. This is PRD §2's success metric (c) — honest degradation — and PRD §8's
"fail loudly into the trace rather than emit a plausible score."

**Task:** Wire the failure path end to end.

- In `beats/base.py`: a shared helper that wraps a beat's `run` so any `AdapterError`, timeout, or
  parse failure becomes a `BeatResult` with `available=False`, a populated `error`, empty
  `checkable_fields`, and the error recorded as an `observation` in the trace. Unexpected exceptions
  get the same treatment — no beat may crash the run.
- In `synthesizer.py`: an unavailable `BeatResult` renders an explicit unavailability line naming the
  beat and that the source couldn't be reached. It is **never** dropped, never merged into silence,
  and the model is never prompted to substitute a value.
- Apply the wrapper to both beats (Steps 11 and 12).
- Tests (all injecting Step 2's `FakeAgentClient` — no real model call): a fixture where the MLB call
  **500s** produces a digest containing an explicit unavailability line and **no score**, with the
  **FR-11 provenance test passing on that run**; a weather timeout does the same; a run where one
  beat fails and the other succeeds still delivers the successful beat's content; the failed beat
  appears in the trace with its error.

**Verify:** Done when `uv run pytest tests/test_tool_failure.py -q` passes the FR-18 criterion
exactly: the 500-on-MLB fixture → digest contains an explicit unavailability line, contains **no**
score, and `check_provenance` passes on that run.

**Guardrails:** No retries-with-fallback that mask a failure, no cached-from-yesterday substitute
(the ledger is write-only in v1 anyway), no "based on typical July weather" hedge. Explicit
unavailability is the correct output. Don't swallow the error — it belongs in the trace.

---

### Step 16 — Sent-item ledger, write path  (implements FR-9)

**Context:** PRD FR-9 — every item included in a delivered digest is durably recorded with its
**beat, timestamp, rendered text, and source observation**. **Write-only in v1 — nothing reads it to
make decisions yet.** Touches `forecaster/memory/ledger.py`, SQLite at `forecaster/data/ledger.db`
(gitignored). PRD FR-9's own note and §9 **Q3** are the reason this is split from FR-9b: **item
identity is unresolved** — what makes two items "the same story" (URL, entity+date, or a model
judgment) is not decided.

**Task:** Build the write path only.

- `forecaster/memory/ledger.py`: create/migrate a SQLite schema — one row per delivered item with
  `run_id`, `beat`, `sent_at`, `rendered_text`, `source_observation_id`, plus an autoincrement row
  id. Idempotent schema creation; the DB file lives under the gitignored `data/`.
- `record_delivered_items(digest, run_id)` called **after a successful delivery** (wired in Step 18).
- Tests: a completed synthetic run appends one row per delivered item; a **second** run appends its
  own rows without collision (distinct `run_id`s, no unique-constraint failure, no overwrite);
  re-running the schema creation on an existing DB is a no-op.

**Verify:** Done when `uv run pytest tests/test_ledger.py -q` passes, showing one row per delivered
item after run 1 and additional non-colliding rows after run 2, and this shows the ledger is
imported **only** by the runner's post-delivery write — no read path feeding any decision:
```powershell
Get-ChildItem forecaster -Recurse -Filter *.py |
  Select-String -Pattern 'ledger' |
  Select-Object Filename, LineNumber, Line
```

**Guardrails:** **Write-only.** Do not add a dedup/"same story" key, a content hash, a similarity
check, a `SELECT` used to filter items, or any identity column that implies an answer to §9 Q3 —
that question is open and FR-9b is `[Later]` and blocked on it. A surrogate autoincrement id plus
`run_id` is fine; a semantic item identity is not. If the schema seems to *want* an identity column,
that's the blocker — surface it, don't decide it.

---

### Step 17 — Delivery interface + email implementation  (implements FR-12)

**Context:** PRD FR-12 — a `Deliverer` interface with one `send(digest)` method and an **SMTP**
implementation; credentials come from a **gitignored `.env`**. Touches
`forecaster/delivery/base.py`, `forecaster/delivery/email.py`. PRD §7 dependency: an SMTP account
with an **app password** (Gmail requires an app password, not the login password) — that's on
Sarah's HUMAN-TODO, not on the build. PRD §4 non-goal: **v1 ships email, not SMS** (the divergence
from the submitted checkpoints is §9 Q1 and is Sarah's framing call, not a build decision).

**Task:** Build delivery plus a test double.

- `delivery/base.py`: a `Deliverer` protocol with a single `send(digest) -> DeliveryResult`.
- `delivery/email.py`: `EmailDeliverer` using `smtplib` over TLS, reading `SMTP_HOST`, `SMTP_PORT`,
  `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_TO` from the gitignored `.env`. Fail with a clear
  error naming the missing variable if any is absent — never send to a default address.
- `FakeDeliverer` capturing the digest in memory so the **full pipeline is testable without sending
  anything**. Config (Step 3, `[delivery]`) selects which deliverer the run uses.
- Record a `delivery` record in the trace: target (address is fine; **the password never is**),
  timestamp, success/failure.
- Tests: `FakeDeliverer` captures a **synthesized digest** (call Step 14's synthesizer directly with
  `FakeAgentClient` — the CLI doesn't exist until Step 18, so don't reach for it here) with no SMTP
  involved; `EmailDeliverer` composes the correct message with a **mocked `smtplib.SMTP`** (no real
  send in the suite); a missing env var raises a clear error; the trace's `delivery` record contains
  the target address and **no** credential.

**Verify:** Done when `uv run pytest tests/test_delivery.py -q` passes all four cases with zero SMTP
socket activity (Step 1's guard confirms it).

**⚠️ Human-gated half of FR-12 — lands in Step 18.** The rest of FR-12's acceptance ("the digest
arrives in Sarah's inbox from a real run") needs real credentials, a real send, and the CLI entry
point that Step 18 builds. **The implementing agent must never send it.** Note the gate in
`BUILD-LOG.md` here; Step 18 hands Sarah the exact command and adds the HUMAN-TODO entries.

**Guardrails:** **No secrets in the diff** — credentials only in gitignored `.env`, placeholders in
`.env.example`, never in `config.toml`, a test, a trace, or a log line. **Do not send a real email
autonomously.** No SMS, no push, no webhook — email is the only v1 channel (PRD §4).

---

### Step 18 — Runner CLI + end-to-end wiring  (completes FR-1, FR-2, FR-13; integrates everything)

**Context:** The pieces exist; nothing has run them together. This step builds the entry point and
lands the three acceptance criteria that are end-to-end by nature: **FR-1** ("a test that runs the
pipeline twice with two configs and asserts different beat sets executed"), **FR-2** ("registers a
dummy beat and **sees it in the output**"), and **FR-13** ("a completed run produces a trace file
from which the §2 provenance check can be computed with no other input"). Touches
`forecaster/cli.py`. Pipeline order per PRD §4: planner → per-beat ReAct workers → synthesizer →
delivery → ledger write.

**Task:** Wire the pipeline and prove it end to end.

- `forecaster/cli.py` / `python -m forecaster.cli` with flags: `--config`, `--preferences`,
  `--dry-run` (use `FakeDeliverer`, still write the trace), `--send-test` (Step 17's human-run
  check). On start, call Step 2's `assert_subscription_auth()` — the run **refuses to start** if
  `ANTHROPIC_API_KEY` is set.
- Run sequence: open trace → `assert_subscription_auth` → load config + preferences → plan → run
  each enabled beat (each wrapped by Step 15's failure handler, each with a fresh scratchpad) →
  escalation → synthesize (provenance check enforced) → deliver → **on delivery success**, write the
  ledger rows (Step 16) → close trace with timings and token usage.
- Update `emeritus/forecaster/README.md` with the real run/test commands, and update
  `emeritus/STATUS.md`'s capstone section to reflect that the build has landed.
- Integration tests, all off recorded HTTP fixtures, with `FakeDeliverer` (Step 17) **and** Step 2's
  `FakeAgentClient` — the suite makes no network call and no model call:
  - **FR-1:** run the pipeline twice with two configs enabling different beat sets; assert the
    executed beats differ, driven by config alone.
  - **FR-2:** register a dummy beat via one class + one config entry, run the pipeline, and see it
    in the delivered digest — with **zero edits** to `planner.py`, `synthesizer.py`, or
    `delivery/*` (assert this by the test needing no such change; note it in `BUILD-LOG.md`).
  - **FR-13:** a completed run produces a trace file, and `check_provenance` computes the §2 metric
    from **that file plus the digest it records, and nothing else**.
  - A full run with one beat failing still delivers, still traces, still writes ledger rows for the
    delivered items.

**Verify:** Done when `uv run pytest -q` passes the **whole** suite, and:
```powershell
cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
uv run python -m forecaster.cli --dry-run
```
completes, prints the digest, writes a trace under `data/runs/`, and a follow-up
`check_provenance` over that trace reports zero violations.

> Note: `--dry-run` uses `FakeDeliverer` but a **real** agent client, so it draws down subscription
> usage and hits the two live APIs. That's intentional here — it's the first true end-to-end run.

**⚠️ Human-gated: FR-12's real send.** Now that the CLI exists, hand Sarah this and stop:
```powershell
cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
uv run python -m forecaster.cli --send-test
```
and add to `emeritus/HUMAN-TODO.md`: create the SMTP app password, put it in the gitignored `.env`,
run the command above, confirm the digest arrived in the inbox. **The agent does not run it.**

**Guardrails:** Wiring only — no new behavior, no new FRs. Keep the planner/synthesizer/delivery free
of beat-specific imports (FR-2's seam is the thing this step proves). **Do not send a real email
here** — `--dry-run` uses the fake deliverer, and `--send-test` is Sarah's to run. `data/` stays
gitignored; no trace or DB in the commit.

---

### Step 19 — Nightly scheduler (Windows Task Scheduler)  (implements FR-14)

**Context:** PRD FR-14 — the pipeline runs unattended at **7 pm CT** via **Windows Task Scheduler**,
with `CLAUDE_CODE_OAUTH_TOKEN` set and **`ANTHROPIC_API_KEY` explicitly unset** in the job
environment. Touches `scripts/run_nightly.ps1`. Acceptance: three consecutive scheduled runs complete
without manual intervention and **the traces confirm subscription auth was used** (Step 2's
`auth_mode`, stamped into `run_start` by Step 6). PRD §8: a laptop asleep at 7 pm means no digest and
no error — "the trace should record intended-but-missed runs so the §2 delivery metric is honest."

**Task:** Author the job script and hand Sarah the registration.

- `emeritus/forecaster/scripts/run_nightly.ps1`:
  - `Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue` **before** anything else;
  - load `.env` (gitignored) for `CLAUDE_CODE_OAUTH_TOKEN` and SMTP settings;
  - accept a **`-DryRun` switch** that passes `--dry-run` through to the CLI (fake deliverer, still
    writes the trace) — this is how the step gets verified without sending mail;
  - `Set-Location` to the project directory and invoke `uv run python -m forecaster.cli`;
  - capture stdout/stderr to a timestamped log under the gitignored `data/`, and exit non-zero on
    failure so Task Scheduler records it;
  - **never echo a secret** into the log.
- **Missed-run honesty (PRD §8 / §2b).** At run start, compare the last recorded run against the
  expected nightly slots and write a `missed_run` trace record for each 7 pm slot that produced no
  run — so missed runs are counted separately from failures. Keep it simple: read the newest trace's
  timestamp, emit one record per skipped slot. This derives from §8, not from an FR acceptance —
  don't build more than that.
- Write the exact registration command into `emeritus/forecaster/README.md` **for Sarah to run**, e.g.
  ```powershell
  schtasks /Create /TN "Forecaster Nightly" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\Sarah\Documents\28_playground\emeritus\forecaster\scripts\run_nightly.ps1" /SC DAILY /ST 19:00 /RL LIMITED
  ```
  (7 pm local; the machine is on CT. Note the PRD §7 dependency: a sleeping laptop means no run.)

**⚠️ Human-gated.** Registering a scheduled task changes system settings, and the acceptance
criterion spans three nights of real runs. The implementing agent **must not register the task**.
Add to `emeritus/HUMAN-TODO.md`: (1) run the `schtasks` command above, (2) after three nights, run
the verification below, (3) confirm the delivery metric in `STATUS.md`.

**Verify (agent-side, today):** Done when the script runs correctly on demand **in dry-run mode**
— no email is sent:
```powershell
cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
$env:ANTHROPIC_API_KEY = "sk-should-be-ignored"
.\scripts\run_nightly.ps1 -DryRun
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
```
It completes successfully — proving the script strips the shadowing key rather than inheriting it,
since the run would have failed Step 2's auth guard otherwise — writes a trace whose `run_start`
records `auth_mode = "subscription_oauth"`, and leaves no secret in the log file (grep the newest
log under `data/` for the token's first characters and find nothing).

**Verify (Sarah-side, FR-14's actual criterion):** after three consecutive nights, three traces
exist under `data/runs/`, each completed without manual intervention, each stamping
`auth_mode = "subscription_oauth"`:
```powershell
Get-ChildItem data\runs\*.jsonl | Select-Object -Last 3 | ForEach-Object {
  (Get-Content $_ -TotalCount 1 | ConvertFrom-Json).auth_mode
}
```

**Guardrails:** **No secrets in the diff or the log** — `.env` stays gitignored and the script never
echoes the token. Don't register the scheduled task from the agent. Don't add a wake-the-machine
hack, a retry daemon, a cloud runner, or a fallback that runs the job on the API key — a missed run
is recorded honestly (§2b) rather than engineered around.

---

# Coverage map

| FR | Phase | Step(s) | Acceptance criterion verified at |
|---|---|---|---|
| FR-1 Config-driven run | MVP | 3, **18** | Step 18 (pipeline run twice, two configs) |
| FR-2 Beat interface | MVP | 5, **18** | Step 18 (dummy beat visible in output) |
| FR-3 MLB adapter | MVP | 9 | Step 9 (doubleheader + in-progress fixtures) |
| FR-4 NWS adapter | MVP | 10 | Step 10 (grid resolve, 5–8 am, `User-Agent`) |
| FR-5 Astros worker | MVP | 11 | Step 11 (three fixtures → three branches) |
| FR-6 Weather worker | MVP | 12 | Step 12 (freeze threshold both directions) |
| FR-7 Planner | MVP | 8 | Step 8 (plan + zero tool calls) |
| FR-8 Scratchpad | MVP | 7 | Step 7 (adapter invoked once on repeat call) |
| FR-9 Ledger write path | MVP | 16 | Step 16 (rows per run, no collision) |
| FR-10 Escalation | MVP | 13, **14** | Step 13 (candidate first, ordered structure); digest-level ordering re-checked in Step 14 |
| FR-11 Synthesizer | MVP | 14 | Step 14 (provenance test green + red) |
| FR-12 Delivery | MVP | 17 | Step 17 automated; **real send is human-gated** |
| FR-13 Run trace | MVP | 6, **18** | Step 18 (provenance computable from trace alone) |
| FR-14 Scheduler | MVP | 19 | Script verified in Step 19; **3 nights is human-gated** |
| FR-15 Preferences | MVP | 4, **14** | Step 14 (suppression removes item) |
| FR-18 Tool-failure | MVP | 15 | Step 15 (500 → unavailability line, no score) |
| — Agent layer / auth / `FakeAgentClient` | infra | 2 | Step 2 (three auth cases + secret-leak test) |
| — Scaffold + fixtures | infra | 1 | Step 1 (suite green, socket guard fires) |
| FR-9b Ledger dedup | **Later** | — | **Blocked on §9 Q3** — no step, by design |
| FR-16 Feedback loop | **Later** | — | Out of scope this pass |
| FR-17 Remaining beats | **Later** | — | Out of scope this pass |

**No MVP FR is uncovered.** Seven FRs (1, 2, 10, 12, 13, 14, 15) have a structural step plus a later
step where their acceptance criterion actually becomes checkable — that's dependency reality, not a
gap. Two of them (FR-12's real send, FR-14's three consecutive nights) end at a **human gate** by
design: both require Sarah's credentials and real-world time, and neither may be executed by the
implementing agent.

# Open questions carried into the build

Per PRD §9, none of these may be answered by an implementing agent. Surface, don't guess.

| Q | Question | Effect on this build |
|---|---|---|
| Q1 | SMS divergence — email vs restoring SMS | None on v1 code (email ships). Sarah's checkpoint-framing call. **Resolved 2026-08-02: deliberate scope cut, acknowledged in Checkpoint 3.** |
| Q2 | Rules vs judgment for escalation | Step 13 stays **deterministic rules only**. If judgment is wanted, that's a new decision. Still open. |
| Q3 | Item identity for the ledger | **FR-9 stayed write-only** (Step 16); FR-9b got no step. **Answered 2026-08-02 — see Steps 20–22.** |
| Q4 | Unknown syllabus (Modules 3+) | Nothing anticipated. The FR-2 seam and FR-13's over-recording are the hedge. |

---

# Increment 2 — Module 3 (retrieval). Steps 20–22.

Added 2026-08-02, after Checkpoint 3's directions landed. Scope is **only** FR-9b and the new
FR-19; Steps 1–19 are done and must not be regenerated.

**What unblocked this.** PRD §9 Q3 was answered by Sarah, not by an agent: *item identity is not a
property of an item; it is a relation computed at read time between a candidate and what has already
been sent.* Every design choice below follows from that sentence — most importantly, that **nothing
stores an identity**, only vectors that accelerate a read-time comparison.

**The standing constraints from the header still apply**, plus two new ones:

6. **No paid embedding service and no torch.** Local static embeddings only; nothing leaves the
   machine.
7. **The embedder is injected**, like the agent client. Real models fetch weights on first use, and
   the suite forbids network — so tests get a deterministic offline double.

### Step 20 — Retrieval layer (`memory/retrieval.py`)

An `Embedder` protocol; `StaticEmbedder` (model2vec) for the nightly run and `HashingEmbedder` for
tests; a `sqlite-vec` virtual table inside the existing `ledger.db`; a KNN search scoped to one beat
and a time window, returning neighbours with cosine similarity. Add `checkable_fields` to the ledger
row, with an explicit migration — real ledgers predate the column.

**Verify:** an identical line scores ~1.0 (the distance→similarity conversion is easy to get
backwards, and backwards means nothing is ever a duplicate); a cold ledger returns `[]`; a
cross-beat item is never returned; the window and floor both exclude.

### Step 21 — The judgment (`memory/dedup.py`) and FR-19's invariants

Retrieval finds candidates; the model decides include / reframe / suppress. The five invariants are
enforced **around** the model, not requested of it — same reasoning as FR-11.

**Verify:** with a client hard-coded to say SUPPRESS, an item whose score differs from a 0.98-similar
neighbour still survives, **and the client is never called**. An invariant that can be talked out of
is not an invariant.

### Step 22 — Wire into the synthesizer and the runner; acceptance

Dedup runs between suppression and escalation. The synthesizer takes an injected retriever and still
opens no database; `retriever=None` reproduces the v1 digest exactly. The runner shares one ledger
connection between the read and the vector write.

**Verify (FR-9b's acceptance):** the same night run twice — once against an empty ledger, once
against one holding last night's item — produces different digests, with the decision, its reason,
the retrieved neighbours and their scores all in the trace.

| FR | Phase | Step(s) | Where its acceptance is actually asserted |
|---|---|---|---|
| FR-9b Retrieval dedup | **MVP** | 20, 21, **22** | Step 22 (`test_fr9b_acceptance.py`, before/after pair) |
| FR-19 Safety invariants | **MVP** | **21**, 22 | Step 21 (`test_dedup.py`, one test per invariant) |

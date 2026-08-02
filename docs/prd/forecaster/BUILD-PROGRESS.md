# BUILD-PROGRESS — Forecaster

Resumable ledger for the `feature/forecaster` build. Doubles as the `BUILD-LOG.md` the
BUILD-PROMPTS header asks for. **Trust the working tree + `git log` over this file** if they ever
disagree; repair the file to match and note the discrepancy.

- **Branch:** `feature/forecaster`, cut from `dev` (a `dev` branch now exists, so the
  BUILD-PROMPTS "no dev branch, PR into main" note is superseded — this PRs into `dev`).
- **Worktree:** the main checkout. This repo has no `scripts/new-worktree.mjs`.
- **Code:** `emeritus/forecaster/` · **Run tests:** `cd emeritus/forecaster; uv run pytest -q`

## Standing constraints honored by every step

1. Subscription OAuth only. No `ANTHROPIC_API_KEY` fallback, no invented token.
2. No paid signups. `statsapi.mlb.com` + `api.weather.gov` only, both keyless.
3. No live network in the test suite — recorded fixtures + the Step 1 socket guard.
4. No PRD §9 open question gets answered. Surface, don't guess.
5. No secrets in the diff, a log, a trace, or a test.

## Environment blocker carried through the whole build

`CLAUDE_CODE_OAUTH_TOKEN` is **not yet minted** (it is open on `emeritus/HUMAN-TODO.md`), so **no
step in this build may make a live `claude-agent-sdk` call.** Every test runs against Step 2's
`FakeAgentClient`. The consequences are recorded per step below — see Steps 18 and 19, whose
*live-run* verify blocks are blocked on the token, and whose *automated* verifies are green.

## Step ledger

| # | Step | Status | Commit | Notes |
|---|---|---|---|---|
| 1 | Scaffold + no-network harness | done | `d98e672` | |
| 2 | Agent client + auth guard | done | `f9ff183` | |
| 3 | Config loader | done | `052e127` | structural half; FR-1 acceptance lands in Step 18 |
| 4 | Preference profile loader | done | `dee17dd` | loader half; FR-15 acceptance lands in Step 14 |
| 5 | Beat protocol + registry | done | `fe854d5` | contract half; FR-2 acceptance lands in Step 18 |
| 6 | Run trace + provenance checker | done | `82660c9` | FR-13 acceptance on a real run lands in Step 18 |
| 7 | Per-run scratchpad | done | `e3c4e3b` | |
| 8 | Planner | done | `c275425` | |
| 9 | MLB adapter + fixtures | done | `917193a` | |
| 10 | NWS weather adapter + fixtures | done | `52b1cb3` | |
| 11 | Astros beat worker | done | `f290a1d` | |
| 12 | Weather beat worker | done | `2482b0c` | |
| 13 | Escalation rules engine | done | `c56f63d` | injury rule dormant; multi-day horizon not built |
| 14 | Synthesizer + provenance guarantee | done | `876033c` | completes FR-15; no ledger read |
| 15 | Tool-failure handling | done | `e2e8b80` | |
| 16 | Sent-item ledger (write path) | done | `e18d078` | write-only; §9 Q3 untouched |
| 17 | Delivery interface + email | done | `a40762c` | real send is human-gated |
| 18 | Runner CLI + end-to-end wiring | done (automated) / **blocked** (live run) | `6f08c16` | live `--dry-run` blocked on the OAuth token |
| 19 | Nightly scheduler script | done (agent-side) / **human-gated** (3 nights) | `636bd54` | task NOT registered by the agent |
| 20 | Retrieval layer + ledger migration | done | `b88be3f` | §9 Q3 answered by Sarah, not by the build |
| 21 | Dedup judgment + FR-19 invariants | done | `b88be3f` | model enforced *around*, not *asked* |
| 22 | Synthesizer + runner wiring, acceptance | done | `874ba80`, `1077db2` | before/after pair green |

## Per-step log

### Step 1 — Scaffold `emeritus/forecaster/` and the no-network test harness — **done**

- `uv sync` resolves on **Python 3.12.4**; runtime deps `httpx`, `claude-agent-sdk` (0.2.128),
  `python-dotenv`; dev dep `pytest` (9.1.1). Nothing else added.
- Harness: `tests/conftest.py` gives `load_fixture`, `Route`, `mock_transport` (a recording
  `httpx.MockTransport`), and `fixture_client`. The `RecordingTransport` keeps every request so
  Step 10 can assert on the `User-Agent` header.
- Socket guard: `autouse` fixture patching `socket.socket.connect`/`connect_ex` to raise
  `NetworkAccessError`. No new dependency (`pytest-socket` not needed).
- **Deviation (small):** tests import the harness as `from tests.conftest import …` rather than
  bare `conftest`, because Step 1's own layout specifies `tests/__init__.py`, which makes `tests` a
  package and takes bare-`conftest` imports off `sys.path`.
- Verify observed: `uv run pytest -q` → `4 passed in 1.39s`. `git status` shows no `.env`, no
  `data/`, no `.venv/` (confirmed with `git check-ignore -v`).
- Next: Step 2.

### Step 2 — Agent client + hard auth guard — **done**

- `forecaster/agent.py`: `assert_subscription_auth()`, `AgentResponse`, the
  `AgentClientLike` protocol, `ClaudeAgentClient` (real), and `FakeAgentClient`.
- SDK surface confirmed against the **installed** `claude-agent-sdk 0.2.128` rather than
  from memory: `query(prompt=…, options=ClaudeAgentOptions(...))` is async and yields
  `AssistantMessage` / `ResultMessage`; `ClaudeAgentOptions` really does take `effort`
  (`low|medium|high|xhigh|max`) and `ResultMessage` carries `usage`, `duration_ms`,
  `duration_api_ms`. The wrapper is sync (`asyncio.run`) so the pipeline stays plain.
- The auth guard raises on `ANTHROPIC_API_KEY` **even when set to an empty string** — an
  empty value still occupies the precedence slot.
- **Deviation (Step 1 amended):** the socket guard now allows **loopback** and blocks
  everything else. On Windows `asyncio.run()` builds its proactor self-pipe from a
  `socket.socketpair()` over 127.0.0.1, so a blanket block broke every asyncio test
  without blocking a single outbound request. `statsapi.mlb.com` / `api.weather.gov`
  remain unreachable, and nothing in this project serves on loopback.
- **Interface shape (a small addition to the prompt's spec):** `complete()` takes a
  `structured` mapping alongside the prompt. That is what lets `FakeAgentClient` derive
  its response from the caller's own values, which is the whole basis of Step 14's
  provenance test — the fake can only *phrase*, never originate.
- Verify observed: `uv run pytest tests/test_agent.py -q` → `12 passed`; full suite
  `uv run pytest -q` → `16 passed in 1.39s`. Three auth cases + secret-leak test +
  shared-interface test parametrized over both clients (real one's SDK call stubbed).
- Next: Step 3.

### Step 3 — Config loader (`config.toml`) — **done**

- `config.toml` carries `[run]` (send time, timezone, and the 5–8 am run window),
  `[beats]`, `[location]`, `[delivery]`, `[escalation]` (threshold, horizon, watched
  players, **and the ordered `rules` list** Step 13 uses for tie-breaking), `[team]`.
- `forecaster/config.py`: frozen dataclasses + `load_config` / `parse_config` /
  `enabled_beats` / `config_digest`. Every missing or wrong-typed key raises `ConfigError`
  naming the section and key — no silent defaults. No credentials in `config.toml`.
- Verify observed: `uv run pytest tests/test_config.py -q` → `9 passed in 0.15s`, and the
  PowerShell grep (`Get-ChildItem forecaster -Recurse -Filter *.py | Where-Object
  { $_.Name -ne 'config.py' } | Select-String 'Austin|America/Chicago|EWX'`) returned
  **nothing**. That grep is also encoded as a test, so it keeps holding as later steps land.
- **FR-1's full acceptance** (pipeline run twice with two configs) needs a pipeline —
  Step 18. This step is the structural half; `enabled_beats` differing by config alone is
  tested here.
- Next: Step 4.

### Step 4 — Preference profile loader (`preferences.toml`) — **done**

- `preferences.toml`: `watched_players`, `[topics]` weights, and `[[suppressions]]` rules
  that match on `beat` + `contains` and/or a `field`/`equals` pair.
- `forecaster/memory/preferences.py`: `Preferences`, `SuppressionRule`,
  `SuppressionDecision`, `load_preferences`, `suppression_match`. Read-only — nothing
  writes, learns, weights by history, or embeds.
- Every rule is **required** to carry an `id` and a `reason`; a rule with no match criteria
  or a duplicate id is rejected at load. A rule that fires returns a sentence naming itself
  and quoting its own criteria, which is what Step 6's trace records.
- Items are matched **structurally** (`beat` / `text` / `fields`) rather than by importing
  `BeatItem`, because preferences load before any beat exists. Step 5's `BeatItem` satisfies
  the shape; the tests use a stub.
- **Gotcha worth recording:** `watched_players` has to sit *above* the first `[table]`
  header in the TOML. Placed after `[topics]` it becomes `topics.watched_players` and the
  loader rejects it as a non-numeric weight. Caught by the test, not by inspection.
- Verify observed: `uv run pytest tests/test_preferences.py -q` → `11 passed`; full suite
  `36 passed in 1.45s`.
- **FR-15's acceptance** (adding a rule removes an item from the digest) needs the
  synthesizer — Step 14.
- Next: Step 5.

### Step 5 — `Beat` protocol, `BeatResult`, and the registry — **done**

- `forecaster/beats/base.py`: `Beat`, `BeatContext`, `BeatItem`, `BeatResult`,
  `ObservationRef`, plus the two collaborator `Protocol`s (`TraceWriter`,
  `ScratchpadLike`) so nothing forward-references Steps 6/7. `base.py` imports neither.
- `BeatResult` enforces its own invariants in `__post_init__` rather than trusting
  callers: unavailable requires a non-empty `error`; available may not carry one; an
  escalation candidate must give a reason; an unavailable result may not declare
  `checkable_fields` (there is nothing to state as fact when the source was unreachable).
  `BeatResult.unavailable()` is the FR-18 constructor.
- Registry: `register_beat` / `unregister_beat` / `registered_beats` / `get_beats`.
  `get_beats` returns beats in **config declaration order**, and enabling a beat nobody
  registered raises `LookupError` — a typo in `[beats]` must not quietly shrink the digest.
- A test asserts `base.py` has no module-scope import of a concrete beat, so the FR-2 seam
  keeps holding rather than being a one-time claim.
- **Fixtures captured in this step** (needed by Steps 9–12, recorded early while the
  network was to hand): `mlb_doubleheader.json` (real Astros DH, 2026-04-30),
  `mlb_final.json` (2026-07-26), `mlb_no_game.json` (real off day, 2026-07-02),
  `nws_points_austin.json` (confirms grid **EWX 156,91** live), `nws_hourly_austin.json`.
  Two are synthetic and labeled as such in `tests/fixtures/README.md`:
  `mlb_in_progress.json` (no Astros game was live at capture time) and
  `nws_hourly_austin_freezing.json` (Austin in July does not produce a 28 °F morning; only
  the three 05:00–08:00 periods on 2026-07-28 were edited).
- Verify observed: `uv run pytest tests/test_beats_base.py -q` → `17 passed in 0.07s`.
- **FR-2's full acceptance** (dummy beat visible in the delivered output) needs the
  pipeline — Step 18.
- Next: Step 6.

### Step 6 — Run trace + the provenance checker — **done**

- `forecaster/trace.py`: `Trace` writes JSON-lines to `data/runs/<run_id>.jsonl` with
  record types `run_start` (incl. **`auth_mode`** for FR-14), `plan`, `tool_call`,
  `observation`, `decision`, `beat_result`, `escalation`, `digest`, `delivery`,
  `missed_run`, `run_end`. `tool_call` returns the `observation_id` a
  `BeatResult.observations` entry points at — that link is what makes provenance computable.
- **Secret guard:** `_assert_no_secret` refuses to write any record whose serialization
  contains the live value of `CLAUDE_CODE_OAUTH_TOKEN` or `SMTP_PASSWORD`. Tested.
- `check_provenance(trace_path, digest_text=None)` defaults the digest to the one the
  trace recorded, so it runs on the trace file **and nothing else**. Three checks:
  - **support** — each declared checkable value must be findable in a linked observation
    (`unsupported_claim`);
  - **fidelity** — each observation-backed rendering becomes a numbers-are-wildcards
    template; a digest passage matching the template with *different* numbers is an
    `altered_claim`. This is what catches "a score changed by one";
  - **honest degradation** — an unavailable beat must contribute no checkable field and
    must be named in the digest (`missing_unavailability_line`, FR-18 / §2c).
  A declared value the digest simply doesn't mention is a **note**, not a violation —
  FR-11 says "appears only if it matches", not "must appear".
- **Deviation worth knowing:** template matching is **case-insensitive**. The first draft
  was case-sensitive and a tampered temperature slipped through purely because the model
  had recased the sentence ("Run-window" → "run-window"). Recasing is allowed; changing
  the numbers inside a sentence is not.
- Verify observed: `uv run pytest tests/test_trace.py -q` → `17 passed`; full suite
  `70 passed in 1.64s`. Every trace line parses as JSON (the PowerShell
  `ConvertFrom-Json` verify, encoded as a test). `data/` is untracked.
- **FR-13's full acceptance** (a *completed run*'s trace) lands in Step 18.
- Next: Step 7.

### Step 7 — Per-run scratchpad (short-term memory) — **done**

- `forecaster/memory/scratchpad.py`: `Scratchpad` with `get_or_call`, `note`,
  `note_missing`, and counters. The cache key is the **normalized call signature**
  (`adapter` + sorted-key JSON of the arguments), so the same call with its kwargs in a
  different order is still one call — tested.
- Both the hit and the miss are written to the trace as a `decision`, so a
  served-from-cache call is *visible* rather than looking like a call that never happened.
- Not persisted: no file, no SQLite, no TTL, no size limit, no cross-run reuse. Two tests
  cover it — one asserts nothing lands on disk, one asserts a fresh scratchpad shares
  nothing with the previous one.
- Verify observed: `uv run pytest tests/test_scratchpad.py -q` → `9 passed in 0.10s`;
  the repeat-call test asserts `adapter.call_count == 1` after two identical requests.
- Next: Step 8.

### Step 8 — Planner — **done**

- `forecaster/planner.py`: `plan_run(config, preferences, now)` → `RunPlan`, one
  `PlanEntry` per beat carrying a non-empty completion criterion, plus a `skipped` map
  with the reason for anything that didn't make the cut. Written into the trace as a
  `plan` record; skips go in as `decision`s.
- The criterion comes from **asking the beat** (`beat.completion_criterion`), falling back
  to a generic contract. Switching on the beat name here would have put the
  Astros/weather specifics in the planner, which is exactly what FR-2's seam forbids.
- Preference weights are respected: weight 0 skips the beat, and higher weights plan first.
- **FR-7's acceptance:** a test injects a counting fake adapter, a `Scratchpad`, and Step
  2's `FakeAgentClient`, and asserts **every** call count is 0. A second test asserts
  `planner.py` has no import of `beats.astros` / `beats.weather`.
- Verify observed: `uv run pytest tests/test_planner.py -q` → `10 passed in 0.12s`.
- Next: Step 9.

### Step 9 — MLB Stats API adapter + fixtures — **done**

- `forecaster/tools/mlb.py`: `fetch_schedule(team_id, start_date, end_date=None, *,
  client, tz_name)` → typed `Game` list with `game_pk`, `abstract_game_state`,
  `detailed_state`, `start_time_utc`, `start_time_local`, home/away teams and scores,
  `is_doubleheader`, `game_number`. Accepts a **date range** so FR-5's "preview the next
  game" branch has something to call.
- Failure contract: HTTP error, timeout, or unparseable payload raises `AdapterError`
  carrying the status. It never returns a partial or guessed `Game`. An **empty** result
  (a real off day) is an empty list, not an error.

**⚠️ BUILD-PROMPTS / PRD inaccuracy found while building.** Both say
`abstractGameState` is *"Final / In Progress / Preview"*. The live endpoint returns
**`Live`** for a game in progress — `"In Progress"` is the `detailedState`. Verified
against the real payload. The adapter exposes both fields and its `STATE_LIVE`
constant is `"Live"`; `mlb_in_progress.json` was hand-edited to the real shape. Nothing
downstream should branch on the string `"In Progress"` from `abstractGameState`.

- **Deviation — one dependency added beyond Step 1's four:** `tzdata` (win32 only).
  Windows ships no system tz database, so stdlib `zoneinfo` raises
  `ZoneInfoNotFoundError` on `America/Chicago` and FR-3's UTC→local conversion is
  impossible without it. Not gold-plating — the eight localization tests fail without it.
- Verify observed: `uv run pytest tests/test_mlb.py -q` → `13 passed`. The FR-3
  criterion is asserted directly: the doubleheader fixture returns **2** games, both
  `Final`, both flagged `is_doubleheader`, game numbers `[1, 2]`, with local start times
  that carry the configured zone and the same instant as UTC.
- Next: Step 10.

### Step 10 — NWS weather adapter + fixtures — **done**

- `forecaster/tools/weather.py`: `fetch_hourly_forecast(lat, lon, *, client)` does the two
  hops — `/points/{lat},{lon}` to resolve the grid office + x/y, then the
  `properties.forecastHourly` URL that response hands back. The grid is **resolved, not
  hardcoded**; a test asserts the second request URL is literally the one the first
  response returned.
- `run_window_periods(periods, day=, start=, end=)` slices the 5–8 am local window; the
  payload's times already carry the grid's offset, so it compares wall-clock hours rather
  than converting twice. `next_morning(now)` is tomorrow, because the digest sends at 7 pm.
- **`User-Agent` on every request**, asserted by inspecting the recorded requests in
  `MockTransport` — both hops, not just the first. A 403 raises an `AdapterError` whose
  message names the header and says "this is a rejected request, not an outage", so the
  PRD §8 failure mode cannot be mistaken for a downed service.
- Same failure contract as Step 9: HTTP error / timeout / unparseable payload →
  `AdapterError`, never a substituted value.
- Live confirmation during capture: Austin (30.2672, -97.7431) resolves to grid
  **EWX 156,91**, exactly as the PRD says. A request with no `User-Agent` really does
  return 403 (checked with curl before writing a line of this).
- Verify observed: `uv run pytest tests/test_weather.py -q` → `12 passed`; full suite
  `114 passed in 1.79s`.
- **Not implemented on purpose:** the multi-day "freeze within N days" horizon. FR-6's
  acceptance is scoped to the next morning's window, and extending the forecast range is
  an open decision for Sarah — see the Step 13 note.
- Next: Step 11.

### Step 11 — Astros beat worker (ReAct loop) — **done**

- `forecaster/beats/astros.py`: `AstrosBeat` implements the protocol and registers itself.
  The loop calls today's schedule, inspects the state, decides whether that is enough, and
  makes a **second** call only when the branch needs one — the look-ahead range to preview
  the next game (final branch), or the look-back range for the last completed game (live
  branch). The no-game branch makes exactly one call. Every branch and its reason is a
  `decision` record.
- Four branches, all asserted on the structured `BeatResult`, never on prose:
  final-and-preview-next, live-plus-last-completed, preview-only ("not started"), and
  no-game. The **no-game branch returns `available=True`** — an off day (and the whole
  offseason) is information, not a failure.
- **Deviation from the Step 11 prompt, resolved in favour of the PRD.** The prompt says to
  put "localized start time" in `checkable_fields`. A localized rendering is *derived*, not
  observed, so it can never match an observation and would fail its own provenance check;
  and FR-11's own list is "scores, game state, temperature, wind, precipitation
  probability", with dates and times explicitly called prose. So the beat declares the
  **observed UTC timestamp** as the checkable value and keeps the localized rendering in
  the item's `fields` and text as prose. The PRD is the spec of record.
- `escalation_signals["injuries"]` is left unpopulated, with a test asserting it. No injury
  feed exists in v1 and adding one is new scope.
- New real fixture: `mlb_preview.json` (2026-07-28, genuinely `Preview`) — recorded, not
  synthetic.
- Verify observed: `uv run pytest tests/test_beat_astros.py -q` → `11 passed in 0.21s`.
  Includes the scratchpad test (two identical runs, one HTTP request) and a test that
  `astros.py` imports no planner/synthesizer/delivery.
- Next: Step 12.

### Step 12 — Weather beat worker — **done**

- `forecaster/beats/weather.py`: `WeatherBeat` produces the next morning's 5–8 am
  run-window forecast (low/high, wind, max precipitation probability) and evaluates the
  freeze threshold **read from config**. The comparison is recorded as a `decision` with
  both the low and the threshold on it.
- `checkable_fields` is exactly `run_window_low_f`, `run_window_high_f`,
  `precip_probability_pct`, `wind_speed` — the four values FR-11 polices, no more.
- **FR-6's acceptance, both directions:** `nws_hourly_austin_freezing` (28 °F) →
  `escalation_candidate=True`; the real `nws_hourly_austin` (76 °F) → `False`. A third
  test proves the threshold is config-driven: the *same* fixture flips outcome when the
  configured threshold changes to 80 °F.
- A forecast that doesn't cover the window returns an **unavailable** result rather than
  an invented one. A test asserts the beat adds no "what to wear" advice.
- **Not implemented, on purpose:** the multi-day "freeze within N days" horizon FR-10's
  prose implies. The adapter fetches the next morning only and FR-6's acceptance is scoped
  to that window; extending the forecast range is an open decision for Sarah.
- Verify observed: `uv run pytest tests/test_beat_weather.py -q` → `10 passed`; full suite
  `135 passed in 1.91s`.
- Next: Step 13.

### Step 13 — Escalation rules engine — **done**

- `forecaster/escalation.py`: `apply_escalation(results, config, *, trace=None)` →
  `OrderedItems`. Pure, deterministic, **no model call** (a test asserts the module never
  imports `agent`). Promotions carry the rule name and reason; nothing is dropped.
- Ordering: promotions sort by the **config's `[escalation].rules` index** (priority),
  then beat order; unpromoted items keep base order. Swapping the two rule names in config
  swaps the output order — tested both ways.
- An unknown rule name in config raises `LookupError` rather than silently not firing.
- **Every** rule evaluation is written to the trace, fired or not, so PRD §8's "escalating
  everything is the same as escalating nothing" is observable from day one rather than a
  surprise in week three. Test asserts 4 records for 2 beats × 2 rules.

**Two spec gaps handled rather than papered over:**

1. **The injury rule has no v1 data source.** Implemented against
   `escalation_signals["injuries"]` and tested with a *synthetic* `BeatResult`, so the rule
   exists and is correct — but it is **dormant**: no v1 beat populates that key, and its
   not-fired reason literally says "the rule is implemented but dormant". No injury feed
   was added and no roster page is scraped.
2. **"Within N days" exceeds the fetched horizon.** `freeze_horizon_days` is read from
   config and recorded in the fired reason, but the rule applies over the horizon the data
   actually covers — the next morning's run window (FR-6). **A multi-day horizon needs a
   forecast-range decision from Sarah first.**

- PRD §9 **Q2 (rules vs judgment)** is untouched and stays open; the module docstring says
  so, and nothing here reaches for the model.
- Verify observed: `uv run pytest tests/test_escalation.py -q` → `13 passed in 0.15s`.
  FR-10's criterion is asserted on `ordered.beat_order[0] == "weather"`, not on prose.
- Next: Step 14.

### Step 14 — Synthesizer + the provenance guarantee — **done**

- `forecaster/synthesizer.py`: `synthesize(results, config, preferences, trace, *,
  agent_client)` → `Digest`. Suppression → escalation ordering → composition through the
  **injected** client. The model receives only `{"lines": [...], "unavailable": [...]}`,
  every entry of which is a beat's own rendered text — a test asserts every line handed to
  the client was produced by a beat.
- **Provenance is structural, not a prompt.** After composition the digest is written to
  the trace and `check_provenance` runs over trace + digest. A violation raises
  `ProvenanceError` and **fails the run**; it does not degrade to a warning. A test proves
  it with a deliberately fabricating client that changes "Astros 3" to "Astros 7".
- **FR-11 both directions:** a clean synthetic run passes; the same run with a score
  changed by one produces an `altered_claim` violation.
- **FR-15 completed:** the same seeded run, synthesized with and without a suppression
  rule, contains and then does not contain the matching item; the trace names the rule and
  quotes its reason.
- **FR-10 re-checked at digest level:** with the weather beat flagged freezing, the weather
  line appears before the Astros line in the rendered text.
- **Scope correction honored.** FR-11's prose says the synthesizer "applies the ledger
  check" — that check *is* FR-9b, `[Later]` and blocked on §9 Q3. This step applies
  **escalation ordering + preference suppression only**. A test parses `synthesizer.py`
  with `ast` and asserts no ledger import and no ledger name anywhere in the code.
- Verify observed: `uv run pytest tests/test_synthesizer.py -q` → `10 passed in 0.30s`.
- Next: Step 15.

### Step 15 — Tool-failure handling (the no-fabrication guarantee) — **done**

- `beats/base.py` gains `run_beat_safely(beat, context)`: any `AdapterError`, timeout,
  parse failure, **or outright bug** becomes a `BeatResult` with `available=False`, a
  populated `error`, and empty `checkable_fields`. The error goes into the trace as an
  observation plus a `beat_unavailable` decision whose reason says "reporting it as
  unavailable rather than substituting a value".
- Catching bare `Exception` is deliberate and documented: narrowing to `AdapterError`
  would let an unrelated bug in one beat take down a run that could still have delivered
  the other beat's content.
- `synthesizer.unavailability_line()` renders "Couldn't reach {beat} tonight ({error})."
  and the synthesizer **appends it if the composer left it out** — a failed beat cannot
  silently drop out even if the model ignores it. Tested with a deliberately silent client.
- **FR-18's acceptance, exactly:** the MLB-500 fixture produces a digest that (a) contains
  an explicit unavailability line naming the beat, (b) contains **no** score
  ("Astros 3", "White Sox 12", "Final:" all absent), and (c) passes `check_provenance`.
  The weather-timeout case does the same.
- Also tested: one beat failing still ships the other's content; no hidden retry (exactly
  one HTTP request); no cached-from-yesterday substitute; the model is handed a
  pre-written unavailability line rather than a gap.
- Verify observed: `uv run pytest tests/test_tool_failure.py -q` → `9 passed`; full suite
  `167 passed in 2.53s`.
- Next: Step 16.

### Step 16 — Sent-item ledger, write path — **done**

- `forecaster/memory/ledger.py`: SQLite at the gitignored `data/ledger.db`, one row per
  delivered item with `run_id`, `beat`, `sent_at`, `rendered_text`,
  `source_observation_id`, plus a surrogate autoincrement `id`. Schema creation is
  idempotent. `record_delivered_items(digest, run_id)` appends; it is wired into the
  runner **after a successful delivery** in Step 18.
- **Write-only, and tested as such.** Four guardrail tests: the schema has no semantic
  identity column (asserted against `PRAGMA table_info`, with `item_identity`,
  `fingerprint`, `content_hash`, `story_id`, `dedup_key` all explicitly absent); no index
  is `UNIQUE`; the module's *code* (parsed with `ast`, so the docstring's explanation
  doesn't trip it) references no hash, similarity, or embedding; and no module other than
  `cli.py` may import it.
- The two-run test asserts the identical rendered text appears **twice**, on purpose:
  without an answer to §9 Q3 there is no basis for calling them "the same story".
- Verify observed: `uv run pytest tests/test_ledger.py -q` → `8 passed in 0.33s`.
- Next: Step 17.

### Step 17 — Delivery interface + email implementation — **done**

- `delivery/base.py`: the one-method `Deliverer` protocol, `DeliveryResult`, and
  `FakeDeliverer` (captures in memory, sends nothing). `delivery/email.py`:
  `EmailDeliverer` over `smtplib` + STARTTLS, reading all six SMTP settings from the
  gitignored `.env`. `make_deliverer(config)` selects on `[delivery].kind`.
- A missing setting raises `DeliveryConfigError` **naming the variable** — parametrized
  over all six. It never falls back to a default address.
- Secret hygiene: `SmtpSettings.__repr__` redacts the password, `EmailDeliverer.__repr__`
  omits it, the trace's `delivery` record carries the target address only, and three tests
  assert the password appears in none of them.
- All four verify cases pass with **zero SMTP socket activity** — `smtplib.SMTP` is
  replaced by a mock, and Step 1's socket guard would fail the test if it weren't.
- **⚠️ Human gate (FR-12's other half).** The digest arriving in Sarah's inbox needs real
  credentials and a real send. **Not done by the agent.** Step 18 hands over the exact
  command and adds the HUMAN-TODO entries.
- Verify observed: `uv run pytest tests/test_delivery.py -q` → `18 passed in 0.32s`.
- Next: Step 18.

### Step 18 — Runner CLI + end-to-end wiring — **done (automated) / live verify BLOCKED**

- `forecaster/cli.py`: `run_pipeline(...)` (fully injectable) plus `main()` with
  `--config`, `--preferences`, `--dry-run`, `--send-test`. Order: open trace →
  `assert_subscription_auth` → load config + preferences → plan → run each enabled beat
  behind Step 15's wrapper **with a fresh `Scratchpad` per beat** → synthesize (escalation
  + provenance enforced) → deliver → **on delivery success** write the ledger rows → close
  the trace with timings and token usage.
- **All three end-to-end acceptance criteria land, off fixtures, with fakes:**
  - **FR-1** — the pipeline runs twice with two configs and executes different beat sets
    (`["astros","weather"]` vs `["astros"]`), and the difference shows in the *delivered
    text*, not just in bookkeeping.
  - **FR-2** — a `DummyBeat` (one class) plus one `[beats]` entry appears in the delivered
    digest. A companion test parses `planner.py`, `synthesizer.py`, `delivery/base.py` and
    `delivery/email.py` with `ast` and asserts none of them imports a concrete beat — so
    "zero edits" is checked mechanically rather than asserted.
  - **FR-13** — a completed run's trace passes `check_provenance(trace_path)` with **no
    digest argument**: the trace records its own digest, so the §2 metric computes from
    that file and nothing else.
- Also covered: one beat failing still delivers, still traces, and still writes ledger
  rows; ledger rows are written **only** after a successful delivery; a fabricating client
  fails the run with `run_end.status == "provenance_failed"` and writes zero ledger rows.
- Verify observed: `uv run pytest tests/test_cli.py -q` → `11 passed in 0.58s`; full suite
  `204 passed`.

**🚫 BLOCKED — the live `--dry-run` verify.** It needs `CLAUDE_CODE_OAUTH_TOKEN`, which is
not yet minted (open on `emeritus/HUMAN-TODO.md`). Attempted and recorded verbatim:

```
> uv run python -m forecaster.cli --dry-run
refusing to start: CLAUDE_CODE_OAUTH_TOKEN is missing or empty. Mint one with
`claude setup-token` and put it in the gitignored .env. The pipeline cannot run
without it, and it will not fall back to an API key.
EXIT=2
```

The guard works exactly as designed — this is the *intended* failure, not a defect. The
shadow guard was confirmed live too:

```
> $env:ANTHROPIC_API_KEY="sk-should-be-ignored"; uv run python -m forecaster.cli --dry-run
refusing to start: ANTHROPIC_API_KEY is set in this environment. It shadows
CLAUDE_CODE_OAUTH_TOKEN and would bill per token instead of drawing on the Claude
subscription. ...
EXIT=2
```

**To unblock:** mint the token, put it in `emeritus/forecaster/.env`, then run the
`--dry-run` command in the README. Nothing in the code needs to change.

**⚠️ Human gate — FR-12's real send.** Not run by the agent. Command is in the README and
on HUMAN-TODO.
- Next: Step 19.

### Step 19 - Nightly scheduler (Windows Task Scheduler) - **done (agent-side) / human-gated**

- `scripts/run_nightly.ps1`: strips `ANTHROPIC_API_KEY` as its **first executable
  statement**, loads the gitignored `.env` (and explicitly refuses to re-add
  `ANTHROPIC_API_KEY` from it), `Set-Location`s to the project, accepts a **`-DryRun`**
  switch, logs to the gitignored `data\logs\`, and exits with the CLI's exit code.
- **Missed-run honesty (PRD 8 / 2b).** `cli.missed_slots()` compares the newest trace's
  `run_start` against the expected nightly slots, and the runner emits one `missed_run`
  record per dark slot - computed **before** tonight's trace is opened, so the run does
  not see itself. Missed runs are a distinct record type from delivery failures; the two
  have different fixes. A corrupt old trace does not block tonight.
- **Deviation from the first draft, found by running it:** the script originally used
  `& uv @CliArgs *>&1 | Tee-Object`. On Windows PowerShell 5.1 that wraps every stderr
  line in an `ErrorRecord` *and* Tee-Object writes UTF-16 into a UTF-8 log, producing a
  file with a space between every character. Replaced with `Start-Process` plus explicit
  redirect files. The mangled log is what caught it, not review.

**Verify (agent-side) - observed, verbatim.** With the shadowing key deliberately set:

```
> $env:ANTHROPIC_API_KEY = 'sk-should-be-ignored-0123456789'
> .\scripts\run_nightly.ps1 -DryRun
refusing to start: CLAUDE_CODE_OAUTH_TOKEN is missing or empty. ...
log: ...\data\logs\nightly-20260727-160215.log
SCRIPT_EXIT=2
```

and the log it wrote:

```
=== Forecaster nightly run 20260727-160215 ===
project: C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
dry-run: True
ANTHROPIC_API_KEY present: False
CLAUDE_CODE_OAUTH_TOKEN present: False
--- stderr ---
refusing to start: CLAUDE_CODE_OAUTH_TOKEN is missing or empty. ...
exit code: 2
```

**`ANTHROPIC_API_KEY present: False` is the proof the strip works** - the key was set in
the calling shell, and the CLI reported the *missing-token* error rather than the
*shadowing* error, which it would have reported had the key survived. Exit code 2
propagated. Grepping the log for the sentinel key value returns **0** matches.

**BLOCKED - not fully verifiable here.** The step's stated verify ("completes
successfully") also needs `CLAUDE_CODE_OAUTH_TOKEN`, so a trace stamping
`auth_mode = "subscription_oauth"` was **not** produced by this run. That assertion is
covered in the automated suite instead: `test_cli.py` asserts
`run_start.auth_mode == "subscription_oauth"` on a completed run.

**HUMAN-GATED, per instruction:** the scheduled task was **not registered**, and FR-14's
"three consecutive scheduled runs" was **not attempted**. Both commands are in the README
and on `emeritus/HUMAN-TODO.md` (item 4).

- Verify observed: `uv run pytest tests/test_nightly.py -q` -> `17 passed in 0.36s`;
  full suite `221 passed in 3.49s`.
- **All 19 steps complete.** Next: trackers + PR.

---

## Increment 2 — Module 3 (retrieval), 2026-08-02

Branch `feature/fr-9b-retrieval`, cut from a newly created `dev` (this repo had only `main`
after graduating; the `dev` referenced above was the playground's).

### Step 20 — Retrieval layer (`memory/retrieval.py`) — **done**

- `Embedder` protocol + `StaticEmbedder` (model2vec `minishlab/potion-retrieval-32M`, **512
  dims**, no torch) + `HashingEmbedder` (deterministic, offline, tests only). Vector index is a
  `sqlite-vec` vec0 virtual table **inside the existing `ledger.db`**, keyed by `sent_items.id`.
- **Deps added:** `sqlite-vec 0.1.9`, `model2vec 0.8.2`, and `numpy` — 15 packages total, **no
  torch**. Verified live before writing any code: `vec_version() -> v0.1.9`.
- `sent_items` gains `checkable_fields` (JSON). **Explicit migration**, because SQLite has no
  `ADD COLUMN IF NOT EXISTS` and a `CREATE TABLE IF NOT EXISTS`-only schema would silently leave
  an existing ledger without the column. Tested against a hand-built legacy database.
- **The measurement that shaped the whole design**, taken before the design was fixed:

  ```
  "Final: Houston Astros 4, Texas Rangers 2."
      vs "Final: Houston Astros 5, Texas Rangers 2."   cosine 0.9859
  "Astros beat the Rangers 4-2." vs "…5-2."            cosine 0.9746
  "Astros beat the Rangers 4-2." vs a weather line     cosine 0.0037
  ```

  Static embeddings are near-blind to numerals. Two *different games* are near-duplicates.
- **Gotcha worth recording:** sqlite-vec's KNN returns **distance**, not similarity. Over unit
  vectors, `similarity = 1 - d²/2`. Getting that backwards means nothing is ever a duplicate and
  every test still passes for the wrong reason, so there is a test asserting an identical line
  scores ~1.0.

### Step 21 — Dedup judgment + FR-19 — **done**

- `memory/dedup.py`. Retrieval narrows; the model judges; five invariants bound what the judgment
  may do. Enforced **around** the model — `test_the_model_is_not_even_asked_when_a_checkable_value_moved`
  asserts the client is never called, because an invariant that can be talked out of is not one.
- **Bug found by a test I wrote to document intent.** `_checkable_values_differ` compared values
  as strings, so a field that round-tripped through JSON as `"41.0"` against an int `41` read as
  *new information* — which would have quietly disabled suppression for every numeric field, in
  the safe direction, invisibly. Now numeric-aware. Worth remembering: the failure was silent and
  test-shaped, not crash-shaped.

### Step 22 — Wiring + acceptance — **done**

- Dedup runs between suppression and escalation ordering. The synthesizer takes an **injected**
  retriever and still opens no database and names no table — `test_the_synthesizer_does_not_read_the_ledger`
  survived FR-9b unchanged, which is the FR-2 seam doing its job.
- `retriever=None` reproduces the v1 digest exactly, asserted.
- **Four ledger guardrail tests were revised, not deleted.** They existed to enforce "§9 Q3 is
  unanswered". Q3 is answered, so the guard changed shape: no identity may still ever be *written
  down*, and nothing outside the retrieval layer may query the table. Both still asserted.
- **Verify observed:** `uv run pytest -q` → **256 passed in 4.22s** (was 221). Still no network
  and no model call anywhere in the suite.
- **The demonstration, captured with the real embedder** (no model call — scripted client):

  ```
  RUN 1 — empty ledger
    DIGEST: 'Final: Houston Astros 4, Texas Rangers 2.'
    dedup:  include — 'no prior item within the retrieval window'

  RUN 2 — ledger holds last night; SAME game reported again
    retrieved: [('Final: Houston Astros 4, Texas Rangers 2.', 1.0)]
    DIGEST: ''
    dedup:  suppress — 'judged to add nothing over item #1 (cosine 1.0000)'

  RUN 3 — ledger holds 4-2; a DIFFERENT game (5-2) reported
    retrieved: [('Final: Houston Astros 4, Texas Rangers 2.', 0.9859)]
    DIGEST: 'Final: Houston Astros 5, Texas Rangers 2.'
    dedup:  reframe, forced=True — 'near-duplicate wording (cosine 0.9859) but a
            checkable value differs … suppression is not permitted'
    provenance ok: True
  ```

  Run 3 is the point: 0.9859 similarity, and the item survives anyway, with the model never
  consulted.

**Still blocked, unchanged:** `CLAUDE_CODE_OAUTH_TOKEN` is not minted, so no live run has
happened. FR-9b has never executed against an organically accumulated ledger — the demonstration
above seeds one. Recorded as DIVERGENCES row 4.

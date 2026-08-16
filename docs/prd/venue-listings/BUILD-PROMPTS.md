# BUILD PROMPTS — Venue listings beat, v1 (ZACH only)

Decomposes [`PRD.md`](PRD.md) **v1: FR-42 … FR-46**. FR-47 (Bass via Ticketmaster) is `[Later]`,
gated on a developer account that does not exist — **do not stub it**. This file continues the
repo step ledger at **Step 40** (parent 1–19, FR-9b 20–22, ai-news 23–34, need-to-know 35–39;
FR-37 consumed no steps).

**Driving note.** Keep [`BUILD-PROGRESS.md`](BUILD-PROGRESS.md) updated after every step and
resume from it in a fresh session: skip `done`, continue from the first `todo`. If the ledger and
`git log` disagree, trust git, repair the ledger, and say so. One commit per step.

**Environment, for every step:**

- Repo: `C:\Users\Sarah\Documents\31 Emeritus`, code under `forecaster/`. Python 3.12 + `uv`.
- Verify command: `cd forecaster; uv run pytest -q` — all green before "done".
- Branch: `feature/venue-listings-beat`, cut from `dev` (`71d4846`), PR'd into `dev`. Never `main`.
- **No network and no model calls in the test suite.** Fixtures via `capture_fixture.py --raw`;
  socket guard stays on. **This beat also makes zero model calls in production** — no test may
  hand it a working agent client; use the exploding-client pattern from
  `tests/test_beat_need_to_know.py::_no_model`.
- **Protected gates — never edit to force green:** the FR-2 seam test in `test_cli.py`, the
  synthesizer seam test, the no-identity guard in `test_ledger.py`, and
  `test_time_scoped_items.py`'s coverage test — it **will** fire when the beat registers; Step 42
  satisfies it with real fixtures (every item this beat emits carries a date field; nothing is
  synthesized, so no FR-27 exemption applies).
- Beat-seam rule: zero edits to `planner.py` or `delivery/` anywhere. `synthesizer.py` is edited
  **only** in Step 43, as a dedup-machinery change (FR-9b/FR-37 precedent), never for beat
  registration.
- No secrets exist in v1 (ZACH is keyless). `TICKETMASTER_API_KEY` belongs to FR-47 and must not
  appear anywhere in this build.
- **Domain gotcha:** the working host is `www.zachtheater.org` — one "t". The intuitive spelling
  bounces through a ticketing-session redirect. Config ships the working host; the fetch follows
  no cross-host redirects.

---

### Step 40 — `[venues]` config + `[retrieval] exempt_beats`  (implements FR-43 and FR-44 config halves)
**Context:** [`PRD.md`](PRD.md) FR-43/FR-44 and §6. `forecaster/forecaster/config.py`,
`forecaster/config.toml`, `forecaster/tests/test_config.py`, `tests/helpers.py`. Mirror the
optional-section contract every beat section follows: absent is valid; enabled-without-section
raises at load.
**Task:** Add a `venues` settings model: `user_agent`, `timeout_seconds`, `window_days`, and a
`venues` list of `{name, kind, url}` entries. Validate: `window_days >= 1`, non-empty `name`/
`kind`/`url`, duplicate venue names rejected (`_reject_duplicates`), and — when the beat is
enabled — a non-empty venue list. Do **not** validate `kind` against a parser registry here;
config stays ignorant of code (the beat reports an unknown kind per venue at run time, Step 42).
Add `exempt_beats` to `RetrievalConfig` (list of beat names, default `[]`), validated as a string
list. Ship `config.toml` with `[beats] venues = false` (until Step 42), the `[venues]` section
(ZACH entry, `kind = "zach_shows"`, the one-"t" URL, `window_days = 14`), and
`[retrieval] exempt_beats = ["venues"]`. Add an opt-in `VENUES_CONFIG` dict to `tests/helpers.py`
following `NEED_TO_KNOW_CONFIG`'s pattern (a `.test` host URL).
**Verify:** `uv run pytest -q` green. New tests: config without `[venues]` still valid and every
existing test passes; enabled-without-section raises naming the section; empty venue list with
the beat enabled raises; duplicate venue names raise; `window_days = 0` raises;
`exempt_beats` defaults to `[]` when absent (assert on an existing base config) and parses when
present; the real `config.toml` parses with `venues = false` and `exempt_beats == ["venues"]`.
**Guardrails:** No parser, no beat class, no synthesizer change yet. No `min_*`/taste knobs —
the re-scope stripped taste from this beat and config must not sneak it back.

### Step 41 — ZACH parser + captured fixtures  (implements FR-42)
**Context:** [`PRD.md`](PRD.md) FR-42 and §6/§8. New `forecaster/forecaster/tools/venues.py`;
fixtures under `forecaster/tests/fixtures/`; `tests/fixtures/README.md` documents hand-edited
derivatives, per the house convention. The robots/UA/timeout posture to copy is
`tools/feeds.py`'s.
**Task:** **First, capture live** (network is sanctioned outside the suite):
`capture_fixture.py --raw zach_shows.html "https://www.zachtheater.org/tickets/shows/"
--user-agent "forecaster/0.1 (sarah.rachel.hernandez@gmail.com)"` and
`--raw robots_zach.txt "https://www.zachtheater.org/robots.txt"`. Then derive two hand-edited
fixtures and note them in the fixtures README: `zach_shows_empty.html` (production cards removed,
page landmarks intact) and `zach_shows_redesigned.html` (landmarks stripped). Build the parser:
`fetch_listings(url, *, client, user_agent, timeout, trace)` → robots check (unreachable robots
= disallow, per the Step 26 rule) → fetch (no cross-host redirects) → `parse_listings(html)` →
typed `Production(title, start_date, end_date, url, raw_dates)` records. Choose the landmark from
the real capture (the production-card container the 2026-08-14 probe saw headings inside);
**parsed-empty** = landmark present, zero cards; **unparseable** = landmark absent → raise
`VenueParseError`. Date ranges: parse the page's informal text ("through Aug 23",
"Nov 18 – Dec 27") into dates where unambiguous, inferring the year from adjacency (a range
ending before it starts crossed a year boundary); when the text resists parsing, keep
`raw_dates` verbatim with `start_date = end_date = None` — **never guess a date**.
**Verify:** `uv run pytest -q` green. Over the real fixture: the productions visible on the
captured page come back with correct titles, absolute URLs, and parsed ranges (assert a handful
by name against what the capture actually contains — read it, don't assume). The empty fixture →
`[]` with no error; the redesigned fixture → `VenueParseError`; a fixture `robots.txt`
disallowing the path → skipped with a trace record; a test asserts the outgoing `User-Agent`;
an unparseable date-range string keeps `raw_dates` and `None` dates.
**Guardrails:** Stdlib parsing in the house style of `feeds.extract_body` — no BeautifulSoup, no
new dependency. No windowing here (the beat owns the window); the parser returns everything it
sees.

### Step 42 — `VenueListingsBeat`: window, items, quiet vs broken  (implements FR-43, FR-45)
**Context:** [`PRD.md`](PRD.md) FR-43/FR-45. New `forecaster/forecaster/beats/venues.py`;
`beats/base.py::load_builtin_beats` gains the import; `config.toml` flips `venues = true`;
`tests/test_beat_venues.py`; `test_time_scoped_items.py` gains the venues case (COVERED_BEATS +
a fixture-driven test — its items all carry dates, so the standard date-rule parametrize shape
fits, unlike need_to_know's). Structure model: `beats/need_to_know.py` (per-source loop, FR-28
pattern), minus corpus/embedder — this beat needs **neither**, nor an `agent_client`.
**Task:** One class, `name = "venues"`, `kind`-keyed parser dispatch (`{"zach_shows":
venues.fetch_listings}`); a venue with an unknown `kind` is treated as a failed venue (named
decision + dated status line), not a crash. Per venue: one `tool_call`/`observation` pair around
the fetch+parse (payload: the production records), then in code: filter to productions whose run
intersects `[now, now + window_days]` — a production with unparsed dates is **included** with its
`raw_dates` text (a listing with "dates: see site" is honest; dropping it silently is not).
Emit one item per in-window production: text like `At ZACH through Aug 23: "Sally & Tom" —
<url>` assembled in code; `checkable_fields` per item are impossible (they're beat-level) — so
declare the beat's `checkable_fields` as a flat mapping of per-item keys
(`{"venues:0:title": ..., "venues:0:end_date": ...}`) exactly as the Astros beat handles
multi-game nights (read `beats/astros.py` first and copy its convention rather than inventing
one). Item `fields`: `venue`, `title`, `start_date`/`end_date` (or `raw_dates`), and `as_of`.
Genuinely-empty parse → one quiet status line per venue ("Nothing on the calendar at ZACH in the
next 14 days.") with `as_of`. Fetch/parse failure → FR-28: `venue_unavailable` decision + dated
"couldn't read ZACH's calendar tonight" line. Every venue failing → FR-18 `unavailable`.
**Verify:** `uv run pytest -q` green, and specifically: the FR-2 seam test passes with the beat
enabled; over the real fixture with a `now` that makes some productions in-window and others not,
exactly the intersecting ones appear; a production with `raw_dates` appears carrying the verbatim
text; the empty fixture yields the quiet line and `available=True`; the redesigned fixture yields
the unavailable line naming ZACH; unknown `kind` yields a named failed venue; every item passes
the FR-11 provenance check against the parse observation; the beat never touches
`context.agent_client`/`embedder`/`corpus` (exploding client + `None`s in every test); and
`git diff` over `planner.py`, `synthesizer.py`, `delivery/` is empty **at this step**.
**Guardrails:** Zero edits to `synthesizer.py` here — with the exemption not yet built, venue
items flow through normal dedup in any pipeline-level test; that is expected until Step 43. No
taste, no ranking, no truncation of the listing count.

### Step 43 — Dedup opt-out: `exempt_beats`, explicit and accounted  (implements FR-44)
**Context:** [`PRD.md`](PRD.md) FR-44. `forecaster/forecaster/synthesizer.py` (the FR-9b dedup
pass — find where `assess_item`/the retriever is consulted per item and where FR-37's same-run
neighbours are gathered), `forecaster/tests/test_dedup_exemption.py` (new),
existing synthesizer/dedup suites. **Read the pass before editing**: the exemption must sit
*before* retrieval, so an exempt item costs zero embedder and zero model work.
**Task:** In the dedup pass: an item whose beat is in `config.retrieval.exempt_beats` skips
retrieval, same-run neighbours, and judgment entirely; it is included verbatim with a
`dedup_exempt` decision (`beat`, reason "beat opts out by config; repeats are deliberate").
Exempt items also do not join FR-37's kept-items pool (nothing should ever defer to or reframe
against a listing). Ledger writes are unchanged — exempt items are still recorded as delivered.
**Verify:** `uv run pytest -q` green. New tests: a venue item byte-identical to a ledger row from
last night is delivered unchanged with a `dedup_exempt` decision, the model never consulted and
the retriever never queried (call-count asserts on both); the same setup with
`exempt_beats = []` reaches the normal path; a non-exempt beat's near-duplicate still
suppresses (the existing suites prove this — they must pass untouched); an exempt item never
appears as a same-run neighbour for another item.
**Guardrails:** This is the only step that touches `synthesizer.py`, and only the dedup pass.
Do not weaken any FR-19 invariant, any veto, or any test — the exemption is a bypass *around*
the machinery, not a change *to* it.

### Step 44 — Venues metric checker + CLI  (implements FR-46)
**Context:** [`PRD.md`](PRD.md) FR-46 and §2. New `forecaster/forecaster/venues_metric.py` in
the `ntk_metric.py` shape (reuse `Condition`); `forecaster/cli.py` gains `--venues-metric`;
`forecaster/tests/test_venues_metric.py`.
**Task:** Three conditions over trace files: **(a) listing provenance** — reuse the final
provenance verdict for delivered runs, scoped as `news_metric` condition (a) is; **(b) never
suppressed** — zero `dedup_suppress`/`dedup_reframe` decisions whose item belonged to the
venues beat, and every delivered venue item on a run where dedup ran has a `dedup_exempt`
record; a single suppression fails; **(c) quiet is explicit** — every run where the beat is
available carries ≥1 venue listing item, or per-venue quiet lines, or `venue_unavailable`
decisions; no unaccounted third state. Report n/a when the beat appears in no run (the
n/a-not-pass posture).
**Verify:** `uv run pytest -q` green. The checker passes a fixture trace satisfying all three;
returns the specific failing condition for a trace violating each one — including a synthetic
`dedup_suppress` on a venue item for (b); reports n/a for a beat-absent trace; and
`uv run python -m forecaster.cli --venues-metric` runs cleanly against the real `data/runs/`
(expected: n/a — the beat has never run live).
**Guardrails:** Report-only. Don't refactor the sibling metric modules beyond importing
`Condition`.

---

## Withheld pending §9 — none

The PRD's §9 has no blocking open questions: Sarah answered the two that shaped the spec
(no dedup; ZACH-only v1), and the only `[Later]` item (FR-47, Bass) is gated on an account, not
a design decision. Nothing here touches the Q5/Q6/Q7 threshold family.

## Explicitly out of this build

FR-47 (Bass via Ticketmaster) — no stub, no `TICKETMASTER_API_KEY` reference, no dormant code
path. When the account exists, it lands as its own increment: a new `kind`, a fixture, and a
config entry, exactly what the parser registry is for.

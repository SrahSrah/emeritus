# PRD: Venue listings beat — what's playing, repeated on purpose

**Project:** emeritus (capstone) · **Status:** Draft · **Feature ID:** `venue-listings` · **Target path:** `forecaster/forecaster/beats/venues.py`, `forecaster/forecaster/tools/venues.py`

> Child of [`docs/prd/forecaster/PRD.md`](../forecaster/PRD.md). Taken FR numbers: 1–19 (parent),
> 20–30 and 37 (ai-news), 31–36 and 38–41 (need-to-know). This spec owns **FR-42 … FR-47**. The
> parent's FR-17 is amended to point here for the live-music/theatre beat specifically.

## 1. Problem & why now

Checkpoint 1 promised *"upcoming local live music or theatre shows I might be interested in."*
Sarah re-scoped it on 2026-08-16, and the re-scope is the design: **not discovery — named
venues.** "I don't wanna know live music. I want to know what's playing in the next two weeks at
the Bass Concert Hall and the ZACH Theatre." That kills the hardest parts of the promised beat
(taste, ranking, coverage of an open-ended scene) and leaves a **structured listings beat**:
titles and dates from known calendars, filtered to a 14-day window, assembled in code. This is
Astros-shaped, not news-shaped — no corpus, no chunking, no retrieval, and **zero model calls**.

Sarah also set a second requirement that inverts this project's usual posture (2026-08-16, in her
words): *"i don't need/want dedupe for that. it can tell me the same thing multiple days in a row
while i decide if i want to see it."* Repetition is the feature — a listing is a standing offer,
not news — so this beat opts out of the FR-9b pass entirely (FR-44), rather than riding FR-19's
date rule, which would still permit reframes of a line she wants repeated verbatim.

**Why v1 is ZACH-only.** Measured 2026-08-14 with the repo's identifying client:
ZACH's listings page is server-rendered HTML, 200 keyless, robots with no Disallow. Bass Concert
Hall has no honest keyless path — texasperformingarts.org and broadwayinaustin.com both WAF-403
every request including robots.txt, and the credible alternative (Ticketmaster Discovery API,
free tier, 5,000 calls/day verified 2026-08-14) requires a developer account **Sarah tried and
failed to create on 2026-08-16** (signup rejected; cause unknown). Bass is therefore FR-47
`[Later]`, gated on that account existing — not forgotten, and not worth blocking ZACH for.

## 2. Goal & success metric

- **Goal:** Every night, the digest lists what is playing at each configured venue in the next
  `window_days`, repeated nightly for as long as it remains true, with every title and date traced
  to that run's fetch — and a night with nothing scheduled says so explicitly, distinguishably
  from a broken parser.

- **Success metric.** Three conditions, computable from `data/runs/*.jsonl` alone. Parent §2(a)
  holds unchanged.
  - **(a) Listing provenance.** Every delivered listing's title and dates appear in
    `checkable_fields` and match the parse observation they came from — enforced by the existing
    FR-11 check, zero violations.
  - **(b) Never suppressed.** **Zero** `dedup_suppress` or `dedup_reframe` decisions for this
    beat, ever; every one of its items reaches the digest each night with an explicit
    `dedup_exempt` record (FR-44). A single suppression fails the metric — this is Sarah's
    no-dedup requirement made machine-checkable.
  - **(c) Quiet is explicit.** Every run where the beat is available produces either ≥1 listing
    item or exactly one "nothing in the window" line; a parse failure produces the FR-18
    unavailable shape. No third state exists.

Deliberately not a metric: whether the shows are any good. Taste stays out of this beat entirely
— that is what the re-scope bought.

## 3. Users & job-to-be-done

One user: Sarah. The job: "keep the current fortnight's options at my venues in front of me until
I act or they close." Repetition is not a defect of that job — it is the job.

## 4. Scope

**In scope (v1):**

- One venue-parser tool for ZACH's listings page (keyless fetch, identifying UA, robots-checked),
  returning typed productions: title, date range, event URL.
- One `Beat` implementation plus one config entry (`[beats] venues`, `[venues]` section with a
  venue list and `window_days = 14`). Zero edits to `planner.py`, `synthesizer.py`, `delivery/`
  for the beat itself.
- Item text assembled in code, with title and dates as `checkable_fields`, event URL included
  (Checkpoint 1: "rife with links").
- A per-beat dedup exemption (FR-44) — the one edit that touches shared dedup machinery, same
  sanctioned category as FR-9b/FR-37 changes.
- Parsed-empty vs unparseable distinguished structurally (FR-45), and per-venue failure handling
  in the FR-28 pattern.
- A small metric checker (FR-46).

**Out of scope / non-goals:**

- **Bass Concert Hall** until the Ticketmaster account exists (FR-47 `[Later]`).
- **Any model call.** Nothing here needs phrasing judgment; a listing is a template over typed
  fields.
- **Discovery, recommendations, taste, or any venue not named in config.** The re-scope is the
  spec; scope creep back toward "live music in Austin" is the failure mode this section exists to
  block.
- **Spoofing around the TPA/Broadway WAF.** The fetcher identifies itself everywhere; that
  posture is part of the capstone's argument and is not negotiable for a nicer calendar.
- **Ticket prices, availability, seat maps** — the link carries all of that.

## 5. Functional requirements

- **FR-42 — ZACH listings parser** `[MVP]`
  - **Requirement:** A tool in `tools/venues.py` that fetches
    `https://www.zachtheater.org/tickets/shows/` (**note the domain: `zachtheater.org`, one
    "t"** — `zachtheatre.org` redirects through a ticketing session bounce) with the configured
    identifying `User-Agent`, robots-checked and timeout-bounded per the FR-21 posture, and
    parses it into typed `Production` records: `title`, `start_date`, `end_date` (parsed from the
    page's date-range text), `url`. The parser must distinguish three outcomes structurally:
    **parsed with productions**, **parsed and genuinely empty** (page landmarks recognized, zero
    production cards), and **unparseable** (landmarks missing — a redesign), which raises. A
    date range it cannot parse keeps the production with the raw date text carried verbatim and
    flagged, never a guessed date.
  - **Acceptance:** Done when, over a real captured fixture of the live page, the parser returns
    the productions visible on it with correct titles, URLs, and parsed date ranges; a fixture
    with the production cards removed but landmarks intact returns parsed-empty; a fixture with
    the landmarks stripped raises; and a test asserts the outgoing `User-Agent` and the robots
    check. Fixture captured in the same change, per the repo rule.
  - **Touches:** `forecaster/tools/venues.py`, `tests/fixtures/zach_shows.html`,
    `tests/fixtures/robots_zach.txt`

- **FR-43 — Venue listings beat worker** `[MVP]`
  - **Requirement:** One `Beat` implementation, `VenueListingsBeat` (`name = "venues"`),
    registered by `[beats] venues = true` plus a `[venues]` section: `user_agent`,
    `timeout_seconds`, `window_days = 14`, and a `venues` list of `{name, kind, url}` entries
    where v1 supports `kind = "zach_shows"` (the parser registry is keyed by `kind`, so FR-47
    adds Bass as a new kind, not a new beat). For each configured venue it fetches, parses, and
    emits **one item per production whose run intersects the next `window_days`** — text
    assembled in code ("At ZACH through Aug 23: *Sally & Tom* — <url>"), `checkable_fields`
    carrying title and dates, and `fields` carrying the venue, the production dates, and `as_of`.
    No `agent_client`, ever.
  - **Acceptance:** Done when the FR-2 seam test passes with the beat registered and enabled; a
    fixture run emits exactly the productions intersecting the window (one in-window, one
    starting beyond it, one already closed — only the first appears); every item's title and
    dates pass the FR-11 provenance check against the parse observation; and disabling
    `[beats] venues` returns the digest to its prior shape.
  - **Touches:** `forecaster/beats/venues.py`, `config.toml`, `forecaster/config.py`

- **FR-44 — Dedup opt-out, explicit and accounted** `[MVP]`
  - **Requirement:** `[retrieval]` gains `exempt_beats` (default `[]`; ships as `["venues"]`).
    For an item from an exempt beat, the synthesizer's dedup pass performs **no retrieval and no
    judgment** — the item is included verbatim with a `dedup_exempt` decision recording the beat
    and the reason ("beat opts out by config; repeats are deliberate"). The exemption is
    config-owned, not beat-declared, so turning dedup back on for this beat is a one-line config
    edit and no code change. Every FR-19 invariant is untouched for every other beat.
  - **Acceptance:** Done when a venue item identical to last night's ledger row is delivered
    unchanged with a `dedup_exempt` decision and **zero** model calls; the same fixture with
    `exempt_beats = []` reaches the normal dedup path; and the whole existing dedup suite passes
    unchanged.
  - **Touches:** `forecaster/synthesizer.py` (the dedup pass — sanctioned dedup-machinery
    change, as FR-9b and FR-37 were, not a beat-seam change), `forecaster/config.py`
  - **Why config-owned:** Sarah's requirement is about *this beat today*, not a property of
    listings forever. A `dedup = false` flag buried in a beat class would outlive the preference
    invisibly; a config list is visible every time she opens the file.

- **FR-45 — Quiet night vs broken parser** `[MVP]`
  - **Requirement:** A venue whose parse is **genuinely empty** for the window yields one
    code-assembled status line ("Nothing on the calendar at ZACH in the next 14 days."),
    date-fielded with `as_of`. A venue whose fetch fails or whose parser raises takes the FR-28
    path: a `venue_unavailable` decision plus a dated "couldn't read ZACH's calendar tonight"
    line, and every configured venue failing is the FR-18 unavailable shape. The two must never
    collapse: quiet is a parsed fact, broken is a named failure.
  - **Acceptance:** Done when the parsed-empty fixture yields the quiet line and no error; the
    landmark-stripped fixture yields the unavailable line naming ZACH and no listing; and both
    lines carry `as_of` so FR-19's date rule governs them (they are status items, not exempt
    listings — the exemption in FR-44 covers the beat's listing items; status lines follow the
    house pattern).
  - **Touches:** `forecaster/beats/venues.py`
  - **Note:** status lines from an *exempt* beat still bypass dedup wholesale under FR-44's
    mechanism. That is acceptable — a repeated "nothing at ZACH" line is exactly what Sarah said
    she wants nightly truth about — and simpler than splitting item classes within one beat.

- **FR-46 — Venue metric checker** `[MVP]`
  - **Requirement:** §2's three conditions over trace files, in the `ntk_metric.py` shape, plus a
    CLI flag (`--venues-metric`). Condition (b) — never suppressed — is the one this beat adds to
    the project: it is the inverse of every other beat's dedup expectations, and it is what makes
    the no-dedup promise auditable rather than vibes.
  - **Acceptance:** Done when the checker passes a fixture trace satisfying all three, returns
    the specific failing condition for a trace violating each one (including a synthetic
    `dedup_suppress` on a venue item), and reports n/a when the beat appears in no run.
  - **Touches:** `forecaster/venues_metric.py`, `forecaster/cli.py`

- **FR-47 — Bass Concert Hall via Ticketmaster Discovery** `[Later]` — **gated on the TM developer account**
  - **What it needs:** the account Sarah could not create on 2026-08-16 (signup rejected —
    retry later or via TM support; HUMAN-TODO holds the step-by-step). When it exists:
    `TICKETMASTER_API_KEY` in the gitignored `.env` (placeholder in `.env.example`, no secret in
    any diff), a `kind = "ticketmaster"` parser hitting the Discovery `events` endpoint scoped to
    the Bass venue id for the window, and the same item shape as FR-43. Free tier verified
    2026-08-14: 5,000 calls/day against our ~1/night. **This is the project's first keyed
    dependency** — free but not keyless — approved by Sarah 2026-08-16 conditional on the free
    tier, and it must be named as an exception wherever a checkpoint leans on "keyless."
  - **Not buildable until the key exists. Do not stub it.**

## 6. Technical & data notes

- **Measurements (2026-08-14, repo `httpx` client, identifying UA):** ZACH
  `tickets/shows/` → 200, 68,639 bytes, server-rendered (titles and date strings present in
  HTML; **no JSON-LD**, so parsing is positional HTML, hence FR-42's landmark discipline). ZACH
  robots: no Disallow (content-signal comments only). TPA and Broadway in Austin: 403 on every
  path including robots.txt. Ticketmaster free tier: 5,000 calls/day, verified against
  developer.ticketmaster.com. TM signup: **failed 2026-08-16**.
- **Domain gotcha:** the working host is `www.zachtheater.org`; the intuitive spelling
  (`zachtheatre.org`) bounces through a `tickets.zachtheater.org` shared-session redirect that
  broke both probe paths. Config ships the working host; the parser follows no cross-host
  redirects.
- **No new dependencies.** Fetch is `httpx`, parsing is the stdlib posture the FR-21 extractor
  already established. No model calls, no embedder, no corpus involvement — the beat never
  touches `BeatContext.embedder`, `corpus`, or `agent_client`.
- **Config sketch:** `[beats] venues = true`; `[venues]` with `user_agent`, `timeout_seconds`,
  `window_days = 14`, `venues = [{name = "ZACH Theatre", kind = "zach_shows", url = ...}]`;
  `[retrieval] exempt_beats = ["venues"]`.
- **Testing:** captured real fixture of the live page plus two derived fixtures (cards removed;
  landmarks stripped) — derived fixtures are hand-edited and say so in `tests/fixtures/README.md`
  per the house convention. Socket guard stays on.

## 7. Dependencies

- None new for v1. FR-47 depends on the Ticketmaster developer account (HUMAN-TODO).

## 8. Risks & edge cases

- **A site redesign is this beat's outage.** Positional HTML parsing breaks silently on
  redesign; FR-42's landmark check turns that into a loud FR-18 failure instead of a quietly
  empty calendar. The metric's condition (c) is the nightly watch on it.
- **Date-range text is informal** ("through Aug 23", "Nov 18 – Dec 27", season labels). The
  parser keeps unparseable date text verbatim and flagged rather than guessing — a listing with
  "dates: see site" is honest; an invented date is FR-18's cardinal sin wearing a calendar.
- **Season boundaries:** a page listing next season's productions months out is normal; the
  window filter, not the parser, decides what tonight's digest shows.
- **The exemption could hide a real bug**: with dedup off, a parser that emits duplicate items
  for one production would repeat within a single digest. FR-43's acceptance asserts one item
  per production per night.
- **ZACH's robots content-signals** are policy comments, not Disallow rules; the fetch is
  compliant today. If ZACH ever adds a Disallow covering the listings path, the beat degrades to
  unavailable — same rule as every other source, no exceptions for being useful.

## 9. Open questions

None blocking v1 — the two that shaped this spec were answered by Sarah on 2026-08-16 (no dedup;
ZACH-only v1) and the thresholds here are calendar windows, not similarity floors, so nothing
joins the Q5/Q6/Q7 unmeasured family.

1. **The Ticketmaster account.** Why signup failed is unknown (browser? VPN? capacity?). Retry
   later, or via TM developer support. FR-47 waits; nothing else does.
2. **More venues later?** The `kind`-keyed parser registry means a third venue is a config entry
   plus possibly a parser. Deliberately not designed further until a real venue is named.

## 10. Phasing

- **v1: FR-42 … FR-46.** ZACH end to end, no-dedup honored and audited, quiet-vs-broken
  distinguishable in the inbox and the trace.
- **Later: FR-47** (Bass via Ticketmaster), unblocked only by the account existing.

## 12. Changelog

- **v1 — 2026-08-16:** Initial PRD, from Sarah's re-scope (named venues, not discovery; no
  dedup, repeats deliberate) and the 2026-08-14 measurements. ZACH-only v1 after the Ticketmaster
  signup failed 2026-08-16; Bass recorded as FR-47 `[Later]` with the free-tier verification and
  the keyed-dependency exception noted.

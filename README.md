# Emeritus — the Forecaster

> The Forecaster — an autonomous nightly digest agent — lives in [`forecaster/`](forecaster/),
> surrounded by the documents that specify, audit, and track it: the PRDs, the divergence
> ledger, and the build ledgers. It runs nightly, for real.

## Program

- **Provider:** Emeritus
- **Program:** Agentic AI Program: Building Autonomous Systems for Real-World Applications
- **Format:** self-paced, weekly written checkpoints, final report + recorded presentation

## The Forecaster

A nightly digest, emailed at 7 pm CT, covering the things that disappeared when social media
did. The argument the whole capstone makes: **every checkable fact traces back to a tool
call.** The model phrases the digest — it never originates a score or a temperature. When a
source is unreachable, the digest names the outage rather than filling the gap.

| Beat | Source | Status |
|---|---|---|
| Astros game state | `statsapi.mlb.com` (free, no key) | live |
| Next-morning Austin weather | `api.weather.gov` (free, needs a `User-Agent`) | live |
| AI news | RSS discovery + article fetch, grounded prose | live |
| Need-to-know news | BBC / NPR / Al Jazeera / Texas Tribune RSS, corroboration-gated | live |
| Local theatre listings | the venue's own calendar page | live |
| r/WallStreetBets mention counts | Reddit RSS, counted in code | live |

**The newest beat is the thesis at its purest.** Checkpoint 1 promised "stock market
picks" from r/WallStreetBets; that framing died on the record. What shipped counts ticker
mentions on the night's hot page — in code, zero model calls, one polite fetch per night
(a metric fails any trace with two) — and a test reconstructs the delivered line
character-for-character from the counted values, so no code path can append commentary
unnoticed. The digest reports attention, never advice: no prices, no "up/down," no picks.

**Architecture, in one paragraph.** A planner reads the date and a preference file and decides
which beats run; six per-beat workers each run their own ReAct loop against their own tools
and return typed items carrying provenance; a synthesizer retrieves each candidate line's
nearest neighbours from a ledger of everything already sent (local embeddings, sqlite-vec),
applies deterministic escalation rules, and composes the email. After composition, a
provenance check recomputes every checkable value in the digest against the tool observations
in that run's trace and quarantines anything it cannot ground. Workers never talk to each
other; shared awareness routes through the synthesizer.

Every run writes a JSONL trace to `forecaster/data/runs/` (gitignored): each tool call, each
observation, each dedup and escalation decision, and the delivery outcome. The per-beat
evaluation metrics are computed from those traces by CLI commands (`--news-metric`,
`--ntk-metric`, `--venues-metric`, `--wsb-metric`) that report honestly — "3 of 14 nights"
stays 3 of 14.

A sample of real output, from the first delivered digest (2026-08-24):

> 3\. Story count: 58 (down from 59). Nothing cleared the need-to-know bar tonight; max
> corroboration 2.
> 4\. ZACH Theatre: nothing on the calendar in the next 14 days.
>
> No unavailable items tonight.

Quiet is reported as quiet, with the evidence tallied — a quiet night and a broken beat are
never allowed to look alike.

## Reviewing the project

Start here:

- [`docs/prd/forecaster/PRD.md`](docs/prd/forecaster/PRD.md) — the spec of record: numbered
  functional requirements, each with acceptance criteria, plus §9's deliberately open
  questions. Each later beat has its own PRD under [`docs/prd/`](docs/prd/).
- [`docs/DIVERGENCES.md`](docs/DIVERGENCES.md) — every place a submitted checkpoint and the
  shipped code disagreed, and how each was resolved. The design-evolution story, as a ledger.
- [`forecaster/`](forecaster/) — source, tests, config, and the nightly scheduler script.

The submitted checkpoint essays themselves are kept out of the repository on purpose; the
divergence ledger above records what they promised wherever it differs from what shipped.

## Running it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/). The test suite needs **no network,
no credentials, and no model account** — recorded HTTP fixtures, a socket guard, and a fake
agent client:

```bash
cd forecaster
uv run pytest -q
```

A real run needs a gitignored `.env` (copy [`forecaster/.env.example`](forecaster/.env.example)
and fill it in):

- `CLAUDE_CODE_OAUTH_TOKEN` — a Claude subscription OAuth token (`claude setup-token`).
  **Auth is subscription OAuth, never an API key.** The pipeline refuses to start if
  `ANTHROPIC_API_KEY` is set, because that would silently bill per-token.
- `CONTACT_EMAIL` — **your email address.** The tracked `config.toml` deliberately contains
  the placeholder token `${CONTACT_EMAIL}` instead of a real address; it is expanded from the
  environment at load time and lands in outbound `User-Agent` headers (`api.weather.gov`
  rejects requests without one) and the fake deliverer's label. Set it so the contact string
  points at someone reachable: you.
- `SMTP_*` — only for real email delivery (`--send-test`); a dry run needs none of it.

```bash
uv run python -m forecaster.cli --dry-run
```

prints the digest and writes a trace without sending anything. The nightly schedule is a
Windows Task Scheduler job wrapping [`forecaster/scripts/run_nightly.ps1`](forecaster/scripts/run_nightly.ps1).

## Layout

```
.
├── docs/prd/                 one folder per increment: PRD, build prompts, build ledger
├── docs/DIVERGENCES.md       submitted-vs-shipped ledger
└── forecaster/               the agent: source, tests, config, scheduler script
```

## How I work in here

- **Notes are mine, not the slides'** — capture what actually landed, in my own words.
- **Assignments get drafted here first**, then submitted through the portal by me.
- Trackers stay live: [STATUS.md](STATUS.md) for where things stand,
  [HUMAN-TODO.md](HUMAN-TODO.md) for what only I can do, and
  [FEATURES-TODO.md](FEATURES-TODO.md) for build work.

---

_Graduated from the playground monorepo on 2026-07-27._

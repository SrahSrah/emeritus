# Emeritus

> Working through an online AI program — and building the capstone it's for.

Coursework plus the agent it produces. A short written checkpoint is due roughly weekly; the
capstone those checkpoints describe is the **Forecaster**, which lives in `forecaster/` and
actually runs.

## Program

_Fill in once confirmed — nothing here is assumed._

- **Provider:** Emeritus
- **Program:**
- **Institution / partner:**
- **Cohort start:**
- **Expected end:**
- **Format:** (self-paced / live sessions / cohort)
- **Portal:**

## The Forecaster

A nightly digest, emailed around 7 pm CT, covering the things that disappeared when social media
did. v1 runs two beats:

| Beat | Source | Free? |
|---|---|---|
| Astros game state | `statsapi.mlb.com` | yes, no key |
| Next-morning Austin weather | `api.weather.gov` | yes, no key (needs a `User-Agent`) |

A planner sits above per-beat ReAct workers; a synthesizer applies escalation rules and composes
the message. The argument the whole capstone makes: **every checkable fact traces back to a tool
call.** The model phrases the digest — it never invents a score or a temperature. When a source is
unreachable, the digest says so rather than filling the gap.

Four more beats (AI news, r/WallStreetBets, need-to-know news, live music) are specified and
deferred — see [FEATURES-TODO.md](FEATURES-TODO.md).

## Layout

```
.
├── assignments/              submitted checkpoint text
├── modules/                  per-module notes
├── writing/                  longer pieces the program prompts
├── docs/prd/forecaster/      PRD (spec of record), build prompts, build ledger
└── forecaster/               the agent: source, tests, config, scheduler script
```

## Running it

Requires Python 3.12 and [uv](https://docs.astral.sh/uv/).

```bash
cd forecaster
uv run pytest -q
```

The suite makes no network call and no model call — recorded fixtures, a socket guard, and a fake
agent client. A real run additionally needs `CLAUDE_CODE_OAUTH_TOKEN` in a gitignored `.env`; see
[HUMAN-TODO.md](HUMAN-TODO.md).

**Auth is subscription OAuth, never an API key.** The pipeline refuses to start if
`ANTHROPIC_API_KEY` is set, because that would silently bill per-token instead of drawing on the
Claude subscription.

## How I work in here

- **Notes are mine, not the slides'** — capture what actually landed, in my own words.
- **Assignments get drafted here first**, then submitted through the portal by me.
- Trackers stay live: [STATUS.md](STATUS.md) for where things stand,
  [HUMAN-TODO.md](HUMAN-TODO.md) for what only I can do, and
  [FEATURES-TODO.md](FEATURES-TODO.md) for build work.

---

_Graduated from the playground monorepo on 2026-07-27._

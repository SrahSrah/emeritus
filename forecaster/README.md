# Forecaster

A nightly digest that tells Sarah what she needs to know, where **every checkable fact came from a
tool call** rather than from a language model's memory. Emeritus capstone build.

Spec: [`../docs/prd/forecaster/PRD.md`](../docs/prd/forecaster/PRD.md) ·
Build steps: [`../docs/prd/forecaster/BUILD-PROMPTS.md`](../docs/prd/forecaster/BUILD-PROMPTS.md)

## Install

Python 3.12, managed by [`uv`](https://docs.astral.sh/uv/).

```powershell
cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
uv sync
```

## Auth — read this before running anything

The agent layer authenticates against Sarah's Claude subscription with
`CLAUDE_CODE_OAUTH_TOKEN`. **`ANTHROPIC_API_KEY` must be unset** in any environment that runs the
pipeline: if it is set it shadows the OAuth token and silently bills per-token. The code refuses to
start rather than let that happen.

```powershell
Copy-Item .env.example .env       # then fill it in — .env is gitignored
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
```

## Tests

The suite runs entirely off recorded HTTP fixtures. A socket guard fails any test that reaches for
the network, and no test ever calls the model.

```powershell
uv run pytest -q
```

## Run

```powershell
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
uv run python -m forecaster.cli --dry-run
```

`--dry-run` uses the fake deliverer (nothing is sent) but a **real** agent client and the two live
APIs, so it draws down subscription usage.

**This needs `CLAUDE_CODE_OAUTH_TOKEN` in `.env` first.** Without it the run exits 2 with
`refusing to start: CLAUDE_CODE_OAUTH_TOKEN is missing or empty` — by design, since the only other
way to authenticate would be the per-token API key.

Flags: `--config PATH`, `--preferences PATH`, `--dry-run`, `--send-test`.

### Send one real digest — Sarah runs this, not an agent

```powershell
cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
uv run python -m forecaster.cli --send-test
```

### Nightly, unattended

The job script strips `ANTHROPIC_API_KEY`, loads `.env`, logs to the gitignored `data/`, and exits
non-zero on failure so Task Scheduler records it.

```powershell
# Dry run on demand — writes a trace, sends nothing
.\scripts\run_nightly.ps1 -DryRun
```

**Registering the scheduled task is Sarah's to run** (it changes system settings):

```powershell
schtasks /Create /TN "Forecaster Nightly" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\Sarah\Documents\28_playground\emeritus\forecaster\scripts\run_nightly.ps1" /SC DAILY /ST 19:00 /RL LIMITED
```

7 pm local; the machine is on CT. PRD §7: a sleeping laptop means no run — the script records
intended-but-missed slots so the delivery metric stays honest.

After three nights, check that all three ran on subscription auth:

```powershell
Get-ChildItem data\runs\*.jsonl | Select-Object -Last 3 | ForEach-Object {
  (Get-Content $_ -TotalCount 1 | ConvertFrom-Json).auth_mode
}
```

## Layout

```
forecaster/            the package
  config.py            config.toml loader (FR-1)
  planner.py           which beats run tonight, and what "done" means (FR-7)
  beats/base.py        the Beat protocol + registry (FR-2)
  beats/astros.py      Astros game-state worker (FR-5)
  beats/weather.py     next-morning run-window forecast (FR-6)
  tools/mlb.py         statsapi.mlb.com adapter (FR-3)
  tools/weather.py     api.weather.gov adapter (FR-4)
  memory/scratchpad.py per-run short-term memory (FR-8)
  memory/preferences.py human-edited preference rules (FR-15)
  memory/ledger.py     sent-item ledger, write-only in v1 (FR-9)
  escalation.py        deterministic escalation rules (FR-10)
  synthesizer.py       composes the digest, enforces provenance (FR-11)
  delivery/            Deliverer protocol + SMTP implementation (FR-12)
  trace.py             per-run JSON-lines trace + provenance checker (FR-13)
  cli.py               the runner: plan -> beats -> synthesize -> deliver -> ledger
config.toml            all run parameters
preferences.toml       topic weights, watched players, suppressions
data/                  traces + ledger — gitignored, never committed
scripts/               fixture capture, nightly job script
tests/fixtures/        recorded HTTP payloads (see fixtures/README.md for provenance)
```

## External services

Both are free and keyless. Neither needs a signup.

- `statsapi.mlb.com` — undocumented public endpoint; may change shape without notice.
- `api.weather.gov` — **rejects requests without a `User-Agent`** with a 403 that looks like an
  outage.

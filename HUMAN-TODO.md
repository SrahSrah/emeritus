# HUMAN-TODO — emeritus

Only the things **Sarah** has to do herself — logging in, submitting, attending,
paying, emailing a human. Everything else belongs in STATUS.md.

Status: `[ ]` open · `[~]` in progress · `[x]` done

## Now

- [x] **Submit Assignment 2.** Done 2026-07-27.

### Before the Forecaster build can run

The code is built and its test suite is green (221 tests, no network, no model calls).
Four things below are **blocking a first real run** — everything else is done.

- [ ] **① Mint a Claude Code OAuth token** and put it in `emeritus/forecaster/.env` as
      `CLAUDE_CODE_OAUTH_TOKEN`. Only you can do this — it's an account action.
      ```powershell
      claude setup-token
      cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
      Copy-Item .env.example .env      # then paste the token in. .env is gitignored.
      ```
      **This is the single blocker on the whole build.** Every run currently stops with
      `refusing to start: CLAUDE_CODE_OAUTH_TOKEN is missing or empty` — by design, since
      the only other way to authenticate would be the per-token API key.

- [x] **Check whether `ANTHROPIC_API_KEY` is set anywhere in your environment.**
      Checked 2026-07-27: **not set** in the current user environment. The code no longer
      depends on that staying true — `assert_subscription_auth()` refuses to start if it
      ever is, and `scripts\run_nightly.ps1` strips it before anything else (verified: with
      the key deliberately set, the script logged `ANTHROPIC_API_KEY present: False`).

- [ ] **② Do the first end-to-end run** once ① is done. Uses the fake deliverer — nothing
      is sent — but a real agent client and the two live APIs.
      ```powershell
      cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
      Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
      uv run python -m forecaster.cli --dry-run
      ```
      It should print the digest and write a trace under `data\runs\`.

- [ ] **③ Create an SMTP app password** for the delivery account and add it to the same
      gitignored `.env` (`SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`,
      `SMTP_FROM`, `SMTP_TO`). Gmail requires an app password, not your login password.
      Then send one real digest — **this is FR-12's acceptance and it is yours to run; no
      agent will send it**:
      ```powershell
      cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
      Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
      uv run python -m forecaster.cli --send-test
      ```
      Confirm it arrived in the inbox.

- [ ] **④ Register the nightly scheduled task.** Changes system settings, so it is yours
      to run:
      ```powershell
      schtasks /Create /TN "Forecaster Nightly" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File C:\Users\Sarah\Documents\28_playground\emeritus\forecaster\scripts\run_nightly.ps1" /SC DAILY /ST 19:00 /RL LIMITED
      ```
      After **three consecutive nights** (FR-14's actual acceptance), check all three ran
      on subscription auth:
      ```powershell
      cd C:\Users\Sarah\Documents\28_playground\emeritus\forecaster
      Get-ChildItem data\runs\*.jsonl | Select-Object -Last 3 | ForEach-Object {
        (Get-Content $_ -TotalCount 1 | ConvertFrom-Json).auth_mode
      }
      ```
      Expect `subscription_oauth` three times. Then note the delivery metric in STATUS.md.
      A sleeping laptop at 7 pm produces no digest and no error — the runner records those
      slots as `missed_run` so the metric stays honest.

- [ ] **Decide the SMS-vs-email framing** for the next checkpoint (PRD §9 Q1) — your call
      whether to present email as a deliberate scope cut or restore SMS before submitting.

### Design decisions the build deliberately did not make

These are PRD §9 open questions. The build surfaced them rather than guessing; each one
gates real work.

- [ ] **Q3 — item identity for the ledger.** What makes two items "the same story": URL,
      entity+date, or a model judgment? The ledger is **write-only** until this is
      answered, and FR-9b (dedup / "what's new" framing) has no implementation.
- [ ] **Q2 — rules vs judgment for escalation.** Escalation is deterministic rules only.
- [ ] **The freeze horizon.** `freeze_horizon_days` is in config, but the weather adapter
      fetches only the next morning's window, so the rule can only apply over that. A
      multi-day "freeze within N days" alert needs a decision to extend the forecast range.
- [ ] **An injury data source.** FR-10 lists "injury to a watched player" as a v1 rule, but
      no v1 endpoint returns injuries. The rule is implemented and tested against a
      synthetic signal, and is **dormant**. Adding a feed is new scope.

## Setup

- [ ] Confirm the program name, partner institution, and cohort dates → fill the
      **Program** block in [README.md](README.md).
- [ ] Log into the Emeritus portal and pull down the syllabus / module list →
      drop it in `modules/` so STATUS.md's module table can be filled in.
- [ ] Note any hard deadlines (live sessions, assignment due dates) on the calendar.

## Deadlines

_None recorded yet._

| Due | What | State |
|---|---|---|
| — | — | — |

# HUMAN-TODO — emeritus

Only the things **Sarah** has to do herself — logging in, submitting, attending,
paying, emailing a human. Everything else belongs in STATUS.md.

Status: `[ ]` open · `[~]` in progress · `[x]` done

## Now

- [ ] **Paste Assignment 3 into the course Google Doc**, under `ASSIGNMENT 3: SUBMISSION:`.
      Drafted 2026-08-02 at
      [assignments/assignment-3-retrieval.md](assignments/assignment-3-retrieval.md) (886 words) —
      paste the essay body only, not the header block. ⚠️ **The Drive connector is read-only for
      existing docs**, so no agent can write into that doc; it can only create new files. This step
      is yours regardless of what `write-next-assignment` says it does.
- [ ] **Edit it in Docs until it sounds like you**, then submit through the Emeritus portal.
      Two claims in it are deliberately hedged and should stay hedged — the demonstration runs on a
      seeded ledger, and the retrieval thresholds are reasoned rather than measured. See
      DIVERGENCES rows 4 and 5.
- [ ] **Merge the FR-9b PR into `dev`** once you're happy with it. It is deliberately left
      unmerged — `feature/fr-9b-retrieval` → `dev`, 265 tests green.
- [x] **Submit Assignment 2.** Done 2026-07-27.
- [x] **Decide the SMS-vs-email framing** (PRD §9 Q1). Done 2026-08-02: deliberate scope cut,
      acknowledged in Checkpoint 3. DIVERGENCES row 1 closed.
- [x] **Answer PRD §9 Q3 — item identity for the ledger.** Done 2026-08-02: identity is a
      read-time relation between a candidate and what's already been sent, not a stored property.
      That unblocked FR-9b, which is now built.

### Before the Forecaster build can run

The code is built and its test suite is green (265 tests, no network, no model calls).
Four things below are **blocking a first real run** — everything else is done.

- [ ] **① Mint a Claude Code OAuth token** and put it in `forecaster/.env` as
      `CLAUDE_CODE_OAUTH_TOKEN`. Only you can do this — it's an account action.
      ```powershell
      claude setup-token
      cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
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
      cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
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
      cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
      Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
      uv run python -m forecaster.cli --send-test
      ```
      Confirm it arrived in the inbox.

- [ ] **④ Register the nightly scheduled task.** Changes system settings, so it is yours
      to run:
      ```powershell
      schtasks /Create /TN "Forecaster Nightly" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"C:\Users\Sarah\Documents\31 Emeritus\forecaster\scripts\run_nightly.ps1\"" /SC DAILY /ST 19:00 /RL LIMITED
      ```
      After **three consecutive nights** (FR-14's actual acceptance), check all three ran
      on subscription auth:
      ```powershell
      cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
      Get-ChildItem data\runs\*.jsonl | Select-Object -Last 3 | ForEach-Object {
        (Get-Content $_ -TotalCount 1 | ConvertFrom-Json).auth_mode
      }
      ```
      Expect `subscription_oauth` three times. Then note the delivery metric in STATUS.md.
      A sleeping laptop at 7 pm produces no digest and no error — the runner records those
      slots as `missed_run` so the metric stays honest.


### Design decisions the build deliberately did not make

These are PRD §9 open questions. The build surfaced them rather than guessing; each one
gates real work.

- [x] **Q3 — item identity for the ledger.** Answered 2026-08-02. FR-9b is built.
- [ ] **Q2 — rules vs judgment for escalation.** Escalation is still deterministic rules only.
      FR-9b settled the same tension for *dedup* by splitting it — retrieval narrows
      mechanically, the model judges, invariants bound the judgment. Whether that split should
      transfer to escalation is untested and yours to decide.
- [ ] **Q5 (new) — validate the retrieval thresholds.** `k = 5`, `similarity_floor = 0.60`,
      `window_days = 14` are reasoned, not measured. After a few weeks of real runs, read the
      traces and tune:
      ```powershell
      cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
      Get-ChildItem data\runs\*.jsonl | ForEach-Object { Get-Content $_ } |
        ConvertFrom-Json | Where-Object { $_.decision -like 'dedup_*' } |
        Select-Object decision, top_similarity, reason
      ```
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

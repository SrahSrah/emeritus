# HUMAN-TODO — emeritus

Only the things **Sarah** has to do herself — logging in, submitting, attending,
paying, emailing a human. Everything else belongs in STATUS.md.

Status: `[ ]` open · `[~]` in progress · `[x]` done

## Now

- [x] **Submit Assignment 3.** Done 2026-08-02. Submitted text logged verbatim at
      [assignments/assignment-3-retrieval.md](assignments/assignment-3-retrieval.md).
- [x] **Merge the AI news beat.** Done 2026-08-04 (PRs #2–#6). **442 tests green**, first green
      end-to-end run with all three beats.
- [ ] **Decide whether `--news-metric` should count runs that never delivered.** Condition (a)
      currently reads violations out of *every* trace, including the three runs that failed
      provenance and sent nothing. §2(a)'s own wording is about claims that "appear in any digest",
      and an undelivered digest was never a digest — so scoping (a) to delivered runs is arguably
      the faithful reading, not a loosening. Left alone deliberately: I have already changed the
      provenance checks three times tonight and this one is yours.
- [ ] **Read [docs/DIVERGENCES.md](docs/DIVERGENCES.md) row 8 before writing Checkpoint 4.** The
      check was loosened three times and its fail-response narrowed once, all on false alarms. The
      guarantee held; it has not yet been *tested* by a real fabrication. That distinction is the
      honest thing to write.
- [ ] **Review the news feed list and topic queries** in `forecaster/config.toml`. Five feeds and
      three topics ship as defaults; nothing in the code knows those ids. This is taste, not design.
      Worth knowing: **OpenAI's feed blocks the article fetch**, so all five of its entries fall back
      to ~150-char summaries. It is contributing headlines, not documents.

- [x] **Merge the FR-9b PR into `dev`.** Done 2026-08-04: PR #1 merged as `f452153`
      (merge commit, not squash, so BUILD-PROGRESS's per-step SHAs stay reachable).
      265 tests green on `dev`. `main` untouched.
- [x] **Submit Assignment 2.** Done 2026-07-27.
- [x] **Decide the SMS-vs-email framing** (PRD §9 Q1). Done 2026-08-02: deliberate scope cut,
      acknowledged in Checkpoint 3. DIVERGENCES row 1 closed.
- [x] **Answer PRD §9 Q3 — item identity for the ledger.** Done 2026-08-02: identity is a
      read-time relation between a candidate and what's already been sent, not a stored property.
      That unblocked FR-9b, which is now built.

### Before the Forecaster build can run

The code is built and its test suite is green (265 tests, no network, no model calls).
Four things below are **blocking a first real run** — everything else is done.

- [x] **① Mint a Claude Code OAuth token** — done (verified 2026-08-24: token in `.env`,
      every live trace since 2026-08-04 records `auth_mode=subscription_oauth`). Original
      steps kept below for the day the token rotates. Put it in `forecaster/.env` as
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

- [x] **② Do the first end-to-end run** — done: live dry runs since 2026-08-04, most
      recently 2026-08-24 (full digest, provenance 0 violations). All used the fake
      deliverer, so nothing has been sent — that's ③. Uses the fake deliverer — nothing
      is sent — but a real agent client and the two live APIs.
      ```powershell
      cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
      Remove-Item Env:ANTHROPIC_API_KEY -ErrorAction SilentlyContinue
      uv run python -m forecaster.cli --dry-run
      ```
      It should print the digest and write a trace under `data\runs\`.

- [x] **③ Create an SMTP app password and send one real digest** — **done 2026-08-24,
      receipt verified 2026-08-28**. Sarah created the app password (~7:07 pm CT, Google's
      security alert confirms it), filled the six SMTP values in `.env`, and ran
      `--send-test` herself: trace `20260825T001009-67993125` records `EmailDeliverer`
      `success: true` to her address at 00:13:34Z. The digest is in the inbox —
      "Forecaster — tonight's digest", received 2026-08-25T00:13:33Z, matching the trace
      to the second. **FR-12's acceptance is met.** For rotation someday:
      https://myaccount.google.com/apppasswords → app password named `forecaster` →
      `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, user/from/to = your address, then
      `uv run python -m forecaster.cli --send-test` and confirm receipt.

- [~] **④ Register the nightly scheduled task.** Registered and armed (verified
      2026-08-24: fires 19:00 daily, real-send mode). Two caveats before calling it done:
      it **refuses to start on battery** (`DisallowStartIfOnBatteries` — the 08-24 09:00
      attempt was refused with 0x800710E0 for exactly this), and it neither wakes the
      laptop nor catches up missed slots (`WakeToRun`/`StartWhenAvailable` both off), so
      a lid-closed 7 pm is a silent miss. To loosen (your call — a caught-up run fires
      *late*, which the delivery metric then counts as late rather than missed):
      ```powershell
      $s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
      Set-ScheduledTask -TaskName 'Forecaster Nightly' -Settings $s
      ```
      **Measured state as of 2026-08-28: FR-14 is at 0 of 3 nights.** ③ is done, so the
      send step no longer blocks — but no scheduled run has succeeded yet:
      - **08-24 19:00**: the task fired and exited 1 at the send step
        (`data\logs\nightly-20260824-190002.log`) — the SMTP values were still empty;
        Sarah filled them ~19:10, *after* it ran. Known cause, not a code bug.
      - **08-25, 08-26, 08-27**: the task never started — no log, no trace, Task
        Scheduler still shows last run 08-24. The battery/no-wake caveat above is live,
        and a never-started night is invisible even to `missed_run` (the runner backfills
        only when it next runs). Loosening the settings (block above) is still your call.
      Next chance is tonight, 08-28 19:00 — laptop plugged in and awake, or settings
      loosened, and it should be unattended night 1 of 3.
      Original registration steps, for re-creating the task:
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

      **④ is now the gate on more than FR-14.** The news beat's §2(c) — at least one suppression on
      **organically accumulated** history over 14 consecutive nights — is what retires DIVERGENCES
      row 4, and only real nights can produce it. Check progress any time:
      ```powershell
      cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
      uv run python -m forecaster.cli --news-metric
      ```
      It reports "N of 14 nights" and will not claim the condition early. It also states plainly
      that it cannot tell organic history from a hand-seeded ledger — that part is your judgement,
      not the checker's.


### Design decisions the build deliberately did not make

These are PRD §9 open questions. The build surfaced them rather than guessing; each one
gates real work.

- [x] **Q3 — item identity for the ledger.** Answered 2026-08-02. FR-9b is built.
- [~] **Q2 — rules vs judgment.** Escalation is still deterministic rules only, and Q2 *for
      escalation* is still yours to decide. **Answered for the need-to-know beat's importance bar
      on 2026-08-14** (structured interview, eight decisions — recorded in
      [docs/prd/need-to-know-news/PRD.md](docs/prd/need-to-know-news/PRD.md) §9 Q2): the FR-9b
      split transfers, suppress-when-unsure, watchlist carve-out, 2–3 nights/fortnight target.
      The beat's escalation contribution stays deterministic so this answer doesn't leak into the
      open half.
- [ ] **Retry the Ticketmaster developer signup** (first attempt failed 2026-08-16 — cause
      unknown; try a different browser, no VPN, or their support). This gates only Bass Concert
      Hall (venue-listings FR-47); ZACH ships without it. Free tier verified 2026-08-14: 5,000
      calls/day vs our ~1/night. When it works, ~5 minutes:
      1. https://developer.ticketmaster.com → **Get Your API Key** → create the account (it's a
         standalone developer account, not your ticket-buying login).
      2. Confirm the verification email, log in.
      3. **My Apps** → **Add a New App** → name `forecaster`, any one-line description; leave
         OAuth/redirect fields blank.
      4. Copy the **Consumer Key** into `forecaster\.env` as `TICKETMASTER_API_KEY=...`
         (gitignored; never paste it in chat; `.env.example` gets a placeholder at build time).
      5. Sanity-check + get the Bass venue id (paste the id back into a session — it's not a
         secret):
         ```powershell
         cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
         uv run python -c "import os; from forecaster.agent import load_env; load_env(); import httpx; r = httpx.get('https://app.ticketmaster.com/discovery/v2/venues.json', params={'keyword': 'Bass Concert Hall', 'stateCode': 'TX', 'apikey': os.environ['TICKETMASTER_API_KEY']}, timeout=20); print(r.status_code); [print(v['name'], v['id']) for v in r.json().get('_embedded', {}).get('venues', [])]"
         ```
- [ ] **Grow the `[wsb]` stoplist as false positives annoy you.** The counter is pattern +
      stoplist by your 2026-08-24 decision, and all-caps WSB titles make every short
      uppercase word a candidate (`CALLS` is not a ticker; `CAKE` is). Every match is
      post-attributed in the trace, so a wrong one is findable in minutes: open the
      night's trace, find the `wsb.count_mentions` observation, and add the offender to
      `stoplist` in `forecaster\config.toml`. No code change. Until you've spot-checked
      accumulated nights, no checkpoint may call the counts "accurate" (child §9 Q1).
- [ ] **Review the need-to-know feed list and watchlist seed terms** in
      [docs/prd/need-to-know-news/PRD.md](docs/prd/need-to-know-news/PRD.md) §6 and FR-38 before
      its build. Four feeds verified free and keyless on 2026-08-14: BBC World, NPR News,
      Al Jazeera, Texas Tribune (the local counterweight); the Guardian blocked the fetch; AP and
      Reuters have no verifiable open feed. The watchlist seed (ERCOT, Austin Water, boil notice,
      evacuation, grid emergency…) is the piece worth ten minutes: an over-broad term escalates
      nightly, and a missing one is a safety story the bar may PASS on. Both are your taste, not
      design.
- [ ] **Q5 (new) — validate the retrieval thresholds.** `k = 5`, `similarity_floor = 0.60`,
      `window_days = 14` are reasoned, not measured. After a few weeks of real runs, read the
      traces and tune:
      ```powershell
      cd "C:\Users\Sarah\Documents\31 Emeritus\forecaster"
      Get-ChildItem data\runs\*.jsonl | ForEach-Object { Get-Content $_ } |
        ConvertFrom-Json | Where-Object { $_.decision -like 'dedup_*' } |
        Select-Object decision, top_similarity, reason
      ```
- [ ] **Q6 (new) — the news beat's corpus-retrieval thresholds.** `k = 6`,
      `similarity_floor = 0.35`, `window_days = 3`, `max_chunks_per_article = 2`. Reasoned, not
      measured, and a **separate** question from Q5: Q5 compares a candidate line to past lines,
      Q6 matches a topic query to article chunks. Same rule applies — no checkpoint may call
      either set tuned. [docs/prd/ai-news-beat/PRD.md](docs/prd/ai-news-beat/PRD.md) §9.
- [ ] **Review the news feed list and topic queries** in that PRD's §6 before the build. The five
      feeds and three topics are a starting proposal; they are your taste, not a design decision,
      and nothing in the code knows those ids.
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

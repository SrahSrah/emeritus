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
- [ ] **Review the need-to-know feed list and watchlist seed terms** in
      [docs/prd/need-to-know-news/PRD.md](docs/prd/need-to-know-news/PRD.md) §6 and FR-37 before
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

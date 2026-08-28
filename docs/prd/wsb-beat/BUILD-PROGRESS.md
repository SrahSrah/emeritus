# BUILD PROGRESS — r/WallStreetBets beat, v1

Resumable ledger for [`BUILD-PROMPTS.md`](BUILD-PROMPTS.md). One row per step, updated as the
build lands. If this file and `git log` disagree, trust git and repair this file.

| Step | What | State |
|---|---|---|
| 51 | `[wsb]` config + `fetch_feed` `beat` keyword | done — 589 passed (from 583) |
| 52 | real fixture + `count_mentions` (FR-48) | done — fixture live 2026-08-28 (25 entries, one request); 8 counter tests |
| 53 | `WsbMentionsBeat` + quiet/broken + registration (FR-49, FR-50) | done — 610 passed (from 589); beat enabled in config.toml |
| 54 | counts-not-picks invariant (FR-51) | done — template pinned by independent reconstruction; raising client on all four paths |
| 55 | `wsb_metric.py` + `--wsb-metric` (FR-52) | done — 622 passed (from 610); each violating trace names its condition |
| 56 | reconcile the record | todo |

## Notes discovered during the build

_(appended as they happen)_

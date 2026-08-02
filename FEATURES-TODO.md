# FEATURES-TODO — Emeritus / Forecaster

Build work, ordered by when it likely becomes relevant. Human-only tasks live in
[HUMAN-TODO.md](HUMAN-TODO.md); the spec of record is
[docs/prd/forecaster/PRD.md](docs/prd/forecaster/PRD.md).

Status: `[ ]` open · `[~]` in progress · `[x]` done

## Shipped in v1

- [x] FR-1 … FR-9, FR-10 … FR-15, FR-18 — all 16 MVP requirements, 221 tests green.

## Shipped in v2 — the Module 3 increment (2026-08-02)

- [x] **FR-9b — retrieval-backed dedup / "what's new" framing.** model2vec static embeddings
      indexed by sqlite-vec inside the existing `ledger.db`; retrieval narrows to the k nearest
      same-beat items, a model judgment decides include/reframe/suppress.
- [x] **FR-19 — retrieval safety invariants.** Five rules enforced around the model, one test
      each. The load-bearing one: a differing checkable value can never be suppressed.
- [x] **PRD §9 Q3 answered** — identity is a read-time relation, not a stored property. This is
      why there is still no identity column.
- 256 tests green, no network, no model calls, no torch, no paid dependency.

## Blocked on a decision, not on effort

- [ ] **Validate the retrieval thresholds.** `k = 5`, `similarity_floor = 0.60`,
      `window_days = 14` are reasoned, **not measured** — nothing has run against a real
      multi-week ledger. The trace records every neighbour and score so they can be tuned from
      evidence. PRD §9 Q5. Don't let a checkpoint describe them as tuned.
- [ ] **Multi-day freeze horizon.** `freeze_horizon_days` exists in config but the weather
      adapter fetches only the next morning's window. Extending it is a scope decision.
- [ ] **Injury data source.** FR-10's injury escalation rule is implemented and **dormant** —
      no v1 endpoint returns injuries. Needs a feed before it can ever fire.

## Next increments — one per course checkpoint

- [ ] **FR-16 — reply-driven feedback loop.** Reply to the digest in plain English; parse it
      into a durable preference rule. Needs an inbox-read path, which v1 doesn't have.
- [ ] **FR-17 — the remaining four beats**, each a `Beat` implementation plus a config entry,
      with no change to planner, synthesizer, or delivery:
  - [ ] AI / Claude news — **the first real test of FR-9b.** The v1 beats don't naturally
        repeat, so dedup has only ever run against a seeded ledger (DIVERGENCES row 4). News
        is where repetition is frequent and where the thresholds get their workout.
  - [ ] r/WallStreetBets mention volume
  - [ ] "need-to-know" news (the bar is higher than daily drudgery)
  - [ ] Austin live music and theatre

## Likely, but unconfirmed

The syllabus past Module 2 is unknown, so these are educated guesses, not commitments. The
architecture was built to absorb them: beats behind one protocol, tools behind adapters, and a
run trace that already records more than v1 consumes.

- [ ] **Evaluation / observability module.** The run trace was over-built for exactly this —
      per-beat traces, tool calls, decisions with reasons, timings, token usage.
- [ ] **Guardrails / safety module.** FR-18's no-fabrication guarantee is the seed.
- [ ] **Multi-agent orchestration.** The planner/worker split is already the shape.
- [ ] **Deployment.** Currently Windows Task Scheduler on one laptop.

## Known debt

- [ ] **Offseason behavior.** November–March there are no Astros games. The beat degrades to
      "no games", but the centerpiece loses its demo value for a third of the year.
- [ ] **`statsapi.mlb.com` is undocumented.** Fine personally; it can change shape without
      notice. The adapter must keep failing loudly rather than guessing.
- [ ] **Missed runs.** A sleeping laptop at 7 pm produces no digest and no error. The runner
      records `missed_run` so the delivery metric stays honest — verify that works in practice.

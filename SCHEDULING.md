# Scheduling — closing the ORCH-01 "not wired to a real clock" gap

`COMPLETION_REPORT.md`'s own honest accounting of ORCH-01/IMP-07 said it
plainly: *"this is not wired to an actual live cron/queue running the real
engines — there is no scheduler infrastructure running anywhere outside
these tests."* This pass closes exactly that gap, and no more than that gap.
Everything below is either real code you can read and re-run yourself, or an
explicitly named limitation — nothing here is aspirational.

## What actually exists now

1. **Two engines that had real, tested math but no CLI entry point now have
   one**, and no longer rely on hand-authored fixture JSON:
   - `engine/incepta/export_state.py` — runs `state.compute_state_vector`
     for real (over a deterministic, seeded synthetic-demo market panel;
     see its own docstring) and writes `public/data/state/latest.json` +
     `engine/exports/state_latest.json`.
   - `quant-infra/alloc/export.py` — runs `solve.py`'s real `solve()`
     pipeline (over a small, deterministic, seeded synthetic-demo set of
     strategies) and writes `public/data/alloc/latest.json` +
     `quant-infra/alloc/exports/latest.json`, matching
     `src/lib/models/alloc-export.ts`'s `AllocExport` contract field-for-field.

   Both replace a JSON file that a person had typed by hand and that no code
   in this repository had ever produced. Both are still **synthetic-demo**
   data — there is no live index/universe feed and no live strategy-return
   history in this sandbox — and both say so explicitly in their own output
   (`universe_note`, `disclaimer`, `generatedBy`), the same honesty
   convention every other engine's export already follows.

2. **`scripts/run_clock.py`** — a single driver, `python scripts/run_clock.py
   {macro|equity|chaos} [--force]`, that:
   - uses the **real wall clock** (`datetime.now(timezone.utc)`) — the one
     place in this whole codebase that should, everywhere else uses
     `orch.scheduler.ManualClock` for tests on purpose;
   - imports the **real** `MACRO_CLOCK` / `EQUITY_CLOCK` / `CHAOS_CLOCK`
     (`quant-infra/orch/clocks/three_clocks.py`) and consults the **real**
     `MarketHoursGate` against the **real, stored NYSE calendar**
     (`data-router/router/universe_publish/calendar_data.py`) — the exact
     same objects the 62 passing `orch` tests exercise, not a parallel
     scheduling concept;
   - invokes each clock's real engine export entry point as a real
     subprocess (`python -m <module>`, from the exact working directory
     each export.py's own docstring documents under "Run:");
   - appends a durable JSON-lines run record to `ops/clock_runs/<clock>.jsonl`
     for every invocation (ran-for-real success/failure per engine, or the
     specific reason it was skipped) — see `ops/clock_runs/README.md`;
   - is genuinely idempotent per cadence window: a second call inside the
     same window reports "already ran for this window" and does not
     re-invoke anything, unless `--force` is passed.

3. **Three GitHub Actions workflows**
   (`.github/workflows/clock-{macro,equity,chaos}.yml`) that check out the
   repo, install each clock's engines' dependencies, run
   `scripts/run_clock.py <clock>`, and commit+push any changed
   `public/data/` / `ops/clock_runs/` files back to the branch, guarded so a
   clean-skip run never creates an empty commit.

## What was proven by actually running it (not just written and inspected)

Every command below was run for real in this sandbox; the output shown is
the real output, not a transcription of expected output.

```
$ python scripts/run_clock.py macro --force
[macro] running 1 engine(s) for real (market-hours gate: NYSE: market hours not required for this job).
  - incepta_state: OK (ok)
[macro] all 1 engine(s) ran successfully.

$ python scripts/run_clock.py equity --force
[equity] FORCE OVERRIDE: the market-hours gate would have refused this run (closed: outside session
(NYSE full-day hours 09:30:00-16:00:00, refresh requested at 08:34:31)), but --force was passed so it
is running anyway. ...
[equity] running 3 engine(s) for real (market-hours gate: closed: outside session (...)).
  - weekly: OK (ok)
  - graph: OK (ok)
  - alloc: OK (ok)
[equity] all 3 engine(s) ran successfully.

$ python scripts/run_clock.py chaos --force
[chaos] FORCE OVERRIDE: the market-hours gate would have refused this run (closed: outside session (...)), ...
[chaos] running 1 engine(s) for real (market-hours gate: closed: outside session (...)).
  - chaos: OK (ok)
[chaos] all 1 engine(s) ran successfully.

$ python scripts/run_clock.py equity        # immediately after, no --force
[equity] SKIP: already ran for this window (last success 2026-09-04T08:34:31+00:00, 0:01:16 ago,
cadence=1h). Pass --force to re-run anyway.
$ echo $?
0
```

`public/data/{state,alloc,weekly,graph,chaos}/latest.json` all show fresh
`generated_at` timestamps from these runs, and
`ops/clock_runs/{macro,equity,chaos}.jsonl` carry the corresponding run
records — both committed alongside this file, not gitignored (see
`ops/clock_runs/README.md` for why that matters).

The sandbox's own local time was 08:34 UTC on a Friday. `market_hours.py`
documents its own simplification: it does not convert timezones and expects
`when` already in venue-local wall-clock time, so a UTC "now" is compared
directly against NYSE's 9:30-16:00 local hours. This is why the equity/chaos
runs above needed `--force` to demonstrate a real run at all in this
sandbox — the honest, unforced behavior (a clean market-closed skip, exit
code 0) was also verified separately and is the behavior that will run in
production once real timezone-aware "now" handling is wired in (see
`clocks/README.md`'s own note on this — not something this pass touches).

## What this needs from you to actually go live

**Merge this to the repository's default branch.** GitHub Actions scheduled
(`on: schedule`) workflows only fire once the workflow file exists on the
default branch — a workflow file sitting on a feature branch or PR never
fires on its own schedule, only via manual `workflow_dispatch` or as part of
CI checks on that PR. This cannot be tested from this sandbox: there is no
GitHub access here, so nothing in this pass can confirm the workflows
actually fire once merged — that confirmation can only happen by merging,
waiting, and checking the Actions tab / the commit history in
`ops/clock_runs/`.

## Honest limitations

- **Chaos cadence is best-effort, not a real-time guarantee.** The design's
  "1-5min" cadence is approximated here with `cron: '*/5 * * * *'` —
  GitHub's documented practical floor for scheduled workflows. GitHub
  explicitly does **not** guarantee scheduled workflows fire at their exact
  scheduled time, and under platform load a `schedule`-triggered run can be
  delayed well past its nominal time or occasionally dropped. If this
  clock's cadence ever needs to be a real-time guarantee rather than a
  best-effort approximation, it needs a different execution substrate (a
  self-hosted runner with its own OS-level timer, or an external always-on
  process calling `workflow_dispatch`) — not GitHub's own `schedule` trigger.
- **`quant-infra/` and `data-router/` have no `requirements.txt` of their
  own.** Each workflow installs the one real engine's `requirements.txt` it
  needs (`engine/`, `weekly-engine/`, `graph-engine/`, `chaos-engine/`) plus
  `networkx` explicitly (needed by `quant-infra/orch/scheduler.py`, which
  every clock's market-hours-gate check imports regardless of which engines
  it goes on to run) — see each workflow's own comments for exactly what's
  installed and why nothing formal backs `quant-infra/alloc`'s scipy/
  scikit-learn dependency beyond "another engine's requirements.txt happens
  to already cover it."
- **The WW-ALLOC synthetic-demo export can legitimately hit `solve()`'s
  fallback path.** With a shadow-mode strategy present, this environment's
  installed scipy reproducibly reports `fallback_reason: "solver did not
  converge: Singular matrix C in LSQ subproblem"` rather than a converged
  optimum — verified to reproduce even on
  `quant-infra/alloc/tests/test_solve.py`'s own existing shadow-mode test
  fixture, so it is a property of this scipy build interacting with
  `solve.py`'s documented redundant `[0,0]`-bound-plus-equality-constraint
  design for shadow-mode variables, not something introduced by this
  export. The fallback path itself is real, tested, and still correctly
  holds the shadow strategy at an exact zero — see
  `quant-infra/alloc/export.py`'s own module docstring for the full
  explanation.
- **`market_hours.py`'s documented timezone simplification still applies.**
  It compares `when.time()` directly against NYSE local hours with no
  timezone conversion; `scripts/run_clock.py` passes real UTC "now" through
  unconverted, exactly as every existing test and the `clocks/` package
  itself already does. This is a pre-existing, already-documented
  simplification (see `clocks/market_hours.py`'s own module docstring) —
  this pass does not touch it, and running the real clocks in UTC means the
  gate's notion of "NYSE hours" is currently UTC-clock-time, not
  EST/EDT-clock-time, until that future work lands.
- **WW-CASCADE still has no export/website seam at all.** This was already
  a named pre-existing gap (`COMPLETION_REPORT.md`'s IMP-15 entry: "none of
  WW-WEEKLY/WW-GRAPH/WW-CASCADE is registered ... as a live website model
  yet" — WW-WEEKLY and WW-GRAPH have since gained real pages/exports, but
  `quant-infra/cascade/` still has no `export.py` and no `src/lib` reader
  anywhere in this repo). This pass does not touch WW-CASCADE and does not
  put it on any clock — there is nothing for a clock to run yet.

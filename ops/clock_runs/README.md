# ops/clock_runs/ — the durable clock heartbeat

`scripts/run_clock.py` appends one JSON object per line to
`ops/clock_runs/<clock>.jsonl` (`macro.jsonl`, `equity.jsonl`, `chaos.jsonl`)
every time it is invoked — whether it actually ran an engine, was skipped
because the market-hours gate refused, or was skipped because the clock
already ran successfully inside its own cadence window.

**These files are committed to git on purpose, not gitignored.** GitHub
Actions runners are ephemeral — every workflow run starts from a fresh
checkout with no memory of any previous run. If this log lived only on the
runner's disk, ORCH-01's idempotent-replay requirement ("running the same
clock twice inside one cadence window is a no-op, not a second real run")
would be unenforceable across separate workflow runs, and there would be no
durable record that a clock ever fired at all. Each `clock-*.yml` workflow
commits and pushes any changes under this directory back to the repository
after every run (see `SCHEDULING.md`), so this log is the durable
heartbeat/completion record for all three clocks.

## Format

One JSON object per line (JSON Lines). Fields:

| field | meaning |
|---|---|
| `timestamp` | ISO-8601 UTC timestamp `scripts/run_clock.py` was invoked at (real wall-clock time, `datetime.now(timezone.utc)` — never a fake/injected clock) |
| `clock` | `"macro"` \| `"equity"` \| `"chaos"` |
| `cadence` | the real cadence string from `quant-infra/orch/clocks/three_clocks.py`'s `ClockJob.spec.cadence` (`"12h"` / `"1h"` / `"1-5min"`) at the time of the run |
| `ran_for_real` | `true` only if at least an attempt was made to invoke the clock's engine export entry point(s) this call; `false` for every skip |
| `forced` | whether `--force` was passed |
| `overall_status` | `"success"` (every engine invoked succeeded), `"failed"` (one or more engines failed), `"skipped_market_closed"`, or `"skipped_already_ran_window"` |
| `market_hours_gate` | present when the gate was actually consulted: `{"allowed": bool, "reason": str}` from the real `MarketHoursGate.should_run(...)` |
| `detail` | human-readable explanation, always present |
| `engines` | list of `{"name", "success", "detail", "returncode"}` per engine invoked this call; empty on any skip |

## Idempotent-replay rule

Only a record with `ran_for_real: true` **and** `overall_status: "success"`
starts a cadence window. A prior failure or skip never blocks a retry —
only a genuinely clean run does — so a transient engine failure can always
be retried immediately without needing `--force`. See
`scripts/run_clock.py`'s own docstring and
`last_successful_real_run_at` for the exact logic.

## What's actually in this directory right now

The `.jsonl` files present alongside this README are real output from
running `scripts/run_clock.py macro|equity|chaos --force` by hand while
building this feature (see `SCHEDULING.md` for the exact commands and
their real output) — not hand-authored fixtures. They will keep growing as
the GitHub Actions workflows fire on schedule once this is merged to the
default branch.

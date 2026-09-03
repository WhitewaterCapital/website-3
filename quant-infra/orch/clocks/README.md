# clocks/ — IMP-07: three clocks, market-hours-gated, on top of `orch/scheduler.py`

`orch/scheduler.py` (ORCH-01) already implements a generic, tested
job-dependency scheduler: per-job cadence, a per-job stale-input policy
(`proceed_marked_stale` / `skip_hold_previous` / `fail_loud`), per-cadence-tier
concurrency budgets, and heartbeat/health tracking. It is deliberately generic
— no notion of "macro" vs "equity" vs "chaos", no notion of a market being
open or closed. This package is IMP-07's "attach anything new" step on top of
that scheduler, per the spec's own sequencing: *"Build the scheduler first
with all three clocks running against the models we already have, confirm
the timestamps behave, then attach anything new."*

## What was missing, and what's here

1. **Market-hours awareness** (`market_hours.py`). Nothing in `scheduler.py`
   checks whether a venue is open before deciding a job should run — so
   today it would happily "refresh into a closed market and call the output
   new," which IMP-07 explicitly forbids. `MarketHoursGate.should_run(when,
   requires_market_hours)` is that missing check. It is intentionally a
   separate object rather than a new field on `scheduler.JobSpec`: cadence
   freshness and market-hours are different questions ("is this input recent
   enough" vs. "is anyone even trading right now"), and `scheduler.py` is
   read-only for this task anyway.

   `MarketHoursGate` depends only on a small duck-typed `CalendarLike`
   protocol (`session_kind(date) -> "full" | "half" | "closed"`) — it does
   **not** import anything from `data-router`. `adapt_venue_calendar()` is a
   plain function that wraps any object shaped like `data-router`'s
   `calendar_data.VenueCalendar` (`.session_type(date)` returning something
   with `.value` in `{"full_day","half_day","closed"}`) into a `CalendarLike`.
   Only `tests/test_market_hours_integration.py` actually imports the real
   `data-router/router/universe_publish/calendar_data.py` and passes it
   through that adapter, as an integration proof — every other file in this
   package stays decoupled from `data-router`.

2. **The three concrete clocks** (`three_clocks.py`): documented example
   `JobSpec`s wired against the real scheduler.

   | Clock  | `cadence` | `stale_input_policy`   | `requires_market_hours` |
   |--------|-----------|------------------------|--------------------------|
   | macro  | `12h`     | `skip_hold_previous`   | `False`                  |
   | equity | `1h`      | `proceed_marked_stale` | `True` (NYSE)            |
   | chaos  | `1-5min`  | `fail_loud`            | `True` (NYSE)            |

   The policy choice for each is the spec's own words, or a documented
   judgment call where the spec allows either:
   - **macro**: *"On failure hold the previous output and mark it stale.
     Never interpolate a macro series."* → `skip_hold_previous`.
   - **equity**: judgment call. Equity research is wired to depend on the
     macro clock's output (`inputs=("macro_regime",)`), and macro only
     refreshes every 12h — so under equity's own 1h cadence, the macro input
     is essentially *always* older than equity's own freshness allowance.
     `proceed_marked_stale` lets equity run every hour as intended while
     still surfacing that staleness explicitly (`RunRecord.status ==
     "stale_but_ran"`), rather than either fabricating freshness or refusing
     to ever run.
   - **chaos**: *"Fail fast, because a stale chaos reading is worse than
     none."* → `fail_loud`.

   **"Each clock gets its own queue, its own request budget, and its own
   alarm"** falls out of the existing scheduler almost for free: a `JobSpec`
   cadence string doubles as its tier name (`tier_for_cadence` is the
   identity function in `scheduler.py`), and `Scheduler` builds one
   independent `TierBudget` per distinct cadence — so `"12h"`, `"1h"`, and
   `"1-5min"` are three separate in-flight sets with independent
   `max_concurrent` caps automatically. That is exactly why **"a failing
   hourly job must never starve the macro cycle"** holds structurally: the
   equity clock's `"1h"` tier budget is a completely different object from
   the macro clock's `"12h"` tier budget; exhausting one cannot touch the
   other. "Its own alarm" is each clock's own `heartbeat_timeout` on its
   `JobSpec` (chaos sets a tight 3-minute timeout instead of the scheduler's
   30-minute default, matching its much faster cadence).

   `run_clock_job(scheduler, clock_job, gate, run_timestamp, work_fn)` is the
   glue: it calls `gate.should_run(...)` **before** ever calling
   `scheduler.run_job(...)`. If the gate refuses, `scheduler.run_job` is
   never invoked for that `(job, run_timestamp)` at all — the scheduler's own
   cadence/freshness view (which has no concept of a closed venue and would
   evaluate purely on input recency) never gets a chance to overrule a
   market-hours refusal. The refusal always comes back as an explicit
   `RunRecord` with a specific reason string in `detail` — never a silent
   no-op.

3. **The source-aware refresh guard** (`derived_value_guard.py`): a reusable
   implementation of the doc's "source aware rule" — *"a refresh recomputes
   derived values, it never restates the observation date of a monthly or
   quarterly source."* `SourceAwareRefresh` only advances its stored
   observed-date when a fetch carries a **strictly newer** observed-date than
   what's already stored; a same-dated (or older-dated) refetch is looked at
   and discarded for state purposes. The derived value (default: a z-score
   against a rolling context window) is recomputed on **every** call,
   regardless of whether the observed-date moved — because the window it's
   scored against can shift even when the underlying print hasn't.
   `tests/test_derived_value_guard.py` runs the acceptance scenario named
   directly in the spec: 60 simulated hourly refreshes of a monthly series,
   observed-date flat across calls 1-40, one genuine vintage change at call
   41, flat again through call 60 — while the derived z-score is shown to
   take multiple distinct values across calls 1-40 alone (fed slightly
   different rolling-window context at a few of those calls), proving it
   really does recompute every call rather than being frozen alongside the
   observation date.

## Documented gaps / future work

- **Calendar data is a hand-built sample table, not a live feed.**
  `data-router/router/universe_publish/calendar_data.py`'s own module
  docstring is explicit that its NYSE holiday/half-day tables are a
  literal, dated, manually transcribed table (2024-2027), not computed at
  runtime — precisely so a calendar library's algorithmic drift can't
  silently change the answer. That is the right call for reproducibility,
  but it also means: extending coverage past 2027, or picking up an ad hoc
  market closure, is a manual data update to that table, not something this
  package (or that one) does automatically. Real production market-hours
  gating needs a live/maintained calendar feed with a process behind it for
  keeping the stored table current — that is out of scope here.
- **No timezone handling.** `MarketHoursGate` compares wall-clock `time`
  values with no timezone conversion; callers must already express `when` in
  the venue's local time (e.g. NYSE = America/New_York). Correct
  UTC-scheduled-job-to-venue-local-time conversion (including DST) is future
  work.
- **`TierBudget`/queue are still the documented in-memory stand-in from
  `scheduler.py` itself** — no real task queue, cron, or thread pool behind
  any of the three clocks. This package proves the *mechanism* (market-hours
  gating + source-aware refresh), matching the spec's own sequencing:
  "build the scheduler first ... then attach anything new." Wiring these
  three clock definitions to actually run the real macro/equity/chaos jobs
  (an Aurora sync, `weekly-engine`, `chaos-engine`) end-to-end against a live
  cron/queue is future work, not attempted here.
- **`inputs`/`outputs` names here (`macro_regime`, `equity_research`,
  `chaos_signal`) are illustrative**, chosen to demonstrate the cross-tier
  dependency behavior (equity depending on a much-slower macro output) — not
  wired to any real job's actual output schema.

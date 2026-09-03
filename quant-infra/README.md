# quant-infra

Four independent, pure-math/logic Python packages for the long/short
equities platform. None of them touch live data, market feeds, or
credentials — every function operates on inputs the caller supplies (real
data plugs in later, once each engine is wired to it). Each subpackage is
its own root: run its tests with

```bash
python3 /home/claude/repo/_pyshim/run_tests.py <abs>/quant-infra/<subpackage> tests
```

(e.g. `.../quant-infra/cascade tests`). Because each subpackage's tests run
with that subpackage's own directory as the import root, modules import each
other with bare names (`from pressure import ...`, not
`from cascade.pressure import ...`) — this mirrors how
`intra-exitus-engine`'s `ie/` tests resolve against `intra-exitus-engine/`
as the root, just one level shallower since each of these four packages is
its own sealed root rather than a shared one.

| Subpackage | Spec item | What it is |
|---|---|---|
| `cascade/` | CASC-01 | Fund-flow mechanical pressure on constituents |
| `alloc/` | ALLOC-01 | Cross-strategy capital allocation solver |
| `loop/` | LOOP-01/02/03 | Self-improvement loop: promotion gate, drift, exploration |
| `orch/` | ORCH-01 | Dependency-aware job scheduler skeleton |

---

## `cascade/` — WW-CASCADE (CASC-01)

Detects mechanical flow pressure on a fund's constituents and how much of
any resulting price move sticks.

- **`pressure.py`** — `estimate_flow_from_shares_outstanding` (direct, from
  a fund's own creation/redemption activity) and `estimate_flow_proxy`
  (volume + NAV premium/discount, explicitly labelled `is_proxy=True` in its
  output) produce a signed dollar `FlowEstimate` per product.
  `compute_pressure(holdings, flows, typical_volume)` sums
  `weight * flow_dollars / typical_volume` **across every product a name
  sits in** — the doc's explicit failure mode ("a name in twelve funds") is
  a named test (`test_name_in_twelve_funds_is_summed_across_all_of_them`).
  A leg with unusable inputs (no flow, NaN weight, non-positive typical
  volume) is *excluded* from the sum, never coerced into a fake zero or a
  NaN that would poison every other product's contribution.
- **`transmission.py`** — regresses realised return on pressure with
  `sklearn.linear_model.LinearRegression`, controlling for name-level
  covariates (e.g. sector move). Validated on synthetic data generated FROM
  a known coefficient plus noise; the fit must recover it within a
  documented tolerance (see the numbers below).
- **`decompose.py`** — fits `impact(h) = permanent + temporary *
  exp(-decay_rate * h)` via `scipy.optimize.curve_fit`, splitting a pressure
  event's realised impact into the part that never reverts (`permanent`)
  and the part that decays away (`temporary`, at `decay_rate`). Validated on
  synthetic exponential-decay data with a known floor and rate.

**Recovered-coefficient validation** (see
`cascade/tests/test_transmission.py`, `cascade/tests/test_decompose.py`):

| Quantity | True | Recovered |
|---|---|---|
| transmission coefficient (beta) | 0.42 | 0.4198 |
| sector-move control (gamma) | -0.15 | -0.1504 |
| permanent floor | 0.02 | 0.02045 |
| temporary component | 0.05 | 0.05127 |
| decay rate | 0.30 | 0.3246 |

## `alloc/` — WW-ALLOC (ALLOC-01)

`solve.py`: shrink each strategy's raw edge towards zero by its live
track-record length (`shrink_edge`, `n / (n + prior_pseudo_obs)` weighting —
at `n=4` observations against the default `prior_pseudo_obs=60`, weight is
`~6%` of the raw mean, tested directly against several raw magnitudes),
score it (`score_strategy` = shrunk edge minus uncertainty and cost
penalties), then solve for budgets `w >= 0` maximising
`score.w - risk_aversion * w^T Cov w - turnover_penalty * sum|w - w_prev|`
subject to a per-strategy cap, a total gross limit, and a **hard zero** for
any shadow-mode strategy — enforced by binding that strategy's variable to
the degenerate box `[0, 0]` (exact under SLSQP's bound handling, not subject
to any constraint tolerance) plus a redundant literal equality constraint
for documentation/logging. `shrink_covariance` builds the strategy
covariance via `sklearn.covariance.LedoitWolf` shrinkage.

Solver guards: infeasible inputs (negative cap, negative total gross limit)
and a solution that would move more than `max_step_fraction` of the total
gross limit both **fall back to the previous budget** (with shadow-mode
strategies still forced to zero even on the fallback path — see
`test_shadow_mode_stays_zero_even_on_fallback_path`) and record why in
`SolveLog.fallback_reason`.

## `loop/` — self-improvement loop (LOOP-01/02/03)

- **`champion_challenger.py`** (LOOP-01) — `promote()` only promotes a
  challenger that beats the champion on BOTH primary quality metrics
  (rank IC, deflated Sharpe) by more than a documented noise margin, AND
  does not regress materially on either secondary guardrail (calibration
  error, turnover). A marginally-better challenger is a tie, not a
  promotion (`test_marginally_better_challenger_is_not_promoted`).
- **`drift.py`** (LOOP-02) — `detect_feature_drift` /
  `detect_prediction_drift` (`scipy.stats.ks_2samp` against a stored
  reference); `assess_drift` flags the diagnostic case where predictions
  drifted but inputs did not. `severity()` implements the doc's ladder
  exactly: a control-band breach demotes (shadow, budget zero) outranking
  sustained decay (monitoring) outranking bare drift (flag). Every function
  in this module can only flag, monitor, or demote — never promote or raise
  a budget; that only happens in `champion_challenger.promote()`, which is
  a distinct, opt-in decision.
- **`exploration.py`** (LOOP-03) — UCB-style allocator for a small
  exploration slice (`plausible_edge_estimate + exploration_k *
  uncertainty`, clipped at zero, normalised across challengers).
  `_HARD_CEILING_SHARE` (10%) is a module constant, not a function
  parameter, so no caller-supplied `total_share` — however large, `inf`, or
  adversarial — can push total exploration spend above it
  (`test_no_adversarial_config_can_exceed_the_architectural_ceiling`).

Two of the four vendored metrics in `champion_challenger.py` (`rank_ic`,
`deflated_sharpe_ratio`) are small local copies of the like-named functions
in `engine/incepta/validation/metrics.py`, copied rather than imported so
this package stays sealed (see that file's docstring for the citation
comment on each). `calibration_error` and `turnover` have no counterpart
there and are implemented fresh.

## `orch/` — orchestration scheduler skeleton (ORCH-01)

`scheduler.py`: each `JobSpec` is a node in a `networkx.DiGraph` (edges
drawn from a job's declared `outputs` to whichever other job names them in
its `inputs`), with a `cadence` string, a `stale_input_policy`
(`"proceed_marked_stale" | "skip_hold_previous" | "fail_loud"`), and a
`heartbeat_timeout`. `Scheduler.run_job` checks each declared input's
freshness against the **consuming job's own cadence** (an input fresh
enough for an hourly job may not be fresh enough for a 1-5 minute job — see
`test_input_fresh_for_its_own_cadence_but_would_be_stale_for_a_faster_one`),
enforces the policy, and is idempotent per `(job_name, run_timestamp)`: a
repeat call for a timestamp already recorded replays the stored
`RunRecord` without invoking `work_fn` again — including replaying a
recorded *failure*, since the recorded result is the durable historical
answer for that timestamp, not a cache to retry. `begin_run` /
`record_heartbeat` / `record_completion` / `health()` give explicit
visibility into a run's lifecycle; a run that stops reporting surfaces as
`"missing_heartbeat"` once its `heartbeat_timeout` elapses, never silently
as "fine". `Scheduler.disable(job_name)` marks exactly the transitively
downstream jobs (`networkx.descendants`) as stale, leaving independent jobs
untouched — the spec's own "done when" test
(`test_disabling_one_job_stales_only_its_downstream_dependents`).

**Documented simplification vs the doc's ask**: there is no real task queue
or thread pool. "Each cadence tier as its own named-queue/budget
abstraction" is `TierBudget` — an in-flight set with a `max_concurrent` cap
and `try_acquire`/`release` — a fully testable model of the concept with no
concurrency behind it. Wiring this to a real scheduler (cron, Airflow, a
message queue) is future work.

---

## Simplifications vs the doc's ask, and why

- **`alloc/solve.py` uses `scipy.optimize.minimize` (SLSQP), not a dedicated
  convex solver.** The doc asks for an "off-the-shelf convex solver"
  (`cvxpy` is the natural fit); `cvxpy` is not installed in this environment
  (`try: import cvxpy except ImportError` in `solve.py` confirms this
  honestly at import time rather than silently assuming either way). SLSQP
  finds the same optimum on this problem shape (smooth quadratic risk term,
  one linear budget constraint, box bounds) for well-scaled inputs, but
  lacks a QP solver's certificate of global optimality and can occasionally
  misreport non-convergence on badly-scaled inputs — which is exactly why
  the fallback-to-previous-budget guard exists regardless of which solver
  sits behind it.
- **`orch/scheduler.py` has no real task-queue/threading infrastructure.**
  `TierBudget` models the "queue/budget per cadence tier" concept with an
  in-flight set and a capacity check, callable and testable synchronously.
  Running it against real concurrent execution (a thread pool, Celery,
  Airflow) is future integration work; the state machine (freshness,
  idempotency, heartbeat visibility, downstream staleness) is what had to be
  correct first, independent of what actually executes the jobs.
- **`loop/champion_challenger.py` vendors two metrics from
  `engine/incepta/validation/metrics.py`** (`rank_ic`,
  `deflated_sharpe_ratio`) as small local copies rather than importing them,
  per the task's sealing requirement — this package must not break if that
  engine's file changes shape. `calibration_error` and `turnover` are
  implemented fresh since `metrics.py` has no counterpart for either.
- **Everything else** (pressure aggregation and its two flow-estimation
  paths, the transmission/decomposition fits, the shrinkage-based edge
  scoring, the promotion gate's noise-margin logic, the drift KS-tests and
  escalation ladder, the exploration UCB rule and hard cap, and the
  scheduler's dependency graph / freshness / idempotency / heartbeat model)
  is real logic, fully tested against edge cases (NaN, empty input, zero,
  negative, infeasible), ready to run once real data or a real scheduler
  backend is plugged in.

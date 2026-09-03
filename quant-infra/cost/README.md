# `cost/` — WW-COST (IMP-18)

Square-root market-impact cost estimate, calibration from realised fills,
a per-strategy capacity limit, and weekly realised-vs-predicted error
tracking.

- **`impact.py`** — `estimate_impact_cost(order_size, typical_volume,
  volatility, effective_spread, impact_coefficient=None)`: `cost =
  impact_coefficient * volatility * sqrt(order_size / typical_volume) +
  0.5 * effective_spread`. `impact_coefficient=None` (the default) uses
  `DEFAULT_IMPACT_COEFFICIENT = 1.0` — a documented, deliberately
  conservative placeholder, not a fitted number — and marks the result
  `calibrated=False`. Passing a fitted coefficient marks it
  `calibrated=True`.
- **`calibration.py`** — `calibrate_impact_coefficient(realized_fills)`
  isolates the sqrt-impact term (`realized_slippage - 0.5*effective_spread`)
  and fits `impact_coefficient` by through-the-origin least squares.
  Returns `None` — never a guess — below `MIN_FILLS_FOR_CALIBRATION = 20`
  *usable* fills (a fill with non-positive `typical_volume`, negative
  `order_size`, or a non-finite field does not count as usable).
- **`capacity.py`** — `estimate_capacity(expected_edge_bps, typical_volume,
  volatility, effective_spread, impact_coefficient)` solves the impact-cost
  formula in closed form for the `order_size` at which cost equals the
  edge — "the size where cost eats the edge." Returns `0.0` if the
  half-spread term alone already meets the edge, and `float("inf")` if
  `impact_coefficient` or `volatility` is `0` (no impact term to grow with
  size once past the spread floor) — both are documented, real
  consequences of the model, not numerical artefacts.
- **`tracking.py`** — `CostTrackingRecord` (predicted cost at order time vs.
  realised slippage) and `CostErrorTracker`, exposing `mean_absolute_error`
  (overall or per strategy) and `weekly_mean_absolute_error` (bucketed by
  ISO week) so a weekly job can pull "how far off were we" without
  recomputing anything from raw fills.

Run tests:

```bash
python3 /home/claude/repo/_pyshim/run_tests.py <abs>/quant-infra/cost tests
```

## Deviations / scope notes

- `capacity.py` solves in closed form (the impact-cost formula is
  monotonic and invertible) rather than by numerical search — the spec
  allowed either; closed form is exact and has no convergence failure
  mode to fall back from.
- **Documented gap: calibration is untested against real fills.**
  `calibrate_impact_coefficient` is validated only against *synthetic*
  fills constructed from a known true coefficient plus small Gaussian
  noise (see `tests/test_calibration.py`) — there is no realised execution
  data in this environment to calibrate against. Production calibration
  is blocked pending a live fills feed; until then every strategy should
  expect `calibrated=False` and the conservative default coefficient.
- **Documented gap: the "weekly" cadence and "no strategy funded past
  capacity" enforcement are not wired to a scheduler or a funding
  gate.** `tracking.py` supplies the aggregation logic a weekly job would
  call; `capacity.py` supplies the number a funding decision would check
  against. Actually running that job on a schedule, and actually blocking
  funding past `estimate_capacity`'s result, are integration points left
  to the caller (e.g. `quant-infra/orch/`'s scheduler for the cadence, and
  `quant-infra/alloc/solve.py`'s per-strategy cap for the funding gate) —
  out of scope for this pure-logic pass.

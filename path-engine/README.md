# PATH — path-dependent pricing and first-passage engine

Simulates thousands of possible price paths for an underlying and prices
instruments whose payoff depends on the whole path rather than only the
final price — Asians, barriers, lookbacks, cliquets, autocallables,
American/Bermudan exercise. The same engine also gives us first-passage
probabilities (touch, time-to-touch, touch-then-recover), which is the part
that pays for the build even if we never trade an exotic: a risk-neutral
touch probability is a genuinely useful number on its own, decoupled from
pricing any specific instrument.

> **This is the only risk-neutral model in the stack.** A Monte Carlo price
> answers what an instrument is worth given no arbitrage, not what the
> market will do. A risk-neutral probability is not a forecast and **must
> never be fed into a forecasting model as though it were one.** Every
> price and probability this package produces is a Q-measure quantity —
> including the touch/first-passage numbers, including the historical
> bootstrap's "expected payoff" (see `pe/validation/model_comparison.py`,
> which is P-measure and is labeled as such precisely so it is never
> confused with the rest). If a number from this engine ever ends up as an
> input feature to WW-WATCH, RISK-01, or FEAT-02's forecasting models, it
> is being misused — those models predict what happens; this engine prices
> what a no-arbitrage argument says an instrument is worth *given* a model
> of how the underlying moves. Neither direction of confusion is safe.

Like `engine/` and `intra-exitus-engine/`, this is a **sealed, pure-Python
math package** — no web framework, no LLM, no shared state with any other
engine in this repo. It shares no code with `engine/` (equity
factors/scoring) or `intra-exitus-engine/` (entry/exit planning); the only
thing it has in common with them is the convention that every function is
fully typed and every number ships with an honest account of its own
uncertainty.

## The one hard rule this package enforces structurally

**A price is never returned without a standard error.** `pe.types.MonteCarloResult`
is the only object any pricing function returns, and its constructor
rejects a missing/negative standard error outright (NaN is allowed only
when `n_paths <= 1`, which nothing in this package actually does). There is
exactly one place in the codebase that computes a standard error
(`pe.engine.mc`) — every payoff and every model routes through it (or
`pe.engine.pricer.price_from_paths`, the thin discounting wrapper around
it), so "never a mean alone" isn't a convention anyone has to remember to
follow, it's the only path available.

## Build order — status

Following the spec's own priority: PATH-01 (buildable slice), then PATH-02
up to local vol, then the barrier/first-passage payoffs (PATH-03/04/06).
Everything past that (autocallable, American/LSM, cliquet, the
three-model-spread standing diagnostic) is genuinely optional and is
included here, but nothing downstream depends on it.

1. ✅ **PATH-01 (buildable slice) — vol surface representation + no-arbitrage
   checks.** `pe/surface/`: a `VolSurface` in (forward log-moneyness,
   total variance) coordinates; `check_calendar_arbitrage` (total variance
   non-decreasing in T at fixed k) and `check_butterfly_arbitrage` (the
   Durrleman/Gatheral-Jacquier condition on the smile, `durrleman_g`) as
   pure functions on a grid or an analytic parameterization. **BLOCKED:**
   fitting a surface to a real, live options chain — there is no
   options-data vendor wired into this sandbox (the same gap that blocks
   real prices elsewhere in this repo; see `engine/README.md`'s Tiingo
   note). What's built here is everything *except* the network call: feed
   `VolSurface.from_grid`/`from_parametric` a chain-fitted grid whenever
   one exists, and every downstream piece (local vol, arbitrage checks)
   is already wired to consume it.
2. ✅ **PATH-02 — simulation engines**, validated in the order the spec asks
   for: GBM (closed-form-checkable baseline) → local vol via Dupire
   (calibrated to reproduce its own input surface *exactly*, by
   construction — see below) → Heston with Andersen's QE discretization
   (`pe/engine/heston.py`, **not** Euler). `pe/engine/bootstrap.py` adds a
   historical block-bootstrap path source (PATH-06) for model comparison —
   explicitly P-measure, never priced as if it were Q-measure.
3. ✅ **PATH-03 — payoff library.** `pe/payoffs/`: Asian (arithmetic +
   geometric, fixed + floating strike), barrier (all 8
   up/down × in/out × call/put combinations, with the Brownian-bridge
   discrete-monitoring correction PATH-04 calls for), lookback
   (fixed/floating), cliquet/forward-start (basic), autocallable (basic —
   see its own docstring for exactly what's simplified), American/Bermudan
   via Longstaff-Schwartz, and first-passage/touch as its own payoff family.
4. ✅ **PATH-04 — variance reduction.** Antithetic variates on by default;
   a control variate using the analytic geometric-Asian closed form
   (Kemna & Vorst 1990) to control the arithmetic Asian; Sobol + Brownian
   bridge for low-discrepancy path generation (`scipy.stats.qmc.Sobol` is
   available in this environment and is used — see "What's genuinely
   simplified" below for the one honest gap in it); common random numbers
   via explicit `SeedSequence` stream-splitting
   (`pe.engine.random_streams.spawn_streams`); the Brownian-bridge
   conditional-crossing correction for discretely-monitored barriers *and*
   touch probabilities.
5. ✅ **PATH-06 — validation, as actual automated tests.** European call vs
   Black-Scholes, geometric Asian vs Kemna-Vorst, continuous barrier vs
   Reiner-Rubinstein, put-call parity within MC error, local-vol
   self-repricing, a log-log convergence-rate fit, point-in-time
   determinism, and the three-model-spread standing diagnostic
   (`pe/validation/model_comparison.py`). 77 tests, all green — see
   "Validated numbers" below for the actual figures, not just "it passed."
6. ⬜ **PATH-07 — wiring into WW-WATCH / RISK-01 / FEAT-02.** Described
   below, not built — this package is deliberately self-contained pure
   math with no website TS seam, per its build brief.

## Layout

```
path-engine/
  pe/
    types.py           # MonteCarloResult — the only pricing return type
    surface/            # PATH-01: VolSurface, no-arbitrage checks, SVI generator
      surface.py
      arbitrage.py
      svi.py
    engine/              # PATH-02: simulation models + RNG infrastructure
      random_streams.py  # CRN, antithetic pairing, Sobol+bridge
      gbm.py              # PATH-02a
      localvol.py         # PATH-02b: Dupire
      heston.py            # PATH-02c: Andersen QE
      bootstrap.py          # PATH-06: historical block bootstrap (P-measure)
      mc.py                  # the only place a standard error is computed
      pricer.py               # payoff -> discount -> MonteCarloResult
    payoffs/             # PATH-03: pure path -> payoff functions
      asian.py, barrier.py, lookback.py, cliquet.py,
      autocallable.py, american.py, touch.py, closed_form.py
    validation/          # PATH-06: reusable validation helpers
      convergence.py, model_comparison.py
  tests/                 # 77 tests across 16 files, run via run_tests.py
```

## Validated numbers (from this build's own test run)

These are the actual figures produced by `tests/`, not aspirational
targets — every tolerance in the test suite is a multiple of the
*reported* Monte Carlo standard error, never a bare magic number, so a
regression that changes these figures meaningfully will fail the suite.

| Check | Result |
|---|---|
| GBM European call vs Black-Scholes (200k paths, antithetic) | MC 6.07621 ± 0.02115 vs BS 6.07640 — gap 0.00019, **0.01 SE** |
| Geometric Asian vs Kemna-Vorst closed form | within 4σ (see `tests/test_geometric_asian.py`) |
| Down-and-out call, **naive discrete-monitoring** barrier vs continuous Reiner-Rubinstein | gap **0.524** (naive overprices the knockout by ~15 SE — discrete monitoring under-detects knockouts, as expected) |
| Same instrument, same paths, **Brownian-bridge corrected** | gap **0.00343**, ~0.13 SE — a >150x reduction in bias from one conditional-expectation correction |
| Heston variance path, Feller-violating params (2κθ/ξ² = 0.33) | **QE: 0/30 seeds ever negative. Naive Euler: 30/30 seeds go negative.** |
| Local vol self-repricing (ATM + two off-ATM strikes) | within 4.5σ of the surface's own BS-implied price at every strike tested |
| Convergence slope (log SE vs log N, plain and antithetic MC) | both fits land in (-0.65, -0.35), bracketing the theoretical -0.5 |

## What's genuinely simplified (read before trusting a number)

- **Heston QE without the martingale correction.** `pe/engine/heston.py`
  implements Andersen (2008)'s base moment-matched drift (his eq. 33), not
  his Section 4.3 martingale-correction refinement. The base scheme passed
  every test here (including `E[S_T] = S0` at `r=q`, within MC error at
  400k paths), but a book trading deep, long-dated Heston exotics at
  extreme parameter combinations would want that refinement. Noted in the
  module docstring, not silently assumed.
- **Sobol dimension cap, not a fallback in this run.** `scipy.stats.qmc.Sobol`
  IS available and IS used by default in this environment (checked at
  import time) — this is not the degraded path. What's honestly capped is
  dimension: above `MAX_SOBOL_DIM` (1000) steps, or if Sobol construction
  raises for any reason, `pe.engine.random_streams.normal_increments`
  falls back to plain `numpy.random.Generator` pseudo-random draws and
  says so in its returned `info` dict (`used_sobol=False`) rather than
  silently claiming QMC quality it didn't deliver — both paths are tested
  (`tests/test_random_streams.py`).
- **American/Bermudan via Longstaff-Schwartz carries the well-known
  in-sample upward bias**, and the bias grows with the polynomial basis's
  degree at fixed path count (Longstaff & Schwartz 2001; Broadie &
  Glasserman 1997) — checked directly in `tests/test_american_lsm.py`
  (degree-9 basis priced at or above degree-1 on average, across 5
  independent path sets). The standard fix (freeze regression coefficients
  from a separate training simulation, price on fresh out-of-sample paths)
  is not implemented.
- **Autocallable is a genuinely basic single-underlying structure**: no
  coupon "memory" for missed calls, no worst-of basket, continuous
  (grid-step) knock-in monitoring rather than a separately-configurable
  schedule. See `pe/payoffs/autocallable.py`'s docstring for the exact
  mechanics implemented.
- **Lookback has no closed-form validation.** Unlike Asian/barrier, this
  package does not implement the Goldman-Sosin-Gatto continuous-lookback
  formula; `tests/test_lookback.py` checks structural bounds (a floating
  lookback dominates the corresponding vanilla) instead of an exact
  closed-form match. Honest gap, not hidden.
- **Cliquet is the "basic version"** the spec asks for: a globally
  floored/capped sum of locally floored/capped simple returns between
  configurable reset dates. No path-dependent notional resets, no
  multi-asset basket cliquets.
- **Grid-backed local vol needed a real numerical fix, worth knowing
  about**: `VolSurface`'s grid interpolation is piecewise-linear in
  log-moneyness, which has a genuine kink (unbounded second derivative
  under naive finite-differencing) at every grid node. Differentiating it
  with an arbitrary small bump size — the obvious first thing to try —
  diverges instead of converging as the bump shrinks, and produced a
  measurable (~5%) mispricing bias in early testing of this build.
  `pe/engine/localvol.py` fixes this by differentiating the *exact* same
  piecewise-linear object the surface itself uses for pricing (grid-node
  derivatives via `np.gradient`, interpolated the same way `total_variance`
  interpolates values, with an exact closed-form slope across the
  piecewise-linear T dimension) rather than bumping an arbitrary point.
  Left in the docstring in detail because it's a mistake worth not
  repeating elsewhere in this codebase.

## How this wires into WW-WATCH / RISK-01 / FEAT-02 (PATH-07, described not built)

This package is intentionally self-contained pure math with no website TS
seam — same posture as `engine/`'s Python/TypeScript split, one level more
sealed. If/when it's wired up, the shape would mirror how
`intra-exitus-engine/` hands off to the website: write one JSON export per
run, read by a single narrow bridge, nothing else in the app aware this
engine exists. Conceptually:

- **RISK-01** (portfolio/position risk) is the natural consumer of the
  first-passage payoffs: a touch probability or expected-time-to-touch on
  a position's stop level, computed under whatever vol model RISK-01
  already trusts for that name, is a direct input to a risk budget — this
  is the "pays for the build even without trading an exotic" use case the
  spec calls out. RISK-01 would supply `(S0, r, q, T, level)` and a choice
  of model (flat vol via `pe.engine.gbm`, or a calibrated surface via
  `pe.engine.localvol` for names where PATH-01's chain-fitting gap is
  eventually closed), and this package hands back a `MonteCarloResult` —
  RISK-01 decides what to do with the probability, this package never
  touches position sizing or thresholds itself.
- **WW-WATCH** (whatever surface/monitoring layer that name covers in this
  repo) would consume the **three-model spread**
  (`pe.validation.model_comparison.three_model_spread`) as a standing
  model-risk indicator on any path-dependent instrument WW-WATCH is
  tracking: a widening local-vol/Heston spread on the same instrument is a
  signal that the two models' assumptions about joint path behavior are
  diverging, independent of whether either model's vanilla-option fit has
  changed. This is a diagnostic feed, not a trade signal by itself.
- **FEAT-02** (feature engineering, by naming convention with `engine/features/`)
  is exactly the place the boundary warning at the top of this README is
  aimed at: this package's outputs are Q-measure quantities and must
  **not** become a feature in a forecasting model that treats them as
  P-measure information. The one place P-measure and Q-measure numbers
  ever sit side by side in this package is
  `pe.validation.model_comparison.ThreeModelSpread`, and its
  `historical_bootstrap` leg is labeled `meta['measure'] = 'P'` with an
  explicit warning string specifically so an integration downstream cannot
  reach for it by accident and mistake it for the two Q-measure legs next
  to it.

None of this wiring exists yet — no export writer, no bridge, no JSON
schema. Building it is a natural next step once there's an actual
consumer; describing it here is meant to make that a five-minute exercise
rather than a design discussion when the time comes.

## Running the tests

```bash
python3 /path/to/_pyshim/run_tests.py /path/to/path-engine tests
```

No network access, no external services — every test is self-contained
synthetic data (a hand-built or SVI-generated surface, simulated paths) or
a closed-form reference computed in the test file itself. 77 tests, 16
files, all green as of this build.

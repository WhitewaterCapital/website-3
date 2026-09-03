# WW-CHAOS — the chaos engine

Finds and trades the alpha that appears when markets stop behaving normally.
Detect the dislocation, classify it, forecast the short-horizon path, and show
it on screen while it happens.

This engine is its own world. It shares **no code and no state** with the
Incepta equity engine (`../engine/`), the Intra/Exitus planner
(`../intra-exitus-engine/`), or any other model in this repository. The only
way it ever touches the website is the same way those engines do: it writes
one JSON document to `public/data/chaos/latest.json`, and a single TypeScript
bridge (`src/lib/chaos.ts`) reads it. Nothing else in the app knows this
engine exists — it is not wired into any page or into
`src/lib/models/registry.ts`.

## What this is, and is not

**What this is:** a research model that (1) detects when a market has
stopped behaving normally on an intraday basis, using eight independently
computed, documented signals; (2) classifies the dislocation through an
explicit hysteresis state machine (`calm → stressed → dislocated →
cascade`); (3) forecasts the short-horizon directional path with a
calibrated, abstention-aware classifier; and (4) reports gross- and
net-of-cost performance side by side, at execution assumptions built to be
unflattering rather than flattering to the model.

**What this is not — stated plainly, because it is the framing the doc asks
to be baked in everywhere:**

> This is not high frequency trading. There is no colocated infrastructure,
> no microsecond order-book access, and nothing here claims latency edge.
> What is reachable is intraday dislocation capture on a 1 to 15 minute
> horizon.

That sentence (or the equivalent `DISCLAIMER` string in `chaos/export.py`)
is meant to appear everywhere this engine's output reaches a human: the
export JSON, this README, and every module docstring that could otherwise be
misread as claiming HFT-grade capability. It is not investment advice, and
nothing here has been validated as a live, tradeable alpha model — it is
research/paper output on synthetic data (see "Known simplifications" below).

## Design

Four sealed layers, mirroring the discipline of the other engines in this
repo:

1. **CHAOS-01 — the state engine** (`chaos/state.py`). Eight components, each
   its own documented, independently unit-tested function operating on plain
   pandas OHLCV bar data:
   - **Volatility ratio** — realised vol over fast (5-bar) windows vs.
     trailing 60-bar realised vol. ~1.0 in calm markets, rises sharply on
     detachment.
   - **Volume surprise** — a volume z-score against the *same minute-of-day*
     across trailing sessions, so the ordinary open/close U-shaped intraday
     volume curve is controlled for rather than misread as "surprising"
     every day.
   - **Range/spread deterioration** — high-low range relative to
     close-to-close move. The spread half of this component is **optional**:
     it requires real bid/ask quote data, which does not exist in this
     repo's synthetic bars or in any live feed wired in here, and is
     reported `available: false` rather than approximated.
   - **Cross-sectional dispersion** — std, across a universe, of each
     name's trailing-interval return.
   - **Correlation shift** — short-window average pairwise correlation minus
     its own trailing level; a classic "everything starts moving together"
     stress signature.
   - **Order flow imbalance** — signed volume from an approximate tick rule
     when quotes are unavailable (a bar-level, close-vs-prior-close
     APPROXIMATION of the classic Lee & Ready tick rule, labelled
     `tick_rule_bar_close`), or a real quote-midpoint comparison
     (`quote_midpoint`) when quote data is supplied.
   - **Jump indicator** — bipower variation vs. realised variance
     (Barndorff-Nielsen & Shephard), implemented from scratch with numpy, to
     separate genuine discontinuity from elevated-but-continuous diffusion.
   - **Novelty aggregate** — external-input-only. There is no real news
     pipeline in this repository; this component defaults to
     `available: false` and never fabricates a novelty score.

   The eight component scores combine into a single **chaos index in
   [0, 1]** (an unavailable component is dropped from both numerator and
   denominator — weights renormalise over what's actually available, never
   imputed with a neutral fill), which then drives an explicit **state
   machine with hysteresis and a minimum dwell time**: escalating to a more
   severe state requires crossing an upper threshold; de-escalating requires
   dropping below a *distinctly lower* threshold; and no state change (either
   direction) is allowed until `min_dwell_bars` have elapsed since the last
   one. This is what makes it hysteresis rather than a threshold snapshot —
   see `tests/test_state.py::test_hysteresis_prevents_flapping` and
   `::test_determinism`.

2. **CHAOS-02 — the directional model** (`chaos/directional.py`). See
   "Known simplifications" below — this is an explicitly simplified stand-in
   for the design's real causal TCN. Strictly causal, lagged-only features;
   a calibrated (isotonic, held-out-fold) gradient-boosted classifier;
   a bagged-ensemble uncertainty proxy; and a documented confidence-band
   abstention gate (plus an optional meta-labelling gate).

3. **CHAOS-03 — cost-aware execution assumptions** (`chaos/execution.py`).
   Every simulated fill happens at the **far side of the spread plus
   modelled impact** — never mid-price, and the assumed spread widens as a
   function of the prevailing chaos state (spreads are widest exactly when
   this model wants to trade). A minimum holding period and a
   maximum-turnover-per-session cap are both configurable and both
   reported; every result is gross-vs-net side by side; and a
   **cost-sensitivity table** (1x/2x/3x modelled cost) is a first-class,
   genuinely computed output — see "Known simplifications" / test results
   below for what it actually showed on the synthetic strategy used to
   exercise it.

4. **Export** (`chaos/export.py`). Runs the full CHAOS-01 → CHAOS-02
   pipeline in **synthetic-demo mode** (there is no live intraday data feed
   wired into this repository) over a small illustrative watchlist, and
   writes the one JSON contract the website reads.

## Layout

```
chaos-engine/
  chaos/
    config.py       # thresholds, windows, watchlist, execution assumptions
    state.py         # CHAOS-01 — eight components + chaos index + state machine
    directional.py   # CHAOS-02 — calibrated GBM classifier, causal features, abstention
    execution.py      # CHAOS-03 — far-side-of-spread fills, cost sensitivity
    export.py         # website handoff JSON (synthetic-demo mode)
  exports/            # engine-side copy of the export (gitignored upstream convention;
                       # committed here alongside public/data/chaos/latest.json)
  tests/              # the full test suite (see below)
  requirements.txt
  README.md
```

The website side lives outside this directory, in `src/lib/models/
chaos-export.ts` (the TypeScript mirror of the export schema) and
`src/lib/chaos.ts` (`getChaosExport()`, the single read seam — same pattern
as `src/lib/aurora.ts` / `src/lib/intra-exitus.ts`).

## Quickstart

```bash
cd chaos-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                      # full suite, no network needed — all synthetic data

python3 -m chaos.export         # writes public/data/chaos/latest.json
                                 # and chaos-engine/exports/latest.json
```

(In the sandbox this was built in, tests are run instead via the repo's
offline pytest-compatible shim: `python3 _pyshim/run_tests.py chaos-engine
tests`.)

## Known simplifications

Stated here, in the module docstrings, and in the `disclaimer` field of
every export — nowhere is this quietly glossed over:

1. **CHAOS-02 is a classifier, not a TCN.** The design calls for a causal
   dilated temporal convolutional network. This sandbox has no deep-learning
   framework installed (no torch, no tensorflow) and no network access to
   install one. Rather than fake a TCN or skip CHAOS-02 entirely,
   `chaos/directional.py` substitutes a **calibrated
   `GradientBoostingClassifier`** trained on the same kind of lagged,
   causal-only features a TCN's receptive field would see, calibrated via
   `CalibratedClassifierCV` (isotonic) on a held-out fold, with a bagged-
   ensemble uncertainty proxy standing in for a real predictive quantile
   head. This is a stand-in, not an equivalent model — a TCN can learn
   temporal structure a tree ensemble over hand-built lag features cannot.
   The module's public surface (`fit`/`predict`, `probability`,
   `uncertainty`, `abstain`) is written so a real TCN could be swapped in
   later without changing anything downstream.

2. **No real quote/spread data.** `range_deterioration`'s spread-in-bps half
   and `order_flow_imbalance`'s quote-midpoint method both require bid/ask
   quotes. None exist in this repo's synthetic OHLCV bars, and no live quote
   feed is wired in anywhere in this repository. Both report
   `available: false` (or fall back to a clearly labelled bar-level
   APPROXIMATION for order flow) rather than inventing a number.

3. **No real news/novelty feed.** The novelty aggregate is accepted only as
   an optional external input. There is no news-clustering or event-
   detection pipeline anywhere in this codebase; `novelty_aggregate` returns
   `available: false` whenever nothing is supplied, and never fabricates a
   value.

4. **Synthetic-demo data end to end.** There is no live intraday market data
   feed wired into this repository. `chaos/export.py` generates a
   deterministic synthetic multi-session intraday panel (a repeating
   U-shaped volume curve, a mean-reverting price path with occasional
   genuine jumps) so the full pipeline and the JSON contract can be
   exercised honestly. The export's `provenance` field is stamped
   `"synthetic-demo"` accordingly. Swapping in a real feed only touches the
   bar-generation call site in `export.py` — nothing about CHAOS-01,
   CHAOS-02, or CHAOS-03 assumes synthetic data.

5. **Single chronological split, not purged walk-forward CV.** CHAOS-02's
   `fit()` uses one chronological train/calibration split (calibration data
   strictly later in time). Given overlapping-horizon labels, a rigorous
   evaluation would use purged + embargoed cross-validation (as
   `intra-exitus-engine/ie/regime/` does). That splitter was judged out of
   scope for this explicitly-simplified stand-in; see the module docstring
   in `chaos/directional.py`.

## Test suite

`chaos-engine/tests/` covers all three layers plus the export contract:

- `test_state.py` — all eight CHAOS-01 components individually, the
  renormalising combination, and the state machine's determinism and
  hysteresis (replaying an identical series always reproduces an identical
  label sequence; a fixture that hovers right at a threshold does not
  oscillate faster than the configured minimum dwell time).
- `test_directional.py` — causal feature construction, a direct
  no-future-leakage proof (shuffling future rows leaves past predictions
  byte-identical), and a calibration-error test against a synthetic dataset
  with a **known** true generating probability.
- `test_execution.py` — far-side-of-spread fills that widen with chaos
  state, the minimum holding period, the turnover cap and its breach
  reporting, and the cost-sensitivity table computed on a synthetic
  strategy (not a hardcoded pass).
- `test_export.py` — the website handoff schema shape and honesty fields
  (every component's `available` flag present, `calibrated: true`, the
  disclaimer text).

Run: `python3 _pyshim/run_tests.py chaos-engine tests` from the repo's
`_pyshim` offline shim, or `pytest -q` from inside `chaos-engine/` with a
real pytest installed.

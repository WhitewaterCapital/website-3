# WW-GRAPH — engine

A **sealed graph-diffusion pairs model**. It builds a graph of how securities
relate, spreads each name's signal across that graph to get what its
neighbours implied it should have done, and treats the gap as the tradeable
residual. A large positive residual is a name that has run away from its
group. A large negative one is a name left behind.

This engine is its own world. It shares **no code and no state** with the
Incepta equity engine (`../engine/`), Intra/Exitus (`../intra-exitus-engine/`),
or any other model — the OU/half-life math in `ge/reversion.py`, for example,
is the same math and the same honesty gate as
`intra-exitus-engine/ie/levels/ou.py`, copied on purpose rather than imported.
The only way this ever touches the website is the same way the other engines
do: it writes one JSON document to `public/data/graph/latest.json`, and a
single TypeScript bridge (`src/lib/graph.ts`) reads it. Nothing else in the
app knows this engine exists — it is not wired into any page or into
`src/lib/models/registry.ts`.

## Design (v1)

Five sealed layers, run in this order:

1. **Graph construction** (`ge/graph/construct.py`) — two edge SOURCES, each
   its own inspectable matrix: (a) rolling return correlation, shrunk toward a
   structured target via `sklearn.covariance.LedoitWolf` (signed — an
   anti-correlated pair is a real edge, not a zero); (b) a same-sector
   structural prior. Combined with FIXED, documented weights (`W_CORR=0.85`,
   `W_SECTOR=0.15` in `ge/config.py`) — never learned.
2. **Sparsify** (`ge/graph/construct.py::sparsify_top_k`) — keep the
   strongest `TOP_K_EDGES` (10-20, configurable) per node. A dense correlation
   matrix on real equities is dominated by the market factor, so a fully
   connected diffusion mostly just diffuses every name toward the
   cross-sectional average — sparsifying forces the graph to encode specific
   relationships (sector-mates, close substitutes) instead.
3. **Diffusion** (`ge/graph/diffusion.py`) — a symmetric normalized Laplacian
   gives the textbook stability certificate (eigenvalues bounded in
   `[-1, 1]`/`[0, 2]`); the actual signal propagation uses a SIGNED,
   row-normalized operator (so anti-correlated neighbours pull the implied
   value the other way) iterated via **sparse matrix-vector products**
   (`scipy.sparse`), never a matrix inverse. Stability for the signed operator
   follows from `||alpha*P||_inf = alpha < 1` — a contraction mapping for any
   `alpha` in `[0, 1)`, verified both by eigenvalue bound and by empirical
   convergence in `tests/test_diffusion.py`.
4. **Residual** (`ge/residual.py`) — `residual = signal - diffused`, where
   `signal` is a cross-sectionally z-scored trailing 5-day return (fast,
   PIT, comparable across names — see `ge/features/signal.py`'s docstring for
   why not something slower). Standardized cross-sectionally into a z-score,
   then sector-neutralized (same-sector mean subtracted) so a sector-wide tilt
   isn't mistaken for a name-specific divergence.
5. **Half-life** (`ge/reversion.py`) — an OU/AR(1) fit on the residual's OWN
   time series, gated by a Dickey-Fuller significance test (same
   `DF_CRIT_5PCT = -2.86` as Intra/Exitus). A half-life is reported **only**
   when the reversion is statistically significant; otherwise the model
   abstains rather than invent a number.
6. **Backtest** (`ge/backtest.py`) — a self-contained, cost-aware long/short
   quantile backtest of the (sign-flipped, "fade") residual as a standalone
   signal at a 1-10 day holding horizon, charging transaction costs on
   turnover.

## The "done when" bar

Per the model spec: *"the residual measurably mean reverts... confirm it is
materially shorter than the proposed holding period. If residuals do not
revert on our universe the graph is wrong and the model does not ship."*

`tests/test_reversion_honesty.py` is that gate as an actual test: a synthetic
panel with a KNOWN mean-reverting driver injected into one name must produce a
short, significant half-life; a synthetic panel with a KNOWN non-reverting
driver (a true random walk) must NOT. Both directions are checked, because an
estimator that always says "yes, it reverts" is exactly as useless as one that
never does — see "Current status" below for the honest numbers this actually
produces.

## Data

**No live price or sector data is wired up in this sandbox.** Every number
this engine can currently produce is built from `ge/synthetic.py` — a
deterministic synthetic universe/return panel — and is labeled
`"data_provenance": "synthetic-demo"` everywhere it surfaces (the export JSON,
and the TypeScript contract in `src/lib/models/graph-export.ts`). Wiring a
real price adapter (same shape as
`intra-exitus-engine/ie/adapters/prices_tiingo.py`) and a real sector-mapping
source is the natural next step before this ever touches real capital.

> **Not investment advice.** Research/paper output only, and — in this
> sandbox — built entirely on synthetic data. Not a validated alpha model.

## Layout

```
graph-engine/
  ge/
    config.py           # every fixed, documented constant
    synthetic.py         # deterministic synthetic OHLCV/return panels
    features/
      signal.py          # PIT signal: cross-sectionally z-scored 5-day return
    graph/
      construct.py        # correlation-shrunk + sector-prior graph, sparsify
      diffusion.py         # normalized Laplacian + iterative signed diffusion
    residual.py          # actual - diffused, z-scored, sector-neutral
    reversion.py         # OU/AR(1) + Dickey-Fuller half-life (mirrors ie/levels/ou.py)
    backtest.py          # cost-aware long/short backtest of the residual
    pipeline.py          # orchestration: prices -> signal -> graph -> residual, over time
    export.py            # write the handoff JSON
  exports/               # engine-side copy of the export (gitignored upstream)
  data/                  # local caches (gitignored upstream; unused today)
  tests/                 # pytest — full suite, see below
```

## Quickstart

```bash
cd graph-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest -q                    # full test suite (synthetic, no network needed)
python -m ge.export          # writes public/data/graph/latest.json (synthetic-demo)
```

## Current status / limitations

- **No real data adapter.** See "Data" above. This is the single biggest gap
  before this could ever inform a real position.
- **Only one edge source beyond correlation is implemented: a same-sector
  prior.** Real ETF-holdings-weighted edges (two names both heavily held by
  the same basket), supply-chain/customer-supplier edges, and text-similarity
  edges (10-K/earnings-call similarity) are all natural, higher-signal
  extensions to the graph — **not implemented here** because none of that
  data is available in this sandbox. This is a deliberate, documented
  extension point (add a new edge-source matrix in `ge/graph/construct.py`,
  give it its own fixed weight in `ge/config.py`), not a silent gap.
- **The Dickey-Fuller reversion gate is noisier on this residual than on a
  clean price series.** `ge/reversion.py`'s math and honesty rule are
  identical to `ie/levels/ou.py`'s, which achieves a ~5-15% false-positive
  rate on a true random walk (see `tests/test_reversion.py`). Applied to the
  graph-diffusion residual — which is itself an ESTIMATE with real estimation
  noise from the correlation graph and the diffusion step, not a directly
  observed series — the empirical false-positive rate on a true random-walk
  driver measured in `tests/test_reversion_honesty.py` is meaningfully
  higher, roughly 30-40% on a 60-name synthetic universe at 400 days of
  history. The positive-control power is strong (roughly 90-100% detection of
  a genuinely reverting driver at a similar signal-to-noise ratio). This is
  reported honestly rather than tuned away: a real deployment should treat a
  borderline half-life (DF stat just past -2.86) with real skepticism, and a
  natural hardening step — flagged here, not built — is a stricter production
  threshold (e.g. -3.5) or a sub-window robustness check (does the same name
  show a significant half-life on multiple overlapping windows, not just one).
- **Short-horizon residuals revert fast, almost by construction.** The demo
  export (`python -m ge.export`) currently shows every synthetic name with a
  short, significant half-life. That is not a bug in the sparsification or
  the graph: a residual built from a 5-day return nets out most persistent
  structure by construction, so what's left over is dominated by fast,
  low-conviction noise — the same phenomenon behind the well-documented
  "short-term reversal" effect in real equities. It is exactly why the
  backtest (`ge/backtest.py`) charges realistic transaction costs before this
  is ever called tradeable: a residual that reverts in 2-3 days is easy to
  detect and easy to erode with costs and slippage. A longer signal window
  (`SIGNAL_WINDOW` in `ge/config.py`) is the natural knob to trade detection
  speed for a cleaner, more tradeable half-life; it is a config change, not a
  design change.
- **Graph re-estimation cadence is a fixed constant** (`refresh_every` in
  `PipelineConfig`, default every 5 bars), not adaptively triggered by, e.g.,
  a detected regime shift. Simple and testable; a smarter refresh trigger is
  a future extension, not a current feature.

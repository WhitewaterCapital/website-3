# WW-FACTOR — engine

A **sealed Fama-French factor-exposure model**. For one ticker at a time, it
regresses the ticker's trailing daily excess return (return minus the
risk-free rate) on six well-known return factors — Mkt-RF, SMB, HML, RMW,
CMA, and Mom — and reports the fitted beta on each one, plus the
regression's R² and alpha. This is a genuinely different lens than every
other model in this repo: Distresse judges an idea, Entry & Exit sizes a
level, WW-Weekly ranks a cross-section, Incepta reads fundamentals, WW-GRAPH
reads a graph-diffusion residual — none of them answer "is this ticker's
return pattern driven by market beta, a size tilt, a value tilt, a
profitability tilt, an investment tilt, or a momentum tilt". This engine
answers exactly that, and nothing else.

This engine is its own world. It shares **no code and no state** with the
Incepta equity engine (`../engine/`), WW-GRAPH (`../graph-engine/`),
WW-WEEKLY (`../weekly-engine/`), Intra/Exitus (`../intra-exitus-engine/`),
or any other model — `fac/adapters/prices_tiingo.py` is a self-contained
copy of the same Tiingo adapter pattern every other engine in this repo
copies independently, not imported from any of them. The only way this ever
touches the website is the same way the other engines do: it writes one JSON
document to `public/data/factor/latest.json`, and a single TypeScript bridge
(`src/lib/factor.ts`) reads it. It is deliberately **not** wired into
`src/lib/models/conviction.ts`'s composite score — see "Why this is not in
conviction.ts" below.

## What it computes

For each covered ticker, over a trailing 252-trading-day window (~1 calendar
year — see `fac/config.py`'s `WINDOW_TRADING_DAYS` comment for why):

```
excess_return_t = alpha + beta_mkt * MktRF_t + beta_smb * SMB_t
                            + beta_hml * HML_t + beta_rmw * RMW_t
                            + beta_cma * CMA_t + beta_mom * Mom_t + error_t
```

fit by closed-form OLS (`beta_hat = (X'X)^-1 X'y`, pure numpy — see
`fac/regression.py`'s module docstring for why not statsmodels/sklearn),
where `excess_return_t = ticker_return_t - RF_t`. The output per ticker is
every factor's beta, its standard error and t-stat (with a `significant`
flag at the standard 5% two-sided critical value), the regression's R², and
the fitted alpha (daily and annualized).

## The honesty gate

Per this repo's convention (see `graph-engine/ge/reversion.py`'s
Dickey-Fuller gate, the direct model for this engine's own gate in
`fac/regression.py::fit_factor_exposure`): a beta is published **only**
when both of the following hold —

1. **Enough overlapping history.** At least `MIN_OBS` (126 trading days,
   half the regression window — see `fac/config.py` for the full
   rationale) of dates where BOTH a Tiingo price and a French factor row
   exist. A recently-listed ticker, a thinly-covered one, or one with a
   large data gap gets `"confidence": "insufficient_history"` and
   `"betas": null` — never a beta fit on a truncated, unrepresentative
   window.
2. **A numerically well-posed regression.** The design matrix's condition
   number must be below `MAX_CONDITION_NUMBER` (1e10), and the ticker's own
   excess return must have nonzero variance over the window. A ticker that
   fails either check gets `"confidence": "degenerate"` and `"betas": null`
   — this is rare on real large-cap equities but real on a halted/flat
   security or a factor panel with a data-quality problem.

This gate is applied by the exact same function
(`regression.fit_factor_exposure`) whether the inputs came from real
Tiingo/French data or the synthetic-demo generator — see `export.py`'s
module docstring, `_export_row`.

Individual per-factor `significant` flags are reported ALONGSIDE every beta,
never used to hide it — unlike a single "does this revert" boolean (WW-
GRAPH's half-life), a factor beta is a standard descriptive quantity that
every textbook factor-exposure table reports next to its own significance,
and hiding an insignificant beta would delete real information (e.g. "this
name currently has ~zero measurable exposure to CMA") rather than protect
against a fabricated one. See `fac/config.py`'s `BETA_T_CRIT` comment.

## Data

**Prices**: `fac/adapters/prices_tiingo.py`, the same free, no-signup Tiingo
daily-price adapter pattern every other engine in this repo uses
independently, gated on `TIINGO_API_KEY` in `os.environ` (the same free key
intra-exitus-engine, Incepta, WW-GRAPH, and WW-WEEKLY already use).

**Factors**: `fac/adapters/french_factors.py`, a brand-new adapter for the
free, no-signup, monthly-updated
[Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html)
— no API key of any kind. It downloads the "Fama/French 5 Factors (2x3)
[Daily]" and "Momentum Factor (Mom) [Daily]" zip files, verified live
(2026-09, via WebFetch against the library's own download page and a GitHub
mirror of the real 5-factor daily CSV) for:

* The exact current download URLs (`fac/config.py`'s
  `FRENCH_5_FACTOR_DAILY_URL` / `FRENCH_MOMENTUM_DAILY_URL`).
* The exact CSV format's idiosyncrasies: 1-3 free-text banner lines before
  the real header row, values published as PERCENT (divided by 100 here),
  and a lower-granularity trailing section in at least the MONTHLY files
  (confirmed via a real tutorial's description of the monthly file, and via
  `pandas-datareader`'s actual production parser, which distinguishes
  daily/monthly/annual chunks purely by the magnitude of the leading date
  integer). The parser in `french_factors.py` uses the same discriminator
  pandas-datareader does — a data row is kept only if its date is an
  8-digit `YYYYMMDD` — see that module's docstring for the full citation
  trail and for the one thing this sandbox could NOT confirm directly (see
  "Current status" below).

Downloaded factor files are cached locally under `factor-engine/data/cache/`
with a documented 1-day TTL (`FRENCH_CACHE_TTL_SECONDS`) — the library
updates roughly monthly, so daily re-fetching would only hammer a free,
unauthenticated server for no benefit.

`export.py::build_export()` is gated on `TIINGO_API_KEY` exactly like every
other engine's export:

* **Key set** — `build_live_export()` fetches real daily closes (Tiingo) for
  a small fixed demo universe (`fac.config.DEFAULT_LIVE_UNIVERSE`) and the
  real daily factor panel (French Data Library, no key needed), and runs
  them through the SAME, unmodified `regression.fit_factor_exposure` used
  below — only the data source changes, not the model math — labeled
  `"data_provenance": "live"`.
* **Key unset** — a deterministic synthetic universe/price/factor panel from
  `fac/synthetic.py`, labeled `"data_provenance": "synthetic-demo"`. The two
  are never mixed within one export.

> **Not investment advice.** Research/paper output only, and — in this
> sandbox — built entirely on synthetic data. Not a validated alpha model.
> A factor beta is descriptive risk context, never a directional call.

## Why a small fixed universe, not "any ticker on demand"

Every model in this repo reaches the website the same way: a Python process
writes one static JSON file, and a Next.js route/lib function reads it (see
`src/lib/weekly.ts`, `src/lib/graph.ts`) — there is no live invocation of
this engine from the Node process. A truly general "type any ticker, get its
factor exposure" experience would need an on-demand compute path (a job
queue, or an API route shelling out to Python per request), which is
out of scope for this repo's existing export pattern. Today's export covers
`fac.config.DEFAULT_LIVE_UNIVERSE` (6 illustrative large caps); a ticker
outside that list shows the same honest "not in the research universe" state
`weekly-engine`'s WeeklyCard already shows for its own fixed universe. A real
on-demand deployment is a natural, flagged extension — not built here.

## Why this is not in `conviction.ts`

`src/lib/models/conviction.ts`'s composite score is a **directional/quality
read** — every slot's `score` is on a signed -100..100 "how bullish/bearish"
scale. A factor beta is not that: a market beta of 1.3 is not bullish or
bearish, it is a description of how much a name amplifies whatever the
market does either way; a negative momentum beta is not a sell signal, it is
a description of a style tilt. Forcing either into a signed directional
score would misrepresent what the number means, so this engine's export is
surfaced as its own descriptive panel in the Ticker Hub
(`src/components/panels/FactorPanel.tsx`) and is explicitly never passed to
`computeConviction` — see that panel's own top-of-file comment, which
states this in the code, not just here.

## Layout

```
factor-engine/
  fac/
    config.py            # every fixed, documented constant (window, gates, French URLs, cache TTL)
    regression.py          # closed-form OLS + the honesty gate (fit_factor_exposure)
    synthetic.py            # deterministic synthetic factor panel + ticker returns, known true betas
    adapters/
      prices_tiingo.py       # real Tiingo daily-price client, gated on TIINGO_API_KEY
      french_factors.py       # real Kenneth French Data Library client, no key needed
    export.py              # write the handoff JSON
  exports/               # engine-side copy of the export (gitignored)
  data/cache/            # local cache of downloaded French CSVs (gitignored)
  tests/                 # pytest — full suite, see below
```

## Quickstart

```bash
cd factor-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

pytest -q                    # full test suite (synthetic + mocked-Tiingo + mocked-French, no network needed)
python -m fac.export         # writes public/data/factor/latest.json (synthetic-demo)

# For a LIVE export instead: register free at https://www.tiingo.com, then
echo "TIINGO_API_KEY=your_token" > .env
python -m fac.export          # now writes data_provenance: "live" (French factors need no key at all)
```

## Current status / limitations

- **Live once `TIINGO_API_KEY` is set** (same free key every other engine in
  this repo already uses); falls back to `synthetic-demo` otherwise. The
  live path has been built and unit-tested against MOCKED Tiingo responses
  (`tests/test_prices_tiingo.py`) and a MOCKED French Data Library zip
  response built to match the library's documented real format
  (`tests/test_french_factors.py`), and against a fully mocked live export
  end to end (`tests/test_export.py`) — but **not yet run against either
  real API from this environment: this sandbox has no outbound network
  access at all** (confirmed dead here: even a direct `curl` to
  `mba.tuck.dartmouth.edu` returns a proxy-level `403`/`CONNECT tunnel
  failed`). The exact French Data Library download URLs and CSV-format
  idiosyncrasies documented in `french_factors.py` were verified via
  WebFetch/WebSearch against the live library page and a GitHub mirror of
  the real 5-factor daily file — i.e. researched, not guessed from
  training-data memory — but WebFetch could not confirm one specific detail
  end to end: whether the DAILY files (as opposed to the confirmed-documented
  MONTHLY files) ever carry a trailing lower-granularity section, because no
  tool available in this sandbox could retrieve and show the true tail of a
  real, current daily CSV. The parser defends against that case anyway (see
  `french_factors.py`'s module docstring, point 3) using the same
  date-width discriminator pandas-datareader's real production parser uses,
  so this is a documented, defended-against unknown, not a silent gap. The
  next real run (e.g. the scheduled GitHub Action, which has normal internet
  access) is the first true end-to-end verification of both the Tiingo and
  French Data Library fetches.
- **`DEFAULT_LIVE_UNIVERSE` (6 names) is illustrative, not survivorship-free
  or point-in-time**, same caveat as every other engine's Tiingo-backed
  universe in this repo — see `prices_tiingo.py`'s INTEGRITY NOTES.
- **No live-data run of the real regression has happened anywhere** — the
  betas shown in the demo export are fit against a KNOWN synthetic panel
  with injected true betas (`fac/synthetic.py`'s `DEMO_TRUE_BETAS`),
  specifically so `tests/test_regression.py` can check the recovered betas
  land close to the injected ones as a positive control. That is a
  correctness check on the OLS/gating code, not a claim about any real
  ticker's real factor exposure.
- **Momentum factor construction detail**: the momentum factor (`Mom`) is
  fetched from Ken French's SEPARATE daily momentum file and inner-joined
  onto the 5-factor daily panel by date (`french_factors.py::fetch_factor_panel`)
  — a date present in only one of the two files is dropped from the combined
  panel entirely, never forward-filled, consistent with this engine's
  "never fabricate a value for missing data" rule.
- **Fixed regression window (252 trading days), not adaptive.** A ticker
  whose true factor loadings changed recently (e.g. after a business-mix
  shift) will show a beta that blends the old and new regime for up to a
  year after the change. A shorter window would react faster but be noisier
  window-to-window; 252 is a fixed, documented, not-fit-to-data choice (see
  `fac/config.py`), not a claim that it is optimal for every name.

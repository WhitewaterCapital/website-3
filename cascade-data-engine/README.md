# WW-CASCADE-DATA — real ETF-holdings ingestion for WW-CASCADE

Feeds `quant-infra/cascade/pressure.py` (already-real, already-tested math —
see its own module docstring and `quant-infra/cascade/tests/`) with real
holdings for a small starter universe of liquid iShares funds, in the exact
shape `compute_pressure` expects. This is the data-plumbing half of the
"Cascade Network" build `PLATFORM_REBUILD_PLAN.md`'s Roadblocks left open —
see that doc's "Cascade Network" entries for the prior, honest "I can't
verify this endpoint exists from here" state this engine moves past.

## What's actually confirmed vs. what's still open (read this first)

**Confirmed real, this pass, via Anthropic's own WebFetch/WebSearch tooling
(a separate network path from either of this repo's own sandboxes — see
`cde/adapters/ishares_holdings.py`'s module docstring for the full
evidence trail):**
- iShares' public per-fund holdings CSV (`.../latest-holdings.csv`) is a
  real, live, no-API-key endpoint. Fetched three real funds (IVV, IWF, IWD)
  and got back real, internally-consistent, fund-specific current data
  (confirmed 2026-09-11/12 top holdings, weights, and shares outstanding —
  see the adapter docstring for the exact numbers).
- The confirmed column shape: `Ticker, Name, Sector, Asset Class, Market
  Value, Weight (%), Notional Value, Quantity, Price, Location, Exchange,
  Currency, FX Rate, Market Currency, Accrual Date`, plus fund-level
  shares-outstanding metadata ahead of the header row.

**Still NOT confirmed / genuinely open:**
- **This engine has never fetched that endpoint itself, from any sandbox it
  runs in.** Both this repo's cloud workspace and its on-device shell get
  an identical `403`/"policy denial" from their egress proxy the instant
  they try to reach `ishares.com` — re-confirmed this pass with a direct
  `curl`, same as the existing Tiingo/Alpha Vantage evidence in
  `PLATFORM_REBUILD_PLAN.md`. `IsharesHoldingsAdapter.get_holdings()` makes
  a REAL `urllib` call (unlike `fmp_calendar.py`/`alpha_vantage.py`, which
  never attempt one at all) — but it has only ever been exercised as far as
  that 403, never past it. Try it from your own machine.
- **`typical_volume` per constituent is not sourced anywhere in this pass.**
  This platform's existing Tiingo wiring (already used for prices
  elsewhere) is blocked from both sandboxes exactly like the holdings feed
  itself, so this specific gap can't be closed from here either way — it's
  a second, independent open item, not solved by fixing the holdings feed.
- **NAV per share is not in the holdings CSV at all.** Even once a real
  second day's shares-outstanding reading exists,
  `estimate_flow_from_shares_outstanding` needs a NAV to price the delta
  into dollars — this engine currently passes `nav_per_share=NaN`
  (honestly "not sourced", not a guessed price), so flow stays NaN on the
  live path even past day one, until a NAV source is wired up too. iShares'
  own product page does show NAV (confirmed in this pass's research) — it
  just isn't in the holdings CSV, so this is a second fetch to add, not
  designed here.

## Why the live gate is a flag, not a key

See `cde/config.py`'s module docstring: this endpoint needs no
authentication at all, so there is no key to check for. `CASCADE_LIVE_HOLDINGS=1`
in a gitignored `.env` is the explicit human opt-in, checked instead.

## Run it

```
cd cascade-data-engine
python -m cde.export
```

Writes `public/data/cascade/latest.json` (web-servable) and
`cascade-data-engine/exports/latest.json` (engine-side copy). Also appends
this run's per-fund shares-outstanding snapshot to
`cascade-data-engine/state/fund_snapshots.jsonl` (internal engine state,
not read by the website) — the NEXT day's live run, on a machine that can
actually reach `ishares.com`, will diff against it for a real flow
estimate.

- `CASCADE_LIVE_HOLDINGS` unset → deterministic synthetic-demo panel
  (`cde/synthetic.py`) — fully populated, non-NaN pressure numbers over
  this platform's own existing default 6-ticker universe, so there's
  something concrete to look at before the live path can produce anything.
- `CASCADE_LIVE_HOLDINGS=1` → real `IsharesHoldingsAdapter` calls for every
  fund in `cde/config.FUNDS`. If at least one fund's fetch succeeds, writes
  a `"data_provenance": "live"` export (any fund that failed is named in
  `skipped_funds`, not silently dropped). If EVERY fund fails, raises
  `LiveExportFailedError` instead of writing a "live"-labeled export built
  from nothing real — see `cde/export.py`'s module docstring.

## Tests

```
python -m unittest discover -s tests -v
```

23 tests, all passing, pure standard library plus this repo's existing
`pandas`/`numpy` (already installed — no `requirements.txt`, nothing new to
`pip install`; confirmed via `python3 -c "import pandas"` before assuming,
same discipline `earnings-engine/README.md` documents). Covers: the CSV
parser against a hand-built fixture matching the confirmed column shape,
the live/synthetic gate (including a monkeypatched-network test so the
"real network fails" assertion doesn't silently depend on this sandbox
staying blocked forever), the synthetic-demo round-trip, and the
fund-snapshot history log's append/replace/lookup logic.

## Files

```
cde/
  config.py                    fund universe, the live/synthetic gate, disclaimer
  synthetic.py                 seeded deterministic fallback panel
  adapters/
    ishares_holdings.py        REAL adapter — makes a real HTTP call when enabled;
                                see its module docstring for the full research trail
  export.py                    builds holdings -> calls quant-infra/cascade/pressure.py
                                for real -> writes the website JSON
tests/
  test_ishares_holdings.py     CSV-parser + adapter-gate tests
  test_synthetic.py            synthetic-demo panel tests
  test_export.py               build_export round-trip + live-gate tests
  test_fund_snapshots_history.py   history log append/replace/lookup tests
```

## What this is NOT

Not a `CascadeNetwork.tsx` rebuild. That component doesn't currently exist
in this repo (it was apparently deleted at some point after
`PLATFORM_REBUILD_PLAN.md` logged it as "orphaned but not deleted" — not
re-created here). Per this task's own instruction and this repo's standing
rule (see `VisualsClient.tsx`'s top comment on why the ORIGINAL
CascadeNetwork was pulled), a component is only rebuilt "for real" once
real data is actually flowing through it end to end — and it isn't, yet:
`public/data/cascade/latest.json` as shipped in this pass is
`"data_provenance": "synthetic-demo"`, because no sandbox available while
building this could actually complete the live HTTP call. `src/lib/
cascade.ts` and `src/lib/models/cascade-export.ts` (the read seam) exist so
a future pass — on a machine that can actually reach `ishares.com` — has
somewhere real to plug into without redesigning the contract.

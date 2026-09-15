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
- **This engine has never fetched `ishares.com` (holdings CSV OR the fund
  overview page, see NAV below) itself, from any sandbox it runs in.**
  Both this repo's cloud workspace and its on-device shell get an
  identical `403`/"policy denial" from their egress proxy the instant they
  try to reach `ishares.com` — re-confirmed this pass with a direct
  `curl`, same as the existing Tiingo/Alpha Vantage evidence in
  `PLATFORM_REBUILD_PLAN.md`. `IsharesHoldingsAdapter.get_holdings()` and
  the new `IsharesNavAdapter.get_nav()` both make REAL calls (`urllib`)
  when enabled — but neither has ever been exercised past that 403, in any
  sandbox this engine has run in. Try it from your own machine.

**Solved this pass (2026-09-14) — real adapters built, gated, tested, but
NOT yet exercised end to end against a live network from any sandbox this
engine runs in (see above):**
- **NAV per share** (`cde/adapters/ishares_nav.py`). CONFIRMED via
  WebFetch that iShares' fund OVERVIEW page (a different URL from the
  holdings CSV, same host, same no-auth) displays a current NAV — e.g.
  "NAV as of Sep 11, 2026 $768.0252" for IVV. No separate no-auth
  JSON/CSV endpoint carrying NAV alone was found — this is a second HTML
  page fetch, not a second structured export. Two independent WebFetch
  passes over the same URL DISAGREED on whether that figure lives inside
  structured JSON-LD or plain HTML text (both agreed on the number and the
  surrounding phrase, not on the markup) — named plainly in
  `ishares_nav.py`'s own docstring as a genuinely weaker confirmation than
  the holdings CSV's column-name check, not smoothed over. The adapter
  treats the page as opaque text and regex-matches the confirmed phrase,
  raising `LiveFetchFailedError` (not a guessed value) if that phrase ever
  drifts. Wired into `cde/export.py`: real NAV now feeds
  `estimate_flow_from_shares_outstanding` for a fund with a usable
  prior-day snapshot (closing the exact gap this section used to describe
  — flow no longer needs `nav_per_share=NaN` on day two-plus runs), and
  separately feeds `estimate_flow_proxy` (alongside the fund's own
  price/volume from Alpaca, next item) for a fund's very first live run,
  which has no prior day to diff against at all.
- **`typical_volume` per constituent** (`cde/adapters/alpaca_volume.py`).
  This platform's usual volume vendor, Tiingo, remains blocked from every
  sandbox this engine runs in exactly like `ishares.com` itself — a
  separate, independent wall. `chaos-engine`'s own Alpaca adapter
  (`chaos/adapters/alpaca_bars.py`, built concurrently this pass)
  confirmed Alpaca Markets' free "Basic" Market Data API plan is genuinely
  free (a paper account, no funding needed) and reaches real historical
  bars with volume — a DIFFERENT vendor than the Tiingo wall. This
  engine's own adapter requests Alpaca's `1Day` (daily) bars, not the
  `1Min` bars `chaos-engine` uses — the right granularity for a "typical
  volume" trailing average, not an intraday signal. Gated on the SAME two
  env vars `chaos-engine`'s adapter uses (`ALPACA_API_KEY_ID`/
  `ALPACA_API_SECRET_KEY`, intentionally matching literal strings, NOT
  imported — this engine stays sealed from `chaos-engine`), so one key
  pair configured once lights up both engines. Wired into
  `cde/export.py`'s live path: when Alpaca is configured and reachable,
  `compute_pressure` now gets a real `typical_volume` mapping instead of
  an unconditional `{}`. Independently gated from the iShares holdings
  fetch — a "live" pressure export (iShares reachable) can legitimately
  carry `typical_volume_provenance: "not-configured"` (Alpaca not set up)
  or vice versa; the export's new `typical_volume_provenance` field
  reports exactly which state applies, and `compute_pressure`'s own
  documented contract (missing `typical_volume` entry -> excluded leg,
  reason recorded in `warnings`) is relied on, not reimplemented, for
  every ticker Alpaca doesn't return a bar for.

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

42 tests, all passing (23 from the original pass + 19 added 2026-09-14 for
`ishares_nav.py` and `alpaca_volume.py`), pure standard library plus this
repo's existing `pandas`/`numpy` (already installed — no `requirements.txt`,
nothing new to `pip install`; confirmed via `python3 -c "import pandas"`
before assuming, same discipline `earnings-engine/README.md` documents).
Covers: the holdings-CSV parser and the NAV-phrase parser, each against a
hand-built fixture matching what was actually confirmed (see each
adapter's own docstring); the Alpaca daily-bar aggregation logic (average
dollar volume, malformed-bar skipping, zero-bars-omitted-not-zeroed) against
hand-built fixture bar lists; every adapter's live/synthetic gate
(including monkeypatched-network tests so the "real network fails"
assertions don't silently depend on this sandbox staying blocked forever);
`build_export`'s LIVE path wiring itself — both the "NAV + Alpaca
available" and "Alpaca not configured" cases, via mock-patched fake
adapters so no real network is needed to prove the wiring is correct; the
synthetic-demo round-trip; and the fund-snapshot history log's
append/replace/lookup logic.

## Files

```
cde/
  config.py                    fund universe, the live/synthetic gate, disclaimer
  synthetic.py                 seeded deterministic fallback panel
  adapters/
    ishares_holdings.py        REAL adapter — holdings CSV; makes a real HTTP call
                                when enabled; see its module docstring for the full
                                research trail
    ishares_nav.py              REAL adapter — NAV per share from the fund overview
                                page (2026-09-14); see its module docstring for the
                                research trail and its lower-confidence-than-the-CSV
                                parsing caveat
    alpaca_volume.py            REAL adapter — typical_volume per constituent (and a
                                fund's own latest price/volume) from Alpaca's free
                                daily-bars endpoint (2026-09-14); gated on the same
                                ALPACA_API_KEY_ID/ALPACA_API_SECRET_KEY env vars
                                chaos-engine's own Alpaca adapter uses (matching
                                literal strings, not imported — this engine stays
                                sealed); see its module docstring for the research
                                trail
  export.py                    builds holdings -> real NAV -> real typical_volume ->
                                calls quant-infra/cascade/pressure.py for real ->
                                writes the website JSON
tests/
  test_ishares_holdings.py     CSV-parser + adapter-gate tests
  test_ishares_nav.py          NAV-phrase-parser + adapter-gate tests
  test_alpaca_volume.py        daily-bar aggregation + adapter-gate tests
  test_synthetic.py            synthetic-demo panel tests
  test_export.py               build_export round-trip, live-gate tests, and
                                live-path NAV/Alpaca wiring tests
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

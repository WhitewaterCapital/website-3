# WW-EARNINGS — earnings calendar + pre-print positioning

Answers one narrow question honestly: for the platform's fixed cross-sectional
universe, which names have a confirmed earnings print inside the next
`LOOKAHEAD_DAYS`, and what do this repo's own already-real signals (WW-Insider,
WW-Factor) say about each name going into that print.

**Not** an earnings-surprise-direction predictor — see
`research/equity-model-research-dossier.md`'s own "Earnings-surprise
direction" row: Medium confidence, needs analyst-estimate data with poor
free coverage (re-checked against current 2026 terms 2026-09-14 — see
"Tier B" below; one free path was found and wired, but it still cannot turn
into surprise-DIRECTION *prediction*, since this engine only ever exports
pre-print events). This engine ships the honestly-buildable part (the
calendar, plus reuse of two already-real positioning signals, plus a real
SUE calculator that activates once an actual EPS exists) and abstains
rather than fabricate the rest. See `src/lib/models/impl/earnings-move.ts`
for the website-side model that consumes this export.

## Run it

```
cd earnings-engine
python -m ee.export
```

Writes `public/data/earnings/latest.json` (web-servable) and
`earnings-engine/exports/latest.json` (engine-side copy).

- `FMP_API_KEY` unset → deterministic synthetic-demo calendar (`ee/synthetic.py`).
- `FMP_API_KEY` set → real Financial Modeling Prep pull via
  `ee/adapters/fmp_calendar.py` — **the adapter is currently an honest stub**;
  see its module docstring for exactly what to implement. No sandbox this
  engine has been built in has outbound network access to verify this path
  live — same wall documented for Tiingo/Alpha Vantage/iShares in
  `PLATFORM_REBUILD_PLAN.md`'s Roadblocks. Try it from your own machine.

## Tests

```
python -m unittest discover -s tests -v
```

Pure standard library — no `requirements.txt`, nothing to `pip install`.
Deliberately kept dependency-free so this engine can be built and verified
even from a sandboxed shell with no PyPI access (confirmed working end to
end from exactly such a shell — see the commit this shipped in).

## Files

```
ee/
  config.py        universe, lookahead window, both live/synthetic gates (calendar + Tier B)
  synthetic.py      seeded deterministic fallback calendar (Tier B fields honestly null)
  sue.py             real, tested, dependency-free Standardized Unexpected Earnings calculator
  adapters/
    fmp_calendar.py             FMP calendar adapter — honest stub, zero network calls, see its docstring
    alpha_vantage_estimates.py  Tier B estimates adapter — honest stub; docstring has the full provider survey
  export.py          builds + writes the website JSON, attaching Tier B fields to every event
tests/
  test_export.py     synthetic-path + roundtrip + Tier-B-schema tests (all passing, stdlib only)
  test_sue.py        SUE calculator unit tests — abstention + real-computation cases (all passing, stdlib only)
```

## Tier B — analyst estimates / SUE (added 2026-09-14)

The dossier's "poor free coverage" verdict on analyst estimates/revisions
(`research/equity-model-research-dossier.md`, line ~397) was re-checked
against CURRENT 2026 provider terms — a dossier that itself says "verify
current terms — provider terms drift" shouldn't be treated as permanently
settled. This section records exactly what was checked, what was verified
by fetching a real page vs. inferred from third-party sources vs. assumed,
and what got built as a result. Full per-provider detail (with citations)
lives in `ee/adapters/alpha_vantage_estimates.py`'s module docstring —
this is the short version.

| Provider | Verdict | Evidence |
|---|---|---|
| **Financial Modeling Prep** | **Confirmed paid** — free tier excludes estimates | Fetched `site.financialmodelingprep.com/pricing-plans` directly (twice, consistent): "Analyst" row shows a dash for Basic/Starter/Premium, only Ultimate shows limited access. This engine's existing `FMP_API_KEY` (calendar-only) does NOT unlock it. |
| **Finnhub** | **Inconclusive** — could not verify either way | finnhub.io's docs/pricing are a client-rendered SPA; every fetch attempt this session made returned only HTML `<meta>` tags, never the rendered Premium badges. Third-party summaries disagreed with each other (one says "basic fundamentals" free, another describes a 2026 two-tier restructure that reads as fundamentals now paid-only). A 2020 GitHub issue shows a history of moving free endpoints to Premium. Do not build against this without a session that can load the real docs or a live key to test. |
| **Alpha Vantage** | **Well-evidenced free** — the one path this engine ships wired for | `macroption.com`'s field-level AV reference documents `EARNINGS_CALENDAR`'s `estimate` column (forward consensus EPS) with no premium notice; AV publishes an unauthenticated public demo link for that exact function; two independent tutorials show real `EARNINGS` function output (`estimatedEPS`/`surprise`/`surprisePercentage` per historical quarter) obtained with "your free API key," no paywall mentioned. NOT a live authenticated fetch from this session (network blocked everywhere this session ran — see below) — re-verify with a real key before depending on it beyond this engine's honest-abstention default. |
| **Zacks** | Assumed paid, not independently re-verified beyond its own Nasdaq Data Link listing (`ZEE`) being a commercial database with no visible free tier | Consistent with every source checked and the dossier's own prior assumption; not worth more research time. |
| **Nasdaq Data Link / Quandl** | Could not check | `data.nasdaq.com` is also a client-rendered SPA this session's tooling could not read. The one dataset identified by name (Zacks' `ZEE`) is paid per the row above; no free alternative found. |

**Network reality check, so a future session doesn't waste time retrying
this:** every one of `site.financialmodelingprep.com`, `finnhub.io`,
`www.alphavantage.co`, and `data.nasdaq.com` was unreachable from BOTH
this session's cloud container (proxy returned `403 connect_rejected`,
"organization policy") AND this session's on-device shell on the repo
owner's own Mac (`curl` exit 56, connection refused). This is the same
wall `PLATFORM_REBUILD_PLAN.md`'s Roadblocks already documented for
Tiingo/Alpha Vantage/iShares — re-confirmed here, not new. All of the
evidence above came from a web-fetch/web-search tool operating outside
those two sandboxes, reading vendors' own pages and third-party technical
references — real pages, genuinely read, just not the same network path
this repo's own code runs on. A live key + a real network path is still
required before any of this is more than well-evidenced plumbing.

**What got built:** `ee/sue.py` (real, tested, dependency-free SUE
calculator — Foster-Olsen-Shevlin 1984 formulation, consensus-estimate
variant) and `ee/adapters/alpha_vantage_estimates.py` (honest zero-
network-call stub, same pattern as `adapters/fmp_calendar.py`, gated on a
NEW, separate `ALPHA_VANTAGE_API_KEY` env var — not `FMP_API_KEY`, since
FMP's key doesn't cover this). `ee/export.py` now attaches
`eps_estimate_stdev` / `estimate_source` / `sue` / `sue_abstain_reason` to
every event, live or synthetic. **`sue` is null on every event this engine
can currently produce, by construction** — every export is pre-print
(`report_date` always in the future), and SUE requires an actual EPS that
doesn't exist yet. That's not a gap this session failed to close; it's
what "the calendar engine only shows upcoming prints" structurally means
for a target defined as `(actual − estimate) / stdev`. A future
retrospective/backtest script (the dossier's own "AUC, Brier" evaluation
of this target) is the right place to ever see a non-null SUE, using the
exact same tested `compute_sue()`.

**Explicitly NOT built:** revision momentum (direction/magnitude of
recent estimate changes). Alpha Vantage's free endpoints only expose the
CURRENT consensus estimate, not point-in-time snapshots of how it moved —
computing a revision needs this engine to start storing its own weekly
snapshots over time, which is real infrastructure work, not a data-access
problem, and wasn't in scope for this session.

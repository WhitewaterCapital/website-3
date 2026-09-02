# Incepta Engine

The Python quantitative engine behind the Four & Co. platform. It is deliberately
**separate** from the Next.js app: it does the heavy, deterministic work —
ingestion, a point-in-time (PIT) feature store, factor/valuation/quality/vol math,
scoring, backtesting and validation — and writes results the website reads.

> **The engine is the "factory"; the website is the "storefront."** No LLM lives
> in here. Every number is math on real, timestamped data.

## Build order (vertical slices) — status

1. ✅ **Slice 1 — EDGAR → PIT fundamental store.** Company-facts ingestion,
   stamped with the point-in-time taxonomy, stored as-first-reported.
2. ✅ **Slice 2 — Prices.** ⚠️ Stooq is now behind a JS bot-detection challenge
   (not bypassed). Use the **Tiingo** adapter (`TIINGO_API_KEY`) for real prices.
3. ✅ **Slice 3 — Feature engineering** (`features/`): returns, momentum,
   reversal, realized/downside vol, 52w-high, Amihud, Corwin-Schultz spread.
4. ✅ **Slice 4 — Models** (`models/`): EWMA vol, FF5+MOM factor exposures,
   valuation (with break-down flags), Piotroski F / Altman Z.
5. ✅ **Slice 5 — Cross-sectional scoring** (`models/scoring.py`): robust-z,
   sector-neutral, signed-weight composite → percentile rank.
6. ✅ **Slice 6 — Validation + backtest** (`validation/`, `backtest/`): purged
   walk-forward/k-fold, IC/rank-IC, PSR + **Deflated Sharpe**, cost-aware L/S.
7. ⬜ Later — Tiingo/Sharadar wiring at universe scale; publish serving tables to
   Supabase Postgres for the website.

Run the tests (18, all offline, known-answer): `.venv/bin/python -m pytest`

### Real prices — set a free Tiingo key
```bash
export TIINGO_API_KEY="your_free_token"   # https://www.tiingo.com
```
Without it, the fundamentals path still runs fully (see `quality` below);
price/momentum/vol/factor-exposure/backtest need the key.

## Why PIT first

The three named failure modes for this project are **look-ahead, survivorship, and
overfitting** (see the research dossier). Look-ahead is the most dangerous and the
easiest to introduce, so the store is built to make it *structurally hard*: every
fact carries `fiscal_period_end`, `filed` (filing date), `form`, and an
`is_first_reported` flag, and all reads are `as-of` a date.

## Quick start

```bash
cd engine
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# SEC requires a descriptive User-Agent with a contact email (else HTTP 403).
export SEC_USER_AGENT="Four & Co. Research your.email@example.com"

# Ingest one company's full PIT fundamental history into the local DuckDB store:
.venv/bin/python -m incepta.cli ingest AAPL

# Show what was *knowable* as of a past date (point-in-time query):
.venv/bin/python -m incepta.cli asof AAPL 2021-01-15
```

## Data sources (slice 1)

| Source | What | Key? | Limits (verified 2026-08) |
|---|---|---|---|
| SEC EDGAR `data.sec.gov` | XBRL company facts (fundamentals) | **No key** | ≤10 req/s; **must** send `User-Agent` with contact email |
| SEC `company_tickers.json` | ticker → CIK map | No key | same |

## Config (environment variables)

- `SEC_USER_AGENT` — **required** by SEC. Format: `"Org Name email@domain"`.
- `INCEPTA_DATA_DIR` — where the DuckDB file + caches live (default `./data`).

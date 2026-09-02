# Incepta Engine → Website Integration (handoff for the app/main chat)

This is the "final product" contract. The Python engine (the *factory*) produces a
single JSON document; the Next.js site (the *storefront*) reads it and renders the
UI. **The engine never runs inside a web request** — it runs on a schedule and
writes the file; the site only reads.

## 1. What you get

A JSON file, schema `v1.0.0`, written to two places by `incepta.cli export`:

- **`public/data/incepta/latest.json`** ← web-servable at `/data/incepta/latest.json`
- `engine/exports/latest.json` (an engine-side copy)

Its shape is fully typed in **`engine/contracts/equity_export.ts`** — copy that file
into the app (e.g. `src/lib/models/incepta-export.ts`) and type your fetch against it.

Top level: `{ schema_version, engine_version, generated_at, as_of, universe,
disclaimer, securities[], rankings }`. Each `securities[]` entry has `risk`,
`quality`, `valuation`, a `data_quality` block, and a `confidence` level.

## 2. How to consume it (pick one)

**A. Static fetch (simplest, do this first).**
```ts
import type { EquityExport } from "@/lib/models/incepta-export";
const res = await fetch("/data/incepta/latest.json", { cache: "no-store" });
const data: EquityExport = await res.json();
```

**B. Wrap it in the existing model contract.** The app already defines
`EquityModel.read(dateISO) → EquityReading` with an empty slot
(`equityModels: []` in `src/lib/models/registry.ts`). Implement `impl/equity.ts`
to read this JSON and map it into an `EquityReading` (breadth + per-name signals),
then register it. Keeps the rest of the app unchanged.

**C. API route (recommended for production).** Add `src/app/api/models/equity/route.ts`
that reads the JSON (or later, Supabase) server-side and returns it. This is the
seam where you later swap the file for a Supabase Postgres table with zero UI change.

## 3. How it plugs into what's already there

- **Standing view** (browse names): render `securities[]` as analysis cards +
  the `rankings.quality` table. This is the "Sentimentum · Equity" reader.
- **Per-trade flow** (`/api/models/stress` already takes a `TradeIdea`): when a
  member submits a ticker, look it up in `securities[]` and feed its `risk` /
  `quality` / `valuation` into Distresse's scorecard. The engine is the evidence
  source; Distresse is the judge on top (see the architecture memory).

## 4. UI rules the payload enforces (please honor these)

- **Show `disclaimer`** somewhere visible. This is research/paper output.
- **Use `confidence`** to style each card:
  - `high` → show normally.
  - `medium` / `low` → show with a caution badge; surface `data_quality.flags`.
  - `insufficient` → **do not show numbers**; show "not enough data" (the abstain rule).
- **`null` means unknown** — render "—", never `0`.
- Show `valuation.flags` / `data_quality.flags` (e.g. "negative earnings → P/E not
  meaningful", "bank/finance: EV/EBITDA unreliable"). They are the honesty layer.

## 5. Honest status — what this is and is NOT

- ✅ Real point-in-time SEC fundamentals, real adjusted prices (Tiingo), real
  factor exposures (Fama-French), quality/valuation/volatility — all tested.
- ❌ NOT a validated alpha model: no cross-sectional edge has been proven yet
  (the backtest across a large universe is the next engine slice).
- ❌ Small universe + free-data survivorship limits. Some fundamental fields are
  `null` due to XBRL tagging gaps (normalization hardening is pending).
- ❌ No macro-regime overlay or committee yet (separate workstreams).

Treat it as a **risk-and-evidence display**, not a buy/sell engine. Label it that
way in the UI.

## 6. Regenerating the data

```bash
cd engine
.venv/bin/python -m incepta.cli ingest AAPL MSFT NVDA KO F   # refresh raw data
.venv/bin/python -m incepta.cli export AAPL MSFT NVDA KO F   # rewrite latest.json
```
Later this runs on a schedule (Vercel Cron / a small worker) and, for production,
writes to Supabase Postgres instead of a file — same schema, so the UI is unchanged.

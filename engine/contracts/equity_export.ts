// Incepta equity engine — website handoff contract (schema v1.0.0)
// Mirrors engine/incepta/export.py. Copy this into the Next.js app (e.g.
// src/lib/models/incepta-export.ts) and type your fetch of
// /data/incepta/latest.json against it.
//
// Every number can be null — the engine emits null (not 0, not a guess) when a
// value is missing. The UI MUST treat null as "unknown" and lean on
// `confidence` / `data_quality.flags` to decide what to show vs. grey out.

export type Confidence = "high" | "medium" | "low" | "insufficient";

export interface DataQuality {
  has_prices: boolean;
  has_fundamentals: boolean;
  fundamentals_period_end: string | null; // ISO date of the latest annual used
  price_last_close: number | null;
  stale: boolean;
  flags: string[]; // human-readable reasons (e.g. "no fundamentals", "bank/finance: EV/EBITDA unreliable")
}

export interface RiskRead {
  last_close: number;
  n_bars: number;
  mom_12_1: number | null;      // 12-1 momentum (decimal, e.g. 0.49 = +49%)
  ret_1m: number | null;
  realized_vol: number | null;  // annualized
  downside_vol: number | null;  // annualized semi-deviation
  ewma_vol: number | null;      // annualized EWMA
  max_dd_1y: number | null;     // negative
  high_52w_ratio: number | null;// 1.0 = at 52w high
  spread_bps: number | null;    // ESTIMATED (Corwin-Schultz) — overstates for liquid names
  beta_mkt: number | null;
  beta_smb: number | null;
  beta_hml: number | null;
  beta_mom: number | null;
  factor_r2: number | null;
  idio_vol: number | null;      // annualized idiosyncratic vol
  n_factor_obs: number | null;
}

export interface QualityRead {
  period_end: string | null;
  roa: number | null;
  roe: number | null;
  gross_margin: number | null;
  net_margin: number | null;
  fcf_margin: number | null;
  leverage: number | null;      // long-term debt / assets
  rev_growth: number | null;    // YoY, decimal
  piotroski_f: number | null;   // 0..piotroski_max
  piotroski_max: number | null; // how many of the 9 signals were computable
}

export interface ValuationRead {
  market_cap: number | null;
  pe: number | null;
  earnings_yield: number | null;
  pb: number | null;
  ps: number | null;
  fcf_yield: number | null;
  ev: number | null;
  ev_sales: number | null;
  flags: string[]; // e.g. "negative/zero earnings → P/E not meaningful"
}

export interface SecurityAnalysis {
  ticker: string;
  name: string | null;
  sector: string | null; // SIC description
  sic: string | null;
  as_of: string;         // ISO date
  data_quality: DataQuality;
  confidence: Confidence;
  risk: RiskRead | null;         // null when no price history
  quality: QualityRead | null;   // null when no fundamentals
  valuation: ValuationRead | null;
}

export interface RankingEntry {
  ticker: string;
  rank: number;  // 0..100 percentile within the exported universe
  score: number; // composite z-score (relative, not absolute)
}

export interface EquityExport {
  schema_version: string;   // "1.0.0"
  engine_version: string;
  generated_at: string;     // ISO datetime
  as_of: string;            // ISO date
  universe: string[];
  disclaimer: string;       // SHOW THIS in the UI
  securities: SecurityAnalysis[];
  rankings: { quality: RankingEntry[] };
}

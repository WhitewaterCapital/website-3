// Incepta equity engine — website handoff contract (schema v1.0.0).
// Copied from engine/contracts/equity_export.ts. The UI types its data against
// this, NOT the file location — production swaps the file for a Supabase table
// with the same schema.
//
// Every number can be null — the engine emits null (not 0, not a guess) when a
// value is missing. The UI MUST treat null as "unknown", render it "—", and
// lean on `confidence` / `data_quality.flags` to decide what to show.

export type Confidence = "high" | "medium" | "low" | "insufficient";

export interface DataQuality {
  has_prices: boolean;
  has_fundamentals: boolean;
  fundamentals_period_end: string | null;
  price_last_close: number | null;
  stale: boolean;
  flags: string[];
}

export interface RiskRead {
  last_close: number;
  n_bars: number;
  mom_12_1: number | null;
  ret_1m: number | null;
  realized_vol: number | null;
  downside_vol: number | null;
  ewma_vol: number | null;
  max_dd_1y: number | null;
  high_52w_ratio: number | null;
  spread_bps: number | null;
  beta_mkt: number | null;
  beta_smb: number | null;
  beta_hml: number | null;
  beta_mom: number | null;
  factor_r2: number | null;
  idio_vol: number | null;
  n_factor_obs: number | null;
}

export interface QualityRead {
  period_end: string | null;
  roa: number | null;
  roe: number | null;
  gross_margin: number | null;
  net_margin: number | null;
  fcf_margin: number | null;
  leverage: number | null;
  rev_growth: number | null;
  piotroski_f: number | null;
  piotroski_max: number | null;
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
  flags: string[];
}

export interface SecurityAnalysis {
  ticker: string;
  name: string | null;
  sector: string | null;
  sic: string | null;
  as_of: string;
  data_quality: DataQuality;
  confidence: Confidence;
  risk: RiskRead | null;
  quality: QualityRead | null;
  valuation: ValuationRead | null;
}

export interface RankingEntry {
  ticker: string;
  rank: number;
  score: number;
}

export interface EquityExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  universe: string[];
  disclaimer: string;
  securities: SecurityAnalysis[];
  rankings: { quality: RankingEntry[] };
}

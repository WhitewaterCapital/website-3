// WW-WEEKLY engine — website handoff contract (schema v1.0.0).
// Mirrors weekly-engine/wf/export.py. The site types its read against this.
// Same honesty rules as Intra/Exitus and Incepta: this is a low-predictability,
// research-grade RANK signal, not price targets — never render it as one.

export type WeeklyConfidence = "research-grade";

export interface WeeklyForecast {
  ticker: string;
  // Sector-demeaned, cross-sectionally dispersion-SCALED point score (see
  // wf/model/neutralize.py): a standardized "how far above/below sector-neutral"
  // ranking score, NOT a percentage return — that is what `decile` is built
  // from. quantile_p10/p50/p90 below are the actual predicted return band
  // (unscaled), so read magnitude off those, and ranking off this + decile.
  expected_relative_return: number | null;
  quantile_p10: number | null;
  quantile_p50: number | null;
  quantile_p90: number | null;
  decile: number | null; // 1..10, 10 = most bullish that week
  model_version: string; // "ridge-1.0" | "gbm-1.0" (whichever cleared validation)
  feature_manifest_hash: string;
  confidence: WeeklyConfidence;
  rank_ic_oos: number | null; // walk-forward out-of-sample rank IC of the published model
  provisional: boolean;
}

export interface WeeklyValidationSummary {
  n_folds: number;
  ridge_mean_rank_ic: number | null;
  gbm_mean_rank_ic: number | null;
  ridge_mean_hit_rate: number | null;
  gbm_mean_hit_rate: number | null;
  ridge_mean_decile_spread: number | null;
  gbm_mean_decile_spread: number | null;
  ridge_turnover: number | null;
  gbm_turnover: number | null;
  ridge_deflated_sharpe: number | null;
  gbm_deflated_sharpe: number | null;
  gbm_beats_baseline: boolean;
  gbm_beats_baseline_reason: string;
  model_version_published: string;
}

export interface WeeklyProvenance {
  kind: string; // "synthetic-demo" until a real point-in-time feed is wired in
  note: string;
  generator: string;
  seed: number;
  signal_strength: number;
  n_weeks: number;
}

export interface WeeklyExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  universe: string[];
  disclaimer: string;
  forecasts: WeeklyForecast[];
  provenance: WeeklyProvenance;
  validation: WeeklyValidationSummary;
}

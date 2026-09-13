// WW-FACTOR engine — website handoff contract (schema v1.0.0).
// Mirrors factor-engine/fac/export.py. The site types its read against this.
//
// Same honesty rules as the other engines: `betas` (and `alpha_daily`/
// `alpha_annualized`/`r2`) are populated ONLY when `confidence === "ok"` — a
// ticker with too little overlapping (Tiingo price, French factor) history
// gets `confidence: "insufficient_history"`, and a numerically degenerate
// regression window gets `confidence: "degenerate"` — see
// factor-engine/fac/regression.py's `fit_factor_exposure`. Never a
// fabricated beta.
//
// `data_provenance` distinguishes a real, live-priced export from the
// synthetic-demo output this sandbox can currently produce (see
// factor-engine/README.md "Current status") — the UI must surface this,
// never present synthetic output as a real market read.
//
// IMPORTANT — this is DESCRIPTIVE RISK CONTEXT, not a directional signal:
// a `FactorBeta.beta` is never fed into `src/lib/models/conviction.ts`'s
// composite score. See `src/components/panels/FactorPanel.tsx`'s top-of-file
// comment for why forcing a factor beta into a signed directional score
// would misrepresent what the number means.

export type FactorConfidence = "ok" | "insufficient_history" | "degenerate";
export type FactorDataProvenance = "synthetic-demo" | "live";

// Fama-French 5 factors (Mkt-RF, SMB, HML, RMW, CMA) plus the momentum
// factor (Mom) from Ken French's separate momentum file — see
// factor-engine/fac/config.py's FACTOR_COLUMNS.
export type FactorName = "Mkt-RF" | "SMB" | "HML" | "RMW" | "CMA" | "Mom";

export interface FactorBeta {
  factor: FactorName;
  beta: number;
  se: number;
  t_stat: number;
  // |t_stat| >= the engine's t-critical value (~1.96, two-sided 5%) — an
  // honest annotation shown ALONGSIDE the beta, never used to hide it. An
  // insignificant beta is still real information ("~zero measurable
  // exposure to this factor right now").
  significant: boolean;
}

export interface FactorExposure {
  ticker: string;
  n_obs: number;
  confidence: FactorConfidence;
  abstain_reason: string | null; // set whenever confidence !== "ok"
  alpha_daily: number | null;
  alpha_annualized: number | null;
  r2: number | null;
  condition_number: number | null;
  betas: FactorBeta[] | null; // null unless confidence === "ok"
}

export interface FactorExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  universe: string[];
  window_trading_days: number;
  min_obs: number;
  factors: FactorName[];
  // One-line, non-quant explanation per factor — same copy the engine's
  // export carries (factor-engine/fac/config.py's FACTOR_EXPLAINERS), kept
  // server-side so the website's plain-English copy never drifts from the
  // engine's own documentation of what each factor means.
  factor_explainers: Record<FactorName, string>;
  disclaimer: string;
  data_provenance: FactorDataProvenance;
  exposures: FactorExposure[];
}

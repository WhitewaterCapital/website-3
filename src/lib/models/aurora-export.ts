// Aurora macro engine — website handoff contract (schema v0.1.0)
// Mirrors aurora/export/export.py. Copy this into the Next.js app (e.g.
// src/lib/models/aurora-export.ts) and type your fetch of
// /data/aurora/latest.json against it.
//
// Same honesty rules as the Incepta equity contract:
//   * Every number can be null — the engine emits null (never 0, never a guess)
//     when something is unknown. The UI MUST treat null as "unknown".
//   * `confidence` and `flags` decide what to show vs. grey out.
//   * `disclaimer` must be shown. This is research/paper output, not advice.
//
// This is the "Sentimentum · Macro" reader's data source.

export type Confidence = "high" | "medium" | "low" | "insufficient";

// ---------------------------------------------------------------------------
// 1. Steady state — the model's calibrated "normal" resting point.
// ---------------------------------------------------------------------------
export interface SteadyState {
  KYrat: number;              // capital / output
  HYrat: number;              // housing / output
  Nfrac: number;              // hours worked
  MPfrac: number;             // mortgage payment / worker income
  mortgage_rate_ann: number;  // implied annual mortgage rate (decimal)
  gamma: number;              // mortgage amortisation rate
  calibrated: {               // the 4 recovered free parameters
    omega: number; xi: number; tauK: number; transfer: number;
  };
  residual_norm: number;      // calibration accuracy (should be ~1e-9)
}

// ---------------------------------------------------------------------------
// 2. Scenarios — the core product. Each canonical shock and the economy's
//    impulse-response path, plus a plain-language read for a book like ours.
// ---------------------------------------------------------------------------
export type ShockKind = "TFP" | "monetary" | "housing" | "discount_factor";

export interface ImpulsePath {
  variable: string;   // e.g. "output", "consumption", "house_price", "mortgage_spread", "policy_rate"
  unit: "pct_dev" | "level" | "bps";  // % deviation from steady state, level, or basis points
  path: (number | null)[];            // one value per quarter, length = horizon
}

export interface ScenarioEffect {
  variable: string;
  impact: number | null;      // period-1 response — defines the shock's DIRECTION
  peak: number | null;        // largest-magnitude response (signed)
  peak_quarter: number;       // quarter of the peak (1-indexed)
  reverses: boolean;          // true if the sign flips over the horizon (mean-reverting)
}

export interface Scenario {
  id: string;                 // stable slug, e.g. "monetary_tighten_+1pct"
  kind: ShockKind;
  label: string;              // human title
  description: string;        // what the shock is and its size/sign
  horizon: number;            // number of quarters in each path
  paths: ImpulsePath[];       // impulse responses of the key variables
  effects: ScenarioEffect[];  // signed impact + peak + reversal per variable
  narrative: string;          // "what this means for the book" — plain language
  confidence: Confidence;
}

// ---------------------------------------------------------------------------
// 3. Regime — where the live economy actually is right now (Phase 3+).
//    Null until the FRED layer + nowcaster are wired in.
// ---------------------------------------------------------------------------
export interface RegimeRead {
  as_of: string;                    // ISO date of the latest macro data used
  label: string | null;            // e.g. "late-cycle / rate-shock", or null
  probabilities: Record<string, number> | null;  // regime -> prob (nowcaster)
  key_indicators: {                 // the live macro inputs behind the call
    name: string;                   // FRED series id, e.g. "DGS10"
    value: number | null;
    z_score: number | null;         // vs. own history
    as_of: string | null;           // series-specific date (ragged edge)
  }[];
  confidence: Confidence;
  flags: string[];                  // e.g. "GDP stale (quarterly)", "vintage: real-time"
}

// ---------------------------------------------------------------------------
// 4. Tilt — regime-conditioned sector/factor lean. Macro sets the weather;
//    Incepta (equity engine) picks the names. This is the hand-off to it.
// ---------------------------------------------------------------------------
export interface RegimeTilt {
  factors: { name: string; lean: "overweight" | "neutral" | "underweight"; rationale: string }[];
  sectors: { name: string; lean: "overweight" | "neutral" | "underweight"; rationale: string }[];
  confidence: Confidence;
}

// ---------------------------------------------------------------------------
// 5. Nowcast — trained factor-return model (Phase 4).
//    HONESTY: `expected_return` is only surfaced when the factor shows genuine
//    out-of-sample skill (`skillful`). Otherwise treat it as no-signal.
// ---------------------------------------------------------------------------
export interface FactorNowcast {
  factor: string;                   // "Mkt-RF", "HML", "Mom", ...
  expected_return: number | null;   // forward-horizon %, null when not skillful
  oos_r2: number;                   // out-of-sample R^2 vs a naive mean forecast (>0 = skill)
  hit_rate: number;                 // directional accuracy (0..1)
  skillful: boolean;                // beats the naive baseline out-of-sample
  confidence: Confidence;
}

export interface Nowcast {
  horizon_months: number;
  method: string;                   // e.g. "PCA + Ridge, walk-forward CV"
  as_of: string;
  factors: FactorNowcast[];
  summary: string;                  // honest plain-language verdict
  book_read: string;                // interpretation for the current book (e.g. tech-tilt)
  confidence: Confidence;
}

// ---------------------------------------------------------------------------
// Top-level document written to public/data/aurora/latest.json
// ---------------------------------------------------------------------------
export interface MacroExport {
  schema_version: string;   // "0.1.0"
  engine_version: string;   // aurora package version
  generated_at: string;     // ISO timestamp the file was written
  as_of: string;            // ISO date the macro inputs are current to
  model_variant: "basic_frm" | "basic_arm" | "mortgage_choice" | "refi";
  disclaimer: string;       // MUST be displayed
  steady_state: SteadyState;
  scenarios: Scenario[];
  regime: RegimeRead | null;   // null until Phase 3
  tilt: RegimeTilt | null;     // null until Phase 3
  nowcast: Nowcast | null;     // null until Phase 4 (trained factor model)
}

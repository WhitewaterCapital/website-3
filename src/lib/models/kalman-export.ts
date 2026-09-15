// WW-KALMAN engine — website handoff contract (schema v1.0.0).
// Mirrors kalman-engine/kf/export.py. The site types its read against this.
//
// Same honesty rules as every other engine's *-export.ts in this repo:
// `data_provenance` (here: `provenance`) distinguishes a real, live-priced
// export from this engine's synthetic-demo output (see kalman-engine/
// README.md "Run it") — the UI must surface this, never present
// synthetic output as a real market read.
//
// `cointegrated: false` means this pair was tested for real (Engle-Granger
// two-step — see `cointegration`) and did NOT show statistical evidence of
// a stationary spread over the available history. `kalman` and `score` are
// then absent/null — never a fabricated read forced onto an untested
// relationship. See kalman-engine/kf/cointegration.py's module docstring
// for the exact test and its honesty caveats.
//
// IMPORTANT — this is a RESEARCH READ, not investment advice: `score` and
// `signal` come from the filter's own standardized spread z-score
// (kalman-engine/kf/filter.py), a real statistical quantity, scaled by a
// stated, NOT backtested convention (kalman-engine/kf/config.py::
// Z_TO_SCORE_SCALE) — same "stated simple scaling, not a fitted rule"
// discipline as smart-money-momentum.ts / earnings-move.ts.

export type KalmanProvenance = "synthetic-demo" | "live";

export interface KalmanCointegration {
  adf_t_stat: number | null;
  adf_lag_used: number;
  critical_value_5pct: number;
  // Keyed by significance level as a percent, e.g. "1" | "5" | "10" — JSON
  // object keys are always strings, so this is intentionally
  // Record<string, number>, not Record<number, number>.
  critical_values: Record<string, number>;
  significance: number;
  ols_hedge_ratio: number;
  ols_intercept: number;
  ols_r_squared: number | null;
}

// The specific numbers that make "learns from itself" a checkable claim,
// not a comment — see kalman-engine/kf/filter.py's module docstring and
// kalman-engine/README.md's "Tests" section for exactly what these mean
// and how they were verified to actually move during a run.
export interface KalmanAdaptiveNoise {
  initial_q_trace: number; // trace(Q) at t=0 — kf.config.INITIAL_Q_DIAG, the hand-set STARTING guess only
  final_q_trace: number;   // trace(Q) after the filter's own online re-estimation over this run
  q_drift_pct: number | null;
  initial_r: number;       // R at t=0 — kf.config.INITIAL_R, the hand-set STARTING guess only
  final_r: number;         // R after the filter's own online re-estimation over this run
  r_drift_pct: number | null;
}

export interface KalmanState {
  mu: number;              // filtered intercept, latest time step
  gamma: number;           // filtered hedge ratio, latest time step
  z_score: number;         // standardized pre-fit innovation — the spread signal
  innovation_var: number;
  adaptive_noise: KalmanAdaptiveNoise;
}

export interface KalmanPairReading {
  pair: string;      // "TICKER1/TICKER2"
  ticker1: string;
  ticker2: string;
  available: boolean; // false only when too few overlapping observations to test at all
  cointegrated: boolean;
  n_obs: number;
  cointegration?: KalmanCointegration;
  kalman?: KalmanState; // present only when cointegrated === true
  score: number | null; // -100..100, signed; null when not cointegrated / not available
  signal?: string;       // e.g. "long AAPL / short MSFT", "flat / near fair value"
  note: string;          // always populated — the human-readable reasoning, pass or abstain
}

export interface KalmanExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  universe: string[];
  provenance: KalmanProvenance;
  disclaimer: string;
  pairs_tested: number;
  pairs_available: number;
  pairs_cointegrated: number;
  warnings: string[];
  pairs: KalmanPairReading[];
}

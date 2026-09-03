// WW-CHAOS engine — website handoff contract (schema v0.1.0).
// Mirrors chaos-engine/chaos/export.py. The site types its read against this.
//
// HONESTY (same discipline as aurora-export.ts / intra-exitus-export.ts):
//   * WW-CHAOS is not high-frequency trading. There is no colocated
//     infrastructure and no microsecond order-book access. What is reachable,
//     and all that is ever claimed by this contract, is intraday dislocation
//     capture on a 1 to 15 minute horizon — see `disclaimer`, which MUST be
//     shown wherever this data is surfaced.
//   * Every component carries its own `available: boolean`. An unavailable
//     component (no quote/spread data, no news feed) means "no information",
//     never a fabricated neutral number — `value`/`spread_bps`/etc. are `null`
//     whenever `available` is false, and the UI must treat null as unknown,
//     not as zero.
//   * `directional_probability` is produced by an explicitly SIMPLIFIED
//     stand-in for the design's real causal dilated-TCN — a calibrated
//     gradient-boosted classifier (no local deep-learning framework is
//     available). `calibrated: true` reflects that the probability comes out
//     of isotonic calibration on a held-out fold, not a raw model score.
//   * `abstain: true` means the model is declining to call a direction
//     (calibrated probability too close to a coin flip, or features not
//     warmed up) — the UI must not show a directional lean when abstain is
//     true.
//   * This export runs in synthetic-demo mode only (`provenance:
//     "synthetic-demo"`): every figure comes from a locally generated
//     synthetic intraday panel, not a live market feed.

export type ChaosStateLabel = "calm" | "stressed" | "dislocated" | "cascade";

// ---------------------------------------------------------------------------
// CHAOS-01 — the eight state components. Each is independently gateable via
// `available`; a component that is unavailable contributes nothing to the
// combined index rather than a guessed neutral value.
// ---------------------------------------------------------------------------

export interface ChaosComponentReading {
  available: boolean;
  value: number | null;
}

export interface RangeSpreadDeteriorationReading extends ChaosComponentReading {
  // high-low range relative to close-to-close move. `spread_bps` is a
  // SEPARATE optional sub-reading: real bid/ask spread data does not exist
  // in this repo's synthetic panels (or in any live feed wired in), so it is
  // reported unavailable rather than approximated from OHLCV.
  spread_bps: ChaosComponentReading;
}

export interface OrderFlowImbalanceReading extends ChaosComponentReading {
  // "quote_midpoint" when real bid/ask quotes were supplied; otherwise
  // "tick_rule_bar_close", a documented bar-level APPROXIMATION of the
  // classic tick rule (Lee & Ready 1991) — never a live tape read.
  method: "quote_midpoint" | "tick_rule_bar_close";
}

export interface JumpIndicatorReading {
  available: boolean;
  // Fraction of measured variance attributable to jumps rather than
  // continuous diffusion (Barndorff-Nielsen & Shephard bipower-variation
  // ratio statistic), in roughly [0, 1).
  relative_jump: number | null;
  // Asymptotically N(0,1) under the null of no jumps; large |z_stat| rejects
  // "elevated but continuous diffusion" in favour of a genuine discontinuity.
  z_stat: number | null;
}

export interface ChaosComponents {
  volatility_ratio: ChaosComponentReading;
  volume_surprise: ChaosComponentReading;
  range_spread_deterioration: RangeSpreadDeteriorationReading;
  cross_sectional_dispersion: ChaosComponentReading;
  correlation_shift: ChaosComponentReading;
  order_flow_imbalance: OrderFlowImbalanceReading;
  jump_indicator: JumpIndicatorReading;
  // No real news/novelty pipeline exists in this repository. `available` is
  // only ever true if an external caller supplied a real novelty score;
  // this engine never fabricates one.
  novelty: ChaosComponentReading;
}

// ---------------------------------------------------------------------------
// One ticker's current reading.
// ---------------------------------------------------------------------------

export interface ChaosReading {
  ticker: string;
  // Weighted combination of the eight components, in [0, 1]. Null only in
  // the (synthetic-demo-unreachable) case where every component is
  // unavailable at once.
  chaos_index: number | null;
  state_label: ChaosStateLabel;
  components: ChaosComponents;
  // Calibrated P(price rises over the model's short forecast horizon).
  directional_probability: number | null;
  calibrated: true;
  abstain: boolean;
  // Spread of a small bagged ensemble's predict_proba — an honest proxy for
  // predictive uncertainty, not a real quantile/interval from a
  // probabilistic model.
  uncertainty: number | null;
  as_of: string; // ISO timestamp of the last bar used for this reading
}

// ---------------------------------------------------------------------------
// Top-level document written to public/data/chaos/latest.json
// ---------------------------------------------------------------------------

export interface ChaosExport {
  schema_version: string; // "0.1.0"
  engine_version: string; // chaos-engine package version
  generated_at: string; // ISO timestamp the file was written
  as_of: string; // ISO timestamp the underlying bars are current to
  watchlist: string[];
  // Always "synthetic-demo" today — see the module-level HONESTY note above.
  provenance: "synthetic-demo" | "live";
  disclaimer: string; // MUST be displayed — states the "not HFT" framing
  readings: ChaosReading[];
}

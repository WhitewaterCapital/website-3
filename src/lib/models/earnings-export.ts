// WW-EARNINGS engine — website handoff contract (schema v1.1.0).
// Mirrors earnings-engine/ee/export.py. The site types its read against this.
//
// Calendar data only — deliberately NOT a surprise-direction or price-move
// prediction. See earnings-engine/README.md and
// research/equity-model-research-dossier.md's "Earnings-surprise direction"
// row for why that's out of scope for this export. Any directional read
// shown alongside an event (insider activity, factor momentum) is composed
// client-side in earnings-move.ts from OTHER, already-real engines' exports
// — never derived from this file.
//
// `data_provenance` distinguishes a real FMP-sourced calendar from the
// synthetic-demo fallback this repo can currently produce with no
// FMP_API_KEY configured (see earnings-engine/README.md) — the UI must
// surface this, never present synthetic output as a real calendar.
//
// TIER B (added 2026-09-14): `eps_estimate_stdev` / `estimate_source` /
// `sue` / `sue_abstain_reason` are an ADDITIVE extension — every event
// already carried `eps_estimate`, this adds the pieces needed to turn a
// consensus EPS estimate into a real Standardized Unexpected Earnings
// figure (SUE = (actual − estimate) / stdev-of-trailing-surprises; see
// earnings-engine/ee/sue.py) once both an estimate and an actual exist.
// `sue` is null on literally every event this export can currently
// produce: every event here is pre-print by construction (report_date is
// always in the future), and SUE requires an actual EPS that does not
// exist yet — `sue_abstain_reason` says so explicitly rather than leaving
// the UI to guess why. These fields are gated on a SEPARATE key
// (ALPHA_VANTAGE_API_KEY, not FMP_API_KEY — FMP's free tier does not cover
// analyst estimates; see earnings-engine/ee/adapters/
// alpha_vantage_estimates.py's docstring for the full 2026-09-14 provider
// survey behind that choice) and are honestly null with a stated reason
// whenever that key is unset or the adapter is still a stub, exactly like
// every other honest-abstention field in this repo.

export type EarningsDataProvenance = "synthetic-demo" | "live";
export type EarningsSession = "bmo" | "amc" | "dmh" | null;

export interface EarningsEvent {
  ticker: string;
  report_date: string; // ISO date
  session: EarningsSession;
  eps_estimate: number | null;
  eps_actual: number | null;
  fiscal_period: string | null;
  source: string; // vendor id, or "synthetic-demo"

  // Tier B — see the module-level comment above. `sue_abstain_reason` is
  // non-null exactly when `sue` is null (mirrors ee/sue.py's
  // compute_sue() contract: (value, reason) where exactly one is null).
  eps_estimate_stdev: number | null; // stdev of trailing (actual-estimate) surprises — SUE denominator
  estimate_source: string | null; // vendor id for eps_estimate/eps_estimate_stdev, e.g. "alpha-vantage", or null if unavailable
  sue: number | null; // Standardized Unexpected Earnings — always null pre-print (see above)
  sue_abstain_reason: string | null; // why sue is null, stated plainly
}

export interface EarningsExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  universe: string[];
  lookahead_days: number;
  disclaimer: string;
  data_provenance: EarningsDataProvenance;
  events: EarningsEvent[];
}

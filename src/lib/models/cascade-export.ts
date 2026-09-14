// WW-CASCADE-DATA engine — website handoff contract (schema v1.0.0).
// Mirrors cascade-data-engine/cde/export.py. The site types its read
// against this. See cascade-data-engine/README.md for the full research
// trail on what's real (the iShares holdings endpoint itself, confirmed
// live this pass via WebFetch) vs. what's still open (this engine's own
// network access to it, from any sandbox it has been built in; the
// typical_volume input; NAV-per-share for pricing a flow delta).
//
// `data_provenance` distinguishes a real holdings-derived pressure export
// from the synthetic-demo fallback this engine produces with no
// CASCADE_LIVE_HOLDINGS flag set (see cascade-data-engine/README.md) — the
// UI must surface this, never present synthetic output as a real read on
// mechanical flow pressure.
//
// A `pressure` value of `null` is not "zero pressure" — it means
// quant-infra/cascade/pressure.py's compute_pressure() had no usable leg
// for that constituent (missing flow, missing typical_volume, etc.) and
// correctly abstained rather than fabricate a number. `n_products_used`
// vs. `n_products_total` tells you how partial that coverage was; see
// `warnings` for exactly why each excluded leg was excluded.

export type CascadeDataProvenance = "synthetic-demo" | "live";

export interface CascadePressureRow {
  constituent: string; // ticker
  pressure: number | null; // NaN in Python serializes to null in JSON
  n_products_total: number;
  n_products_used: number;
  any_proxy: boolean;
}

export interface CascadeExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  funds: string[]; // full starter universe this engine tracks
  funds_used: string[]; // funds whose fetch actually succeeded this run
  skipped_funds: string[]; // "TICKER: <reason>" for any fund that failed
  disclaimer: string;
  data_provenance: CascadeDataProvenance;
  pressure: CascadePressureRow[];
  skipped_products: string[]; // products (funds) excluded from every leg they'd contribute
  warnings: string[]; // per-leg exclusion reasons, straight from pressure.py
}

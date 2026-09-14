// WW-EARNINGS engine — website handoff contract (schema v1.0.0).
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

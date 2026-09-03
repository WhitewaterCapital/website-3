// WW-GRAPH engine — website handoff contract (schema v1.0.0).
// Mirrors graph-engine/ge/export.py. The site types its read against this.
//
// Same honesty rules as the other engines: `half_life_days` is populated ONLY
// when `half_life_significant` is true (a Dickey-Fuller-gated AR(1)/OU fit on
// the residual's own history — see graph-engine/ge/reversion.py). A name with
// too little residual history gets `confidence: "insufficient"` and both
// half-life fields null/false — never a fabricated number.
//
// `data_provenance` distinguishes a real, live-priced export from the
// synthetic-demo output this sandbox can currently produce (see
// graph-engine/README.md "Current status") — the UI must surface this, never
// present synthetic output as a real market read.

export type GraphConfidence = "significant" | "not_significant" | "insufficient";
export type GraphDataProvenance = "synthetic-demo" | "live";

export interface GraphResidual {
  ticker: string;
  diffused_value: number | null; // what the name's graph neighbours implied
  residual: number | null;       // actual signal - diffused_value
  residual_z: number | null;     // residual, sector-neutralized and cross-sectionally z-scored
  half_life_days: number | null; // null unless half_life_significant is true
  half_life_significant: boolean;
  confidence: GraphConfidence;
}

export interface GraphExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  universe: string[];
  disclaimer: string;
  data_provenance: GraphDataProvenance;
  residuals: GraphResidual[];
}

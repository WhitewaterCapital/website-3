// Intra / Exitus engine — website handoff contract (schema v1.0.0).
// Mirrors intra-exitus-engine/ie/export.py. The site types its read against this.
// Same honesty rules: the engine ABSTAINS (confidence "insufficient", null levels)
// when there is no clean setup — the UI must show that, never invent levels.

export type PlanConfidence = "actionable" | "watch" | "insufficient";

export interface IntraExitusPlan {
  ticker: string;
  regime: string; // "trend" | "mean-revert" | "high-vol"
  bias: string; // "long" | "short" | "none"
  confidence: PlanConfidence;
  entryZone: [number, number] | null;
  stop: number | null;
  targets: number[];
  expectedR: number | null; // expectancy in R (p·R − (1−p))
  sizingPct: number | null;
  timeStop: string;
  rationale: string;
  invalidations: string[];
  lastClose: number;
  asOf: string;
}

export interface IntraExitusExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  universe: string[];
  disclaimer: string;
  plans: IntraExitusPlan[];
}

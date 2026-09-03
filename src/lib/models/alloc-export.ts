// WW-ALLOC capital allocator — website handoff contract (schema v0.1.0).
// Mirrors quant-infra/alloc/solve.py's StrategyInput / SolverConfig / SolveLog
// dataclasses field-for-field (see that module's own docstring for the
// pipeline: shrink -> score -> solve). Same seam pattern as
// src/lib/models/state-export.ts / chaos-export.ts: the UI types its data
// against THIS contract, not the file location — production later swaps only
// the read in `src/lib/alloc.ts` for a query returning the same AllocExport
// shape, no UI change.
//
// IMP-05 (dashboard allocator panel). REAL STATUS TODAY: solve.py is a pure
// function over caller-supplied StrategyInput — there is no persisted history,
// no live strategy-return feed, and no Next.js-callable bridge to the Python
// process at request time. `public/data/alloc/latest.json` is therefore a
// STATIC, CLEARLY-LABELED SAMPLE export representing one hypothetical solve
// call, built from solve.py's own vocabulary and field names so it will read
// correctly the moment a real export lands. `generatedBy` says so explicitly;
// the UI must surface that string, never present these numbers as a live run.

// One strategy's inputs, mirroring solve.py's StrategyInput dataclass.
export interface AllocStrategyInput {
  name: string;
  expected_edge_raw: number;
  live_track_record_length: number; // number of live observations backing the edge
  uncertainty: number; // >= 0, e.g. std error of the edge estimate
  cost_at_size: number; // >= 0, expected cost penalty at the proposed size
  previous_budget: number; // prior allocation (>= 0)
  shadow_mode: boolean; // true => hard-zero budget regardless of score
  cap: number | null; // per-strategy hard cap, null => config.default_cap applies
}

// One strategy's solved outcome — shrink_edge() -> score_strategy() -> solve()
// (see solve.py), plus the current-vs-previous budget the dashboard needs.
export interface AllocStrategyResult {
  name: string;
  shrunk_edge: number; // expected_edge_raw shrunk by live track record (shrink_edge())
  uncertainty_penalty_term: number; // config.uncertainty_penalty * uncertainty
  cost_penalty_term: number; // config.cost_penalty * cost_at_size
  score: number; // shrunk_edge - uncertainty_penalty_term - cost_penalty_term
  previous_budget: number;
  budget: number; // the solved current budget (SolveLog.solution[name])
  delta: number; // budget - previous_budget
  shadow_mode: boolean;
  // Entries from SolveLog.active_constraints that name THIS strategy
  // specifically (e.g. "shadow_zero:<name>", "nan_score_zero:<name>"), so the
  // UI can show "why did the budget not move / move to zero" per row without
  // re-deriving it from the flat active_constraints list.
  binding_constraints: string[];
}

// Mirrors solve.py's SolverConfig dataclass — shown so a member can see the
// levers behind the score/solve, not just the outputs.
export interface AllocSolverConfig {
  prior_pseudo_obs: number;
  uncertainty_penalty: number;
  cost_penalty: number;
  risk_aversion: number;
  turnover_penalty: number;
  default_cap: number;
  total_gross_limit: number;
  max_step_fraction: number;
}

// ---------------------------------------------------------------------------
// Top-level document written to public/data/alloc/latest.json
// ---------------------------------------------------------------------------
export interface AllocExport {
  schema_version: string; // "0.1.0"
  engine_version: string; // quant-infra/alloc package version
  generated_at: string; // ISO timestamp the file was written
  as_of: string; // ISO date/timestamp the inputs are current to
  config: AllocSolverConfig;
  strategies: AllocStrategyResult[];
  // Mirrors SolveLog.active_constraints verbatim (includes "total_gross_limit"
  // always, plus any "shadow_zero:<name>" / "nan_score_zero:<name>" entries).
  active_constraints: string[];
  fallback_used: boolean; // SolveLog.fallback_used — solver fell back to previous_budget
  fallback_reason: string | null; // SolveLog.fallback_reason
  feasible: boolean; // SolveLog.feasible
  objective_value: number | null; // SolveLog.objective_value
  disclaimer: string; // MUST be shown — research allocation, not an order
  // Honest provenance label — "WW-ALLOC (sample)" today (see module doc
  // above); becomes "WW-ALLOC" once a real solve.py run is exported here.
  generatedBy: string;
}

// WW-STATE market state vector — website handoff contract (schema v1.0.0).
// Mirrors engine/incepta/state.py's StateVector/build_state_export. The UI
// types its data against this, NOT the file location — production later
// swaps only the read in `src/lib/state.ts` for a Supabase query returning
// the same StateExport shape; no UI change.
//
// Seven elements describe what kind of market this is right now. Two of them
// — the implied-vol term structure inside `volatility.raw` and the whole
// `slippage` element — are honestly `null` today because this engine has no
// live options feed and no realised broker fills yet. The UI MUST treat
// `available: false` (or a null `value`) as "unknown, not zero", show it as
// such, and lean on `reason` / `notes` to explain why.

export type StateElementName =
  | "volatility"
  | "dispersion"
  | "correlation"
  | "breadth"
  | "trend"
  | "slippage"
  | "liquidity";

export interface ElementReading {
  available: boolean;
  // The single standardized (z-score-like) reading the allocator reads.
  // Always null when `available` is false.
  value: number | null;
  // Element-specific numbers (per-window breakdowns, levels, sub-scores) —
  // never fabricated, only what was actually computed from real inputs.
  raw: Record<string, unknown>;
  // Documents partial gaps even when `available` is true (e.g. volatility
  // has realised vol but not implied vol).
  notes: string[];
  // Set when `available` is false — why this element could not be computed.
  reason: string | null;
}

export interface StateVector {
  schema_version: string;
  element_order: StateElementName[];
  as_of: string;
  volatility: ElementReading;
  dispersion: ElementReading;
  correlation: ElementReading;
  breadth: ElementReading;
  trend: ElementReading;
  slippage: ElementReading;
  liquidity: ElementReading;
}

export interface StatePlainLanguage {
  volatility: string;
  dispersion: string;
  correlation: string;
  breadth: string;
  trend: string;
  slippage: string;
  liquidity: string;
}

export interface StateExport {
  schema_version: string;
  engine_version: string;
  generated_at: string;
  as_of: string;
  state_vector: StateVector;
  plain_language: StatePlainLanguage;
  disclaimer: string;
  // Present only on demo/synthetic exports (see engine/incepta/state.py's
  // one-off fixture run) — absent once a live universe feed is wired in.
  universe_note?: string;
}

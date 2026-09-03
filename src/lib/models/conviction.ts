// ═══════════════════════════════════════════════════════════════════════════
// IMP-15 — Conviction scores absorb the new models without being taken over
// by them.
//
// v1.0 established the rule this module extends: component scores must stay
// SECURITY SPECIFIC — a composite conviction score is built out of named,
// legible pieces, not one opaque blend, so a reader can ask "why is this
// number what it is" and get an answer per contributing model. Three new
// model outputs now want a slot in that composite: the weekly cross-sectional
// forecast (weekly-export.ts / WeeklyForecast), the graph-residual mean-
// reversion read (graph-export.ts / GraphResidual), and the cascade/chaos
// exposure read (chaos-export.ts / ChaosReading, whose own state label
// literally includes "cascade"). None of the three are registered in
// registry.ts yet (see WEEKLY_FORECAST_SLOT / GRAPH_RESIDUAL_SLOT /
// CASCADE_EXPOSURE_SLOT below) — this module defines the SLOTS and the
// capping mechanics now, so wiring in the real models later is a matter of
// producing a `ConvictionSlotInput` from each one's real export, not
// redesigning how conviction absorbs them.
//
// THE RISK THIS GUARDS AGAINST: a composite conviction score is meant to
// represent a multi-year-relevant read. The weekly forecast in particular
// runs on a "1w" horizon (see horizons.ts's HORIZON_REGISTRY convention) —
// a single bad week, or one that happens to disagree loudly with everything
// else, must not be able to swing a structural conviction call on its own.
// The same discipline applies to the graph residual and the cascade read:
// each is one more opinion, not a veto.
//
// CAPPING APPROACH CHOSEN (documented per the spec's request to pick one):
// each slot's contribution to the composite is computed as a signed delta
// in composite points, and that delta is clamped to
// ±MAX_SINGLE_MODEL_SWING BEFORE it is added to the base score. This is the
// "clamp/scale each slot's marginal contribution directly" approach, not the
// "fixed weight-share of the total" approach — it was chosen because it
// makes the "done when" criterion ("removing any one model changes the
// composite by a bounded documented amount") a proven property of the
// arithmetic rather than an emergent one: because the final composite is
// `clamp(baseScore + Σ delta_i, 0, 100)` and `clamp` is 1-Lipschitz (moving
// its argument by X never moves its output by more than X), removing any
// one slot's delta_i (|delta_i| <= MAX_SINGLE_MODEL_SWING by construction)
// changes the final composite by at most MAX_SINGLE_MODEL_SWING — see
// `computeConviction`'s doc comment for the short proof, and
// `marginalImpact` on the result, which reports the actual measured amount
// per slot (computed by literally recomputing the composite with that slot
// removed, not just trusting the algebra) so a caller/test can read the
// "done when" criterion directly off the output.
//
// A fixed weight-share cap (the spec's alternative) was not chosen because
// it caps a slot's SHARE of the total pull, which still lets a single
// extreme, highly-confident slot dominate when the other slots are weak or
// absent (e.g. one slot alone: its "share" is 100% no matter what the cap
// is) — a direct points cap is the one that actually bounds the absolute
// swing regardless of how many other slots are present, which is what the
// spec's "a one week signal cannot on its own shift a multi year conviction
// score" is asking for.
//
// RELATIONSHIP TO horizons.ts (documented, not duplicated): horizons.ts
// exists to REJECT blending two models' outputs across undocumented
// horizons entirely (`assertCombinable` throws). This module does the
// opposite on purpose: IMP-15 assumes each of the three new models gets an
// explicit, named, CAPPED slot rather than being silently blended into one
// number — the cap is what makes it safe to let a "1w"-horizon weekly
// forecast contribute to a multi-year composite at all. `getHorizon` is
// still consulted here (see `slotContributions[i].horizon` below) purely for
// transparency — so a caller/reviewer can see at a glance which of a
// composite's inputs run on a much shorter clock than the composite itself
// — not to gate anything. The two modules' concerns overlap (both are about
// combining outputs across models with different time horizons) but solve
// different problems: horizons.ts refuses an undocumented blend outright;
// this module documents and bounds a deliberate one.
//
// RELATIONSHIP TO disagreement.ts (documented, not duplicated): that module
// answers "how much do same-kind directional calls disagree". This module
// answers a different question — "how much should a new model be allowed to
// move an existing composite" — and does not compute or depend on
// disagreement; the two can be used side by side on the same slot inputs
// (both accept a `{ modelId, confidence }`-shaped input) without either one
// needing to know about the other.
// ═══════════════════════════════════════════════════════════════════════════

import { getHorizon, type HorizonBand } from "./horizons";

// ---------------------------------------------------------------------------
// Slot input.
//
// `score` convention: signed, -100..100, "directional/quality read" — the
// SAME convention already used elsewhere in this codebase for a single
// model's raw opinion (DirectionalOutput.direction in disagreement.ts,
// EquitySignal.score and SectorRead.sentiment in models/types.ts). This is
// deliberately NOT the 0..100 unsigned scale StressVerdict.conviction uses —
// that scale is for a already-composited, "how sure are we" number; a slot
// here is one model's raw signed opinion (which way, how strongly) that this
// module itself turns into a bounded contribution to a 0..100 composite.
// ---------------------------------------------------------------------------
export interface ConvictionSlotInput {
  modelId: string; // matches a HORIZON_REGISTRY / registry.ts id where one exists
  score: number; // -100 (strongly negative) .. +100 (strongly positive)
  confidence: number; // 0..1 — how much weight this model's own read should carry
}

// ---------------------------------------------------------------------------
// Explicit, named slots — per spec, not a generic list. Real model ids
// (matching whatever id registry.ts eventually assigns them) belong here
// once weekly-export.ts / graph-export.ts / chaos-export.ts get a real
// EvaluatorModel/MacroModel/EquityModel-style wrapper and a registry.ts
// entry. Until then these are RESERVED placeholder ids — none of the three
// appear in registry.ts's MODELS or horizons.ts's HORIZON_REGISTRY today —
// following the exact same "reserved slot" convention horizons.ts already
// uses for its own "your-macro-algo" entry (see horizons.ts).
// ---------------------------------------------------------------------------
export const WEEKLY_FORECAST_SLOT = "ww-weekly"; // WeeklyForecast (weekly-export.ts) — "1w" horizon
export const GRAPH_RESIDUAL_SLOT = "ww-graph"; // GraphResidual (graph-export.ts) — mean-reversion half-life read
export const CASCADE_EXPOSURE_SLOT = "ww-cascade"; // ChaosReading cascade exposure (chaos-export.ts) — intraday-to-multiday

// ---------------------------------------------------------------------------
// The cap.
//
// No single slot may move the composite by more than this many points, in
// either direction, full stop — regardless of how extreme its score is or
// how confident it claims to be. Chosen relative to distresse.ts's own
// rating bands (go: avg > 25, no-go: avg < -20, i.e. roughly a 20-45 point
// gap between adjacent rating thresholds on that model's scale): 8 points is
// comfortably too small for any ONE new slot to flip a rating on its own,
// while still being large enough that three slots agreeing in the same
// direction can add up to a genuinely material (up to 24-point) move — the
// cap bounds a single model's influence, not the composite's ability to move
// at all when several new models agree.
// ---------------------------------------------------------------------------
export const MAX_SINGLE_MODEL_SWING = 8;

// How much the base composite (pre-existing v1.0 score/confidence) counts
// for, in weight-units, when blending an overall confidence read alongside
// the new slots — see computeConviction's `confidence` output. Documented
// as its own constant rather than a bare "1" so the blend's weighting is a
// visible decision: the base composite counts as much as exactly one slot.
const BASE_CONFIDENCE_WEIGHT = 1;

function clamp(x: number, lo: number, hi: number): number {
  if (Number.isNaN(x)) return lo; // never propagate NaN into a displayed score
  return Math.min(hi, Math.max(lo, x));
}

// Per-slot signed contribution, in composite points, BEFORE any cap is
// applied. `score` and `confidence` are clamped to their documented ranges
// first — this module never trusts an out-of-range caller input to stay
// out-of-range, it defends its own invariants at the boundary.
function rawSlotDelta(slot: ConvictionSlotInput): number {
  const score = clamp(slot.score, -100, 100);
  const confidence = clamp(slot.confidence, 0, 1);
  return (score / 100) * MAX_SINGLE_MODEL_SWING * confidence;
}

// The cap, applied explicitly (not merely implied by rawSlotDelta's shape,
// which is already <= MAX_SINGLE_MODEL_SWING for in-range inputs) — this is
// the literal "implement the actual capping logic" mechanism the spec asks
// for, and it stays correct even if rawSlotDelta's formula is ever changed
// to something that isn't automatically bounded.
function cappedSlotDelta(slot: ConvictionSlotInput): number {
  return clamp(rawSlotDelta(slot), -MAX_SINGLE_MODEL_SWING, MAX_SINGLE_MODEL_SWING);
}

// Composite for a given base + slot set, per-slot capped deltas included.
// Shared by computeConviction's "all slots" pass and its "slot i removed"
// passes (used to derive marginalImpact) so both use IDENTICAL arithmetic —
// marginalImpact is a measured difference between two real evaluations of
// this same function, never a formula assumed to match it.
function compositeFor(baseScore: number, slots: ConvictionSlotInput[]): { composite: number; deltas: number[] } {
  const base = clamp(baseScore, 0, 100);
  const deltas = slots.map(cappedSlotDelta);
  const composite = clamp(base + deltas.reduce((s, d) => s + d, 0), 0, 100);
  return { composite, deltas };
}

// Thin wrapper around horizons.ts's getHorizon, collapsing "not found" and
// an actually-declared "unspecified" band to the same value — this module
// only ever reads a slot's horizon for transparency (see
// slotContributions[i].horizon), never to gate anything, so it does not need
// to tell the two cases apart. Exported so a caller can look up a slot's
// declared horizon the same way this module does, without reaching into
// horizons.ts directly.
export function getHorizonBandFor(modelId: string): HorizonBand | "unspecified" {
  return getHorizon(modelId)?.band ?? "unspecified";
}

export interface ConvictionSlotContribution {
  modelId: string;
  delta: number; // this slot's actual, capped contribution to the composite (signed points)
  // getHorizon(modelId)'s band, or "unspecified" for both an actually
  // "unspecified" band AND an unregistered modelId (e.g. the three
  // reserved slot ids above, today) — this module only reads horizons.ts,
  // it never gates on it, so it does not need to distinguish the two.
  horizon: HorizonBand | "unspecified";
}

export interface ConvictionMarginalImpact {
  modelId: string;
  // composite (with this slot) minus composite (with this slot removed,
  // all else unchanged). Positive = this slot is currently pulling the
  // composite up by this many points; negative = pulling it down. Bounded
  // in magnitude by MAX_SINGLE_MODEL_SWING — see computeConviction's doc
  // comment for why that bound holds even after the final 0..100 clamp.
  impact: number;
}

export interface ConvictionResult {
  composite: number; // 0..100
  // Confidence-weighted blend of baseConfidence and each slot's own
  // confidence (base counts as BASE_CONFIDENCE_WEIGHT slot-units) — included
  // so a caller gets one number for "how much to trust `composite`", not
  // just the composite itself. With zero slots this reduces to exactly
  // baseConfidence.
  confidence: number; // 0..1
  slotContributions: ConvictionSlotContribution[];
  marginalImpact: ConvictionMarginalImpact[];
}

// ---------------------------------------------------------------------------
// computeConviction — absorb zero or more new-model slots into a pre-
// existing v1.0 composite (baseScore/baseConfidence), without letting any
// one of them take it over.
//
// PROOF that marginalImpact is bounded by MAX_SINGLE_MODEL_SWING (the
// "done when" criterion): let D = Σ deltas over all slots, and D_i = D
// minus slot i's own (already-capped) delta_i, where |delta_i| <=
// MAX_SINGLE_MODEL_SWING by construction (cappedSlotDelta). The composite
// with all slots is clamp(base + D, 0, 100); the composite with slot i
// removed is clamp(base + D_i, 0, 100) = clamp((base + D) - delta_i, 0,
// 100). `clamp(x, lo, hi)` is 1-Lipschitz: |clamp(x) - clamp(y)| <= |x -
// y| for any x, y. Taking x = base + D and y = x - delta_i gives
// |clamp(x) - clamp(y)| <= |delta_i| <= MAX_SINGLE_MODEL_SWING. So no
// single slot's removal can move the composite by more than
// MAX_SINGLE_MODEL_SWING, REGARDLESS of how many other slots are present or
// how the 0..100 clamp lands. `marginalImpact` below reports the actual
// measured value (not this algebraic bound) for each slot.
// ---------------------------------------------------------------------------
export function computeConviction(
  baseScore: number,
  baseConfidence: number,
  slots: ConvictionSlotInput[],
): ConvictionResult {
  const all = compositeFor(baseScore, slots);

  const slotContributions: ConvictionSlotContribution[] = slots.map((slot, i) => ({
    modelId: slot.modelId,
    delta: all.deltas[i],
    horizon: getHorizonBandFor(slot.modelId),
  }));

  const marginalImpact: ConvictionMarginalImpact[] = slots.map((slot, i) => {
    const without = compositeFor(
      baseScore,
      slots.filter((_, j) => j !== i),
    );
    return { modelId: slot.modelId, impact: all.composite - without.composite };
  });

  const clampedBaseConfidence = clamp(baseConfidence, 0, 1);
  const confidenceWeightTotal = BASE_CONFIDENCE_WEIGHT + slots.length;
  const confidence =
    (clampedBaseConfidence * BASE_CONFIDENCE_WEIGHT +
      slots.reduce((s, slot) => s + clamp(slot.confidence, 0, 1), 0)) /
    confidenceWeightTotal;

  return {
    composite: all.composite,
    confidence,
    slotContributions,
    marginalImpact,
  };
}

// ---------------------------------------------------------------------------
// namesAreDistinguishable — the numeric half of v1.0's rule that two
// different names, fed different inputs, cannot come out the other end with
// near-identical scores (and, per v1.0, near-identical language — this
// module produces no language, so it checks only the number it owns).
//
// This is a PURE PROPERTY CHECK, not a runtime guard: it has no side
// effects, throws nothing, and is meant to be asserted on in tests (see
// scripts/verify-conviction.mjs) to prove the capping/rounding in this
// module does not accidentally wash out genuinely different inputs into the
// same composite. It is intentionally NOT wired into computeConviction
// itself — computeConviction has no notion of "the other name" to compare
// against.
//
// "Meaningfully different" is documented, not left implicit: two input sets
// are meaningfully different if baseScore, baseConfidence, or any matched
// slot's score/confidence differs by more than the thresholds below. A slot
// present on only one side is compared against an absent (0, 0) slot on the
// other — dropping or adding a whole slot is itself a meaningful difference.
// When inputs are NOT meaningfully different, this returns true vacuously
// (nothing requires the composites to differ).
// ---------------------------------------------------------------------------
export interface ConvictionInputs {
  baseScore: number;
  baseConfidence: number;
  slots: ConvictionSlotInput[];
}

export const MEANINGFUL_BASE_SCORE_DIFF = 15; // points, 0..100 base scale
export const MEANINGFUL_BASE_CONFIDENCE_DIFF = 0.15; // 0..1 scale
export const MEANINGFUL_SLOT_SCORE_DIFF = 15; // points, -100..100 slot scale
export const MEANINGFUL_SLOT_CONFIDENCE_DIFF = 0.15; // 0..1 scale

// Composites closer together than this are treated as "collapsed" — i.e.
// indistinguishable — when the inputs behind them were meaningfully
// different. Deliberately larger than ordinary floating-point noise but
// much smaller than MAX_SINGLE_MODEL_SWING, so this catches the capping
// mechanism erasing a real difference, not normal rounding.
export const DISTINGUISHABILITY_EPSILON = 1;

function inputsAreMeaningfullyDifferent(a: ConvictionInputs, b: ConvictionInputs): boolean {
  if (Math.abs(a.baseScore - b.baseScore) > MEANINGFUL_BASE_SCORE_DIFF) return true;
  if (Math.abs(a.baseConfidence - b.baseConfidence) > MEANINGFUL_BASE_CONFIDENCE_DIFF) return true;

  const byId = (slots: ConvictionSlotInput[]) => new Map(slots.map((s) => [s.modelId, s]));
  const mapA = byId(a.slots);
  const mapB = byId(b.slots);
  const allIds = new Set([...mapA.keys(), ...mapB.keys()]);

  for (const id of allIds) {
    const sa = mapA.get(id);
    const sb = mapB.get(id);
    const scoreA = sa?.score ?? 0;
    const scoreB = sb?.score ?? 0;
    const confA = sa?.confidence ?? 0;
    const confB = sb?.confidence ?? 0;
    if (Math.abs(scoreA - scoreB) > MEANINGFUL_SLOT_SCORE_DIFF) return true;
    if (Math.abs(confA - confB) > MEANINGFUL_SLOT_CONFIDENCE_DIFF) return true;
  }

  return false;
}

export function namesAreDistinguishable(
  resultA: ConvictionResult,
  inputsA: ConvictionInputs,
  resultB: ConvictionResult,
  inputsB: ConvictionInputs,
): boolean {
  if (!inputsAreMeaningfullyDifferent(inputsA, inputsB)) return true; // nothing required to differ
  return Math.abs(resultA.composite - resultB.composite) > DISTINGUISHABILITY_EPSILON;
}

// ═══════════════════════════════════════════════════════════════════════════
// IMP-21 — Disagreement scalar.
//
// When more than one model (or the same model read against different
// evidence) produces a directional call on the same strategy/horizon bucket,
// the desk wants one number for "how much do these actually disagree",
// weighted by how confident each call is — two low-confidence calls pointing
// opposite ways matter less than two high-confidence calls doing the same.
//
// "Done when" (IMP-21's acceptance criterion): a pure function returns a
// disagreement scalar plus a boolean reviewFlag that trips above a documented
// threshold — so a bucket with genuinely split, confident opinions gets
// surfaced for human review instead of silently averaged away.
//
// This module is pure and self-contained: no I/O, no registry lookups, no
// side effects, no dependency on any specific model's shape. Callers assemble
// the DirectionalOutput[] themselves (e.g. one entry per model's read on a
// ticker, or per strategy variant) and pass it in.
// ═══════════════════════════════════════════════════════════════════════════

export interface DirectionalOutput {
  modelId: string;
  direction: number; // signed strength on a -100..100 scale (e.g. a sentiment/score)
  confidence: number; // 0..1 — how much weight this call should carry
}

export interface DisagreementResult {
  scalar: number; // 0..100 — 0 is total agreement, 100 is maximal split
  reviewFlag: boolean; // true once scalar exceeds REVIEW_THRESHOLD
  n: number; // how many outputs actually went into this (0 or 1 => no disagreement)
  meanDirection: number; // confidence-weighted mean, for context alongside the scalar
}

// Above this, the split is treated as material enough to route to a human
// rather than average away. Documented here so the cutoff is a visible
// decision, not a magic number buried at a call site.
export const REVIEW_THRESHOLD = 40;

// Formula: confidence-weighted standard deviation of each model's signed
// direction (direction ∈ [-100, 100]).
//
//   weighted mean:      m = Σ(cᵢ·dᵢ) / Σcᵢ
//   weighted variance:  v = Σ(cᵢ·(dᵢ − m)²) / Σcᵢ
//   scalar:             round(√v)
//
// √v (not v) is used so the scalar stays in the same units as `direction` — a
// "typical confidence-weighted spread", in points on the same -100..100 axis
// the models themselves report on — rather than squared points, which keeps
// REVIEW_THRESHOLD legible against that axis.
//
// Inputs with confidence <= 0, or a non-finite direction, are dropped before
// the calculation — a model that abstained or reported no confidence should
// not be able to inflate (or silently zero out) the disagreement read.
export function computeDisagreement(outputs: DirectionalOutput[]): DisagreementResult {
  const usable = outputs.filter((o) => o.confidence > 0 && Number.isFinite(o.direction));

  if (usable.length < 2) {
    const meanDirection = usable.length === 1 ? Math.round(usable[0].direction) : 0;
    return { scalar: 0, reviewFlag: false, n: usable.length, meanDirection };
  }

  const totalWeight = usable.reduce((s, o) => s + o.confidence, 0);
  const meanDirection = usable.reduce((s, o) => s + o.confidence * o.direction, 0) / totalWeight;
  const weightedVariance =
    usable.reduce((s, o) => s + o.confidence * (o.direction - meanDirection) ** 2, 0) / totalWeight;
  const scalar = Math.min(100, Math.round(Math.sqrt(weightedVariance)));

  return {
    scalar,
    reviewFlag: scalar > REVIEW_THRESHOLD,
    n: usable.length,
    meanDirection: Math.round(meanDirection),
  };
}

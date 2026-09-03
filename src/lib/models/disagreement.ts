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

// ═══════════════════════════════════════════════════════════════════════════
// IMP-16 — two different kinds of disagreement, kept SEPARATE.
//
// `computeDisagreement` above answers "how much do these calls disagree",
// as one mixed scalar. IMP-16's complaint is that averaging together (a)
// models pointing opposite ways and (b) models agreeing on direction but not
// on strength hides both: a bucket where five models are all mildly bullish
// can produce the same blended scalar as a bucket split evenly bullish vs.
// bearish, and only the second one is the kind that should stop a human.
//
// `classifyDisagreement` reports the two kinds side by side instead of
// blending them:
//
//   directionalDisagreement — models pointing OPPOSITE ways. Defined as: both
//   the positive-direction group and the negative-direction group carry a
//   "meaningful" share of the total confidence weight, where "meaningful" is
//   documented as >= MIN_MINORITY_WEIGHT_SHARE (20%) of total weight each.
//   This is a confidence-weighted rule, not a headcount rule: two low-
//   confidence dissenters against one high-confidence call do not trip it,
//   matching the same "weight by confidence" spirit as computeDisagreement.
//
//   confidenceDisagreement — models that AGREE on direction but not on
//   strength. Defined as the confidence-weighted standard deviation of
//   |direction| among the outputs sharing the majority sign (by weight) —
//   same √variance-of-a-signed-axis construction as computeDisagreement's
//   scalar, so the two numbers live on the same 0..100 axis and are directly
//   comparable, but this one is computed only within the agreeing side, so a
//   directional split can never leak into it.
//
//   reviewFlag — per the spec, "high conviction directional disagreement
//   still triggers human review": fires when directionalDisagreement is true
//   AND mean confidence across usable outputs exceeds
//   HIGH_CONVICTION_CONFIDENCE_THRESHOLD. Confidence disagreement alone,
//   however large, never sets this flag — only the directional kind does.
// ═══════════════════════════════════════════════════════════════════════════

// A minority side below this share of total confidence weight is treated as
// noise (e.g. one low-confidence dissenter), not a genuine directional split.
// Documented here so the cutoff is a visible decision, not a magic number.
export const MIN_MINORITY_WEIGHT_SHARE = 0.2;

// "High conviction" per the spec's review trigger: mean confidence across
// usable outputs above this bar. Below it, even a clean directional split is
// treated as low-conviction noise, not something worth a human's time.
export const HIGH_CONVICTION_CONFIDENCE_THRESHOLD = 0.6;

export interface DisagreementClassification {
  n: number; // usable outputs that went into this (confidence > 0, finite direction)
  // Models pointing opposite ways, weighted by confidence — see module doc.
  directionalDisagreement: boolean;
  directionalDetail: {
    positiveWeightShare: number; // 0..1, share of total confidence with direction > 0
    negativeWeightShare: number; // 0..1, share of total confidence with direction < 0
  };
  // Agreeing on direction, not on strength — 0..100, same axis as
  // computeDisagreement's scalar. 0 when fewer than 2 outputs share the
  // majority sign (nothing to compare strength against).
  confidenceDisagreement: number;
  meanConfidence: number; // 0..1 — the "conviction" the review trigger reads
  highConviction: boolean; // meanConfidence > HIGH_CONVICTION_CONFIDENCE_THRESHOLD
  // Fires ONLY on directional disagreement at high conviction — never on
  // confidence disagreement alone, per the spec.
  reviewFlag: boolean;
}

export function classifyDisagreement(outputs: DirectionalOutput[]): DisagreementClassification {
  const usable = outputs.filter((o) => o.confidence > 0 && Number.isFinite(o.direction));

  if (usable.length < 2) {
    const meanConfidence = usable.length === 1 ? usable[0].confidence : 0;
    return {
      n: usable.length,
      directionalDisagreement: false,
      directionalDetail: { positiveWeightShare: 0, negativeWeightShare: 0 },
      confidenceDisagreement: 0,
      meanConfidence,
      highConviction: meanConfidence > HIGH_CONVICTION_CONFIDENCE_THRESHOLD,
      reviewFlag: false,
    };
  }

  const totalWeight = usable.reduce((s, o) => s + o.confidence, 0);
  const posWeight = usable.filter((o) => o.direction > 0).reduce((s, o) => s + o.confidence, 0);
  const negWeight = usable.filter((o) => o.direction < 0).reduce((s, o) => s + o.confidence, 0);
  const positiveWeightShare = posWeight / totalWeight;
  const negativeWeightShare = negWeight / totalWeight;
  const directionalDisagreement =
    positiveWeightShare >= MIN_MINORITY_WEIGHT_SHARE && negativeWeightShare >= MIN_MINORITY_WEIGHT_SHARE;

  // Confidence disagreement: spread in |direction| within the majority-sign
  // side only — a directional split on the other side must not inflate this.
  const majoritySign = posWeight >= negWeight ? 1 : -1;
  const sameSignGroup = usable.filter((o) => Math.sign(o.direction) === majoritySign || o.direction === 0);
  let confidenceDisagreement = 0;
  if (sameSignGroup.length >= 2) {
    const groupWeight = sameSignGroup.reduce((s, o) => s + o.confidence, 0);
    const meanMag = sameSignGroup.reduce((s, o) => s + o.confidence * Math.abs(o.direction), 0) / groupWeight;
    const variance =
      sameSignGroup.reduce((s, o) => s + o.confidence * (Math.abs(o.direction) - meanMag) ** 2, 0) / groupWeight;
    confidenceDisagreement = Math.min(100, Math.round(Math.sqrt(variance)));
  }

  const meanConfidence = usable.reduce((s, o) => s + o.confidence, 0) / usable.length;
  const highConviction = meanConfidence > HIGH_CONVICTION_CONFIDENCE_THRESHOLD;
  const reviewFlag = directionalDisagreement && highConviction;

  return {
    n: usable.length,
    directionalDisagreement,
    directionalDetail: { positiveWeightShare, negativeWeightShare },
    confidenceDisagreement,
    meanConfidence,
    highConviction,
    reviewFlag,
  };
}

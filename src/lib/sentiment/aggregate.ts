import type { Headline, TickerSentimentAggregate } from "./types";

// ═══════════════════════════════════════════════════════════════════════════
// WW-SENTIMENT — aggregation.
//
// Pure function, no I/O, no model calls — takes already-scored headlines
// (real FinBERT scores and/or labeled keyword-fallback scores, see
// finbert.ts / keywordFallback.ts) and turns them into ONE documented
// aggregate. Exported standalone (not inlined into route.ts) so
// scripts/verify-sentiment.mjs can hand-trace it against fixed example
// headline sets without a network call or a test framework — see that
// script for the worked examples this doc comment's numbers come from.
//
// THE MATH, in full:
//
// 1. Per-headline signed value. Each scored headline (method "finbert" or
//    "keyword-fallback" — "unavailable" ones are excluded entirely, they
//    carry no score to weight) has a "full-strength" signed value based on
//    its label ALONE:
//        value_i = directionOf(label_i) * 100
//    where directionOf(positive) = +1, directionOf(negative) = -1,
//    directionOf(neutral) = 0. This keeps `value_i` on the same signed
//    -100..100 scale used everywhere else in this codebase
//    (ConvictionSlotInput.score, Dimension.score).
//
// 2. Confidence-weighted average. The published `score` is
//        Σ(value_i * score_i) / Σ(score_i)
//    where score_i is the winning label's own confidence, 0..1 (FinBERT's
//    softmax probability, or the fallback's fixed 0.35 — see
//    keywordFallback.ts), used here as that headline's WEIGHT in the
//    average — NOT baked into value_i first and then weighted again. A
//    headline FinBERT is 95% sure is negative pulls the average much harder
//    than one it calls negative at only 40% confident, exactly once, not
//    quadratically. This is the "confidence-weighted average score" this
//    task asked for, as opposed to a flat mean of value_i.
//
// 3. Aggregate confidence — DELIBERATELY a different number from any single
//    headline's score, and from the composite `score` above. It is the
//    product of two independent, documented factors:
//        sampleWeight   = clamp(nScored / SAMPLE_SIZE_FOR_FULL_CONFIDENCE, 0, 1)
//        meanConfidence = mean(score_i) over scored headlines
//        confidence     = sampleWeight * meanConfidence
//    `sampleWeight` is the "2 headlines should carry much less confidence
//    than 20" requirement made literal: it ramps linearly from 0 at
//    nScored=0 to 1 at nScored=SAMPLE_SIZE_FOR_FULL_CONFIDENCE (10, chosen
//    as roughly a day or two of real coverage for an actively-discussed
//    name — see the constant below), and stays at 1 beyond that (more
//    headlines than 10 does not buy additional confidence past this floor;
//    it is a floor on trusting the SAMPLE, not a claim that 10 is enough to
//    be highly confident on its own — `meanConfidence` still caps the
//    product). `meanConfidence` is how sure the scorer(s) actually were, on
//    average, across whichever headlines got scored. Multiplying the two
//    means a large batch of low-confidence calls and a tiny batch of
//    high-confidence calls can land at similar aggregate confidence — both
//    are genuinely less trustworthy than a large batch of high-confidence
//    calls, for different reasons, and this formula treats them that way
//    rather than optimizing either factor away.
//
// 4. `method` on the aggregate: "finbert" if every scored headline used the
//    real model, "keyword-fallback" if every one used the crude fallback,
//    "mixed" if both occur in the same batch (e.g. FinBERT was reachable for
//    most headlines this run but rate-limited or briefly down for a few),
//    "none" if nScored === 0. A caller that only wants to gate on "was this
//    a real read" should check `method !== "keyword-fallback" &&
//    method !== "none"` rather than assuming the whole batch matches
//    `finbertConfigured` — a configured key can still partially fail per
//    request.
// ═══════════════════════════════════════════════════════════════════════════

export const SAMPLE_SIZE_FOR_FULL_CONFIDENCE = 10;

function directionOf(label: Headline["sentiment"]["label"]): number {
  if (label === "positive") return 1;
  if (label === "negative") return -1;
  return 0; // "neutral" and (defensively) any unrecognized value
}

export function computeAggregate(headlines: Headline[]): TickerSentimentAggregate {
  const n = headlines.length;

  if (n === 0) {
    return {
      abstained: true,
      abstainReason: "No recent headlines found for this ticker — nothing to score, so no read is shown.",
      n: 0,
      nScored: 0,
      counts: { positive: 0, negative: 0, neutral: 0, unavailable: 0 },
      score: null,
      confidence: 0,
      method: "none",
    };
  }

  const counts = { positive: 0, negative: 0, neutral: 0, unavailable: 0 };
  const scored = headlines.filter((h) => h.sentiment.method !== "unavailable");
  for (const h of headlines) {
    counts[h.sentiment.label as keyof typeof counts]++;
  }

  const usedFinbert = scored.some((h) => h.sentiment.method === "finbert");
  const usedFallback = scored.some((h) => h.sentiment.method === "keyword-fallback");
  const method: TickerSentimentAggregate["method"] =
    scored.length === 0 ? "none" : usedFinbert && usedFallback ? "mixed" : usedFinbert ? "finbert" : "keyword-fallback";

  if (scored.length === 0) {
    return {
      abstained: true,
      abstainReason: `Found ${n} headline${n === 1 ? "" : "s"} but could not score any of them (scorer unavailable for every one) — no read is shown rather than a fabricated one.`,
      n,
      nScored: 0,
      counts,
      score: null,
      confidence: 0,
      method: "none",
    };
  }

  let weightedSum = 0;
  let weightTotal = 0;
  let confidenceSum = 0;
  for (const h of scored) {
    const value = directionOf(h.sentiment.label) * 100; // full-strength signed value, per step 1 above
    weightedSum += value * h.sentiment.score; // weighted ONCE by this headline's own confidence, per step 2
    weightTotal += h.sentiment.score;
    confidenceSum += h.sentiment.score;
  }

  // weightTotal is guaranteed > 0 whenever scored.length > 0 UNLESS every
  // scored headline's own score is exactly 0 — a real FinBERT softmax
  // probability is never exactly 0, and the fallback's fixed 0.35 never is
  // either, so this guard exists purely so a future scorer with a genuine
  // 0-confidence output degrades to "no score" instead of a NaN, never so
  // it can silently mask a real bug.
  const score = weightTotal > 0 ? weightedSum / weightTotal : 0;
  const meanConfidence = confidenceSum / scored.length;
  const sampleWeight = Math.min(1, scored.length / SAMPLE_SIZE_FOR_FULL_CONFIDENCE);
  const confidence = sampleWeight * meanConfidence;

  return {
    abstained: false,
    abstainReason: null,
    n,
    nScored: scored.length,
    counts,
    score,
    confidence,
    method,
  };
}

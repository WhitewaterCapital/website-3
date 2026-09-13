import type { HeadlineSentiment } from "./types";

// ---------------------------------------------------------------------------
// CRUDE, VISIBLY-LABELED FALLBACK — used only when the real FinBERT call for
// a given headline failed (unreachable/unauthorized/rate-limited/loading —
// see finbert.ts's FinbertCallResult). Every result this produces carries
// `method: "keyword-fallback"`, never `"finbert"` — route.ts and the UI both
// key off that field, so a fallback score can never be presented as, or
// silently merged into, a real model read (this task's explicit rule).
//
// Same directional-not-authoritative spirit, and near-identical shape, as
// whitewatch/news/route.js's classifyThreat: a small hand-picked keyword
// list, first match wins, no weighting, no negation handling ("not bad" will
// misread as negative here) — a real fallback for resilience, not a
// pretend model.
// ---------------------------------------------------------------------------

const POSITIVE_KEYWORDS = [
  "beat", "beats", "surge", "surged", "soar", "soared", "rally", "rallied",
  "upgrade", "upgraded", "record profit", "record revenue", "raises guidance",
  "raised guidance", "outperform", "strong demand", "buyback", "expands",
  "wins contract", "approval", "approved", "profit jumps", "growth accelerates",
];

const NEGATIVE_KEYWORDS = [
  "miss", "missed", "plunge", "plunged", "slump", "slumped", "downgrade",
  "downgraded", "lawsuit", "sues", "sued", "probe", "investigation", "fraud",
  "recall", "layoffs", "job cuts", "warns", "warning", "cuts guidance",
  "lowers guidance", "bankruptcy", "default", "resigns", "resignation",
  "sell-off", "selloff", "underperform", "loss widens",
];

// Fixed, low confidence for every fallback score — this is a crude heuristic,
// never entitled to the same weight as a real model's own probability. Kept
// well under FinBERT's typical confidence range so a downstream confidence-
// weighted aggregate (aggregate.ts) naturally discounts it relative to real
// scores mixed into the same batch.
const FALLBACK_CONFIDENCE = 0.35;

export function keywordFallbackSentiment(text: string, reason: string): HeadlineSentiment {
  const lower = text.toLowerCase();
  const hasPositive = POSITIVE_KEYWORDS.some((kw) => lower.includes(kw));
  const hasNegative = NEGATIVE_KEYWORDS.some((kw) => lower.includes(kw));

  const label = hasPositive && !hasNegative ? "positive" : hasNegative && !hasPositive ? "negative" : "neutral";

  return {
    label,
    score: FALLBACK_CONFIDENCE,
    method: "keyword-fallback",
    note: `FinBERT unavailable for this headline (${reason}) — showing the cruder keyword heuristic instead.`,
  };
}

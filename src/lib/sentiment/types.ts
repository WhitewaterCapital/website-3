// ---------------------------------------------------------------------------
// WW-SENTIMENT — shared types.
//
// One ticker's recent headlines, each individually scored, plus an honest
// aggregate. See headlines.ts (fetch), finbert.ts (real model), keyword-
// fallback.ts (labeled crude fallback), and aggregate.ts (the math) for how
// these get built; route.ts wires them together behind
// GET /api/models/sentiment.
// ---------------------------------------------------------------------------

// FinBERT's own three output classes (ProsusAI/finbert model card) — lowercase,
// exactly as the model returns them. "unavailable" is NOT a model output; it
// is this codebase's own marker for "we have a headline but no usable score
// for it" (scorer unreachable/unauthorized/rate-limited AND no fallback
// applied) — see route.ts. Kept in the same union rather than a separate
// nullable field so every call site that switches on `label` is forced to
// handle the abstain case instead of accidentally treating `null` as neutral.
export type SentimentLabel = "positive" | "negative" | "neutral" | "unavailable";

// Which scorer actually produced a given headline's label — the load-bearing
// field this task's honesty rule turns on. "finbert" = the real, finance-
// tuned model (ProsusAI/finbert) via the Hugging Face Inference API.
// "keyword-fallback" = the crude, same-style keyword heuristic already used
// elsewhere in this codebase (see whitewatch/news/route.js's classifyThreat),
// used ONLY when finbert could not be reached for this headline — never
// silently merged into "finbert" results. "unavailable" = neither ran (e.g.
// HF_API_KEY unset AND fallback disabled) — see route.ts's `mode` query.
export type SentimentMethod = "finbert" | "keyword-fallback" | "unavailable";

export interface HeadlineSentiment {
  label: SentimentLabel;
  score: number; // 0..1 — the winning label's own confidence/probability. 0 when label is "unavailable".
  method: SentimentMethod;
  // Present only when method === "unavailable" or the finbert call itself
  // failed before falling back — a one-line, honest reason, never left blank.
  note?: string;
}

// One real, dated, linked headline — never a fabricated or paraphrased one.
// Same shape discipline as whitewatch/news/route.js's item objects: every
// field traces to something the RSS feed actually returned.
export interface Headline {
  id: string; // guid or link — stable dedupe key
  title: string;
  source: string; // publisher name string as reported by the feed, e.g. "Reuters"
  link: string;
  publishedAt: string | null; // ISO datetime, or null if the feed didn't supply one
  sentiment: HeadlineSentiment;
}

// The per-ticker aggregate. `score` is a signed -100..100 read (same sign
// convention as ConvictionSlotInput.score in conviction.ts and
// Dimension.score in models/types.ts) built ONLY from headlines whose method
// is "finbert" or "keyword-fallback" (never "unavailable" ones, which
// contribute nothing to the number by construction — see aggregate.ts).
export interface TickerSentimentAggregate {
  // true whenever `score` is null — i.e. nScored === 0. Covers BOTH the
  // "abstain, not zero" case this task calls out explicitly (zero headlines
  // found for the ticker at all, n === 0) AND the rarer case where headlines
  // were found but none could be scored by any method (n > 0, nScored === 0
  // — e.g. FinBERT unreachable for every one of them). Either way, `score`
  // is null and the UI must render a plain abstain state, never a fabricated
  // neutral 0 — `abstainReason` says which of the two happened.
  abstained: boolean;
  abstainReason: string | null;
  n: number; // total headlines considered (all methods, including "unavailable")
  nScored: number; // headlines that actually contributed to `score` (finbert + keyword-fallback)
  counts: { positive: number; negative: number; neutral: number; unavailable: number };
  score: number | null; // -100..100 confidence-weighted average, or null if nScored === 0
  // 0..1 — see aggregate.ts's computeAggregate doc comment for the exact
  // formula. Deliberately NOT the same as any one headline's own score:
  // this is "how much should a reader trust `score`", scaled down hard when
  // nScored is small (2 headlines) and up (but still capped) when it is
  // large (20+).
  confidence: number;
  method: "finbert" | "keyword-fallback" | "mixed" | "none"; // "mixed" = some of each real-scoring method
}

export interface TickerSentimentResult {
  ticker: string;
  queriedName: string | null; // company name used to widen the search query, if one was available
  headlines: Headline[];
  aggregate: TickerSentimentAggregate;
  // Whether HF_API_KEY is set in this deployment at all — surfaced so the UI
  // can tell "key missing" apart from "key set but this specific call
  // failed" (see each headline's own sentiment.note for the latter).
  finbertConfigured: boolean;
  fetchedAt: string; // ISO — when this ticker's headlines were last fetched (cache-aware, see route.ts)
  cacheHit: boolean;
}

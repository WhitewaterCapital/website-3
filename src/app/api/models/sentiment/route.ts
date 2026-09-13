import { NextResponse } from "next/server";
import { fetchTickerHeadlines } from "@/lib/sentiment/headlines";
import { callFinbert, finbertConfigured } from "@/lib/sentiment/finbert";
import { keywordFallbackSentiment } from "@/lib/sentiment/keywordFallback";
import { computeAggregate } from "@/lib/sentiment/aggregate";
import type { Headline, TickerSentimentResult } from "@/lib/sentiment/types";

// ═══════════════════════════════════════════════════════════════════════════
// GET /api/models/sentiment?ticker=NVDA[&name=NVIDIA%20Corporation]
//
// WW-SENTIMENT — real headlines (Google News RSS, see lib/sentiment/
// headlines.ts), scored by FinBERT (ProsusAI/finbert, see lib/sentiment/
// finbert.ts for the full verification writeup and how HF_API_KEY gates
// this), aggregated per lib/sentiment/aggregate.ts's documented math.
//
// CURRENT STATUS (read this before trusting the numbers, same convention as
// graph-engine/README.md and weekly-engine/README.md's own "current status"
// sections):
//
//   - Headline fetch: real, keyless, free — same Google News RSS mechanism
//     whitewatch/news/route.js already uses for one of its feeds. NOT
//     independently re-verified live from this sandbox (no outbound network
//     access here at all) — see headlines.ts's own caveat.
//   - Scoring: gated on HF_API_KEY (see .env.local.example for what it is,
//     what it costs, and how to get one). Unset -> every headline is
//     honestly marked "unavailable", nothing is fabricated. Set -> real
//     FinBERT calls, per headline, with a clearly-labeled crude keyword
//     fallback ONLY for a headline whose individual FinBERT call fails
//     (network/auth/rate-limit/cold-start) — never silently presented as a
//     real model score (see keywordFallback.ts).
//   - NEITHER the live FinBERT endpoint NOR the live Google News query has
//     been exercised from this sandbox — both are built against
//     independently verified, current documentation/schemas and tested here
//     only against realistic mocked responses (scripts/verify-sentiment.mjs
//     covers the aggregation math; there is no live-network test of either
//     external call in this repo yet). The first real deployed request is
//     the first true end-to-end confirmation.
//   - NOT wired into conviction.ts's composite score. See
//     TickerHubClient.tsx's SentimentPanel comment for the full reasoning —
//     short version: this signal decays on the order of hours, not weeks,
//     and (unlike WW-Weekly's backtested rank IC) has no measured predictive
//     validation in this codebase, so blending it into a "multi-year
//     conviction" composite would risk giving structural weight to what is
//     often just noise from one or two headlines. Shown as its own
//     standalone panel instead — same deliberate-exclusion precedent as
//     WW-Graph/WW-Cascade being left out of VerdictCard.
// ═══════════════════════════════════════════════════════════════════════════

export const runtime = "nodejs";

// How many of the most recent (deduped) headlines actually get scored per
// ticker. Bounds both API spend (each scored headline is one real HF call
// when a key is configured) and how much a member is asked to read. 20 is
// also the exact "vs 2 headlines" upper example this feature's own spec
// used for the confidence-scaling requirement — see aggregate.ts.
const MAX_SCORED_HEADLINES = 20;

// How many FinBERT calls run at once per request — a small, fixed
// concurrency cap so one ticker lookup doesn't fire 20 simultaneous requests
// at a metered, rate-limited free-tier endpoint.
const SCORE_CONCURRENCY = 5;

// Best-effort, module-level, per-ticker cache — same documented tradeoffs as
// whitewatch/news/route.js's module cache: persists across warm invocations
// of the same lambda instance, not guaranteed shared across instances or
// cold starts. Shorter TTL than that route's 5 minutes (this is a much
// faster-decaying signal — see the horizons.ts entry) but still long enough
// that re-rendering the Ticker Hub, or two members looking up the same name
// close together, doesn't re-spend metered HF credit on unchanged headlines.
const CACHE_TTL_MS = 10 * 60 * 1000;
const cache = new Map<string, { result: TickerSentimentResult; fetchedAt: number }>();

async function mapWithConcurrency<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const results: R[] = new Array(items.length);
  let next = 0;
  async function worker() {
    while (next < items.length) {
      const i = next++;
      results[i] = await fn(items[i]);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker));
  return results;
}

async function scoreHeadlines(raw: Omit<Headline, "sentiment">[]): Promise<Headline[]> {
  const configured = finbertConfigured();

  return mapWithConcurrency(raw, SCORE_CONCURRENCY, async (h): Promise<Headline> => {
    if (!configured) {
      return {
        ...h,
        sentiment: {
          label: "unavailable",
          score: 0,
          method: "unavailable",
          note: "HF_API_KEY is not set on this deployment — sentiment scoring is unavailable (see .env.local.example).",
        },
      };
    }

    const result = await callFinbert(h.title);
    if (result.ok) {
      return { ...h, sentiment: result.sentiment };
    }
    return { ...h, sentiment: keywordFallbackSentiment(h.title, result.reason) };
  });
}

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const ticker = searchParams.get("ticker")?.trim().toUpperCase();
  const name = searchParams.get("name")?.trim() || null;

  if (!ticker) {
    return NextResponse.json({ error: "ticker query param is required." }, { status: 400 });
  }

  const cached = cache.get(ticker);
  const now = Date.now();
  if (cached && now - cached.fetchedAt < CACHE_TTL_MS) {
    return NextResponse.json({ ...cached.result, cacheHit: true } satisfies TickerSentimentResult);
  }

  try {
    const rawHeadlines = await fetchTickerHeadlines(ticker, name);
    const limited = rawHeadlines.slice(0, MAX_SCORED_HEADLINES);
    const headlines = await scoreHeadlines(limited);
    const aggregate = computeAggregate(headlines);

    const result: TickerSentimentResult = {
      ticker,
      queriedName: name,
      headlines,
      aggregate,
      finbertConfigured: finbertConfigured(),
      fetchedAt: new Date(now).toISOString(),
      cacheHit: false,
    };

    cache.set(ticker, { result, fetchedAt: now });
    return NextResponse.json(result);
  } catch (err) {
    console.error(`[sentiment] request failed for ${ticker}:`, (err as Error).message);
    return NextResponse.json({ error: "Failed to build a sentiment read for this ticker." }, { status: 500 });
  }
}

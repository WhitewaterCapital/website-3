import type {
  EvaluatorModel,
  TradeIdea,
  TradeEvidence,
  StressVerdict,
  Rating,
  Dimension,
  IdeaTimeframe,
  IdeaCatalystType,
} from "../types";
import { getEquityExport, findSecurity } from "@/lib/incepta";
import { getFactorExport } from "@/lib/factor";
import { fetchInsiderTransactions } from "@/lib/whitewatch-data/edgar-sources";
import { fetchTickerHeadlines } from "@/lib/sentiment/headlines";
import { callFinbert, finbertConfigured } from "@/lib/sentiment/finbert";
import { keywordFallbackSentiment } from "@/lib/sentiment/keywordFallback";
import { computeAggregate } from "@/lib/sentiment/aggregate";
import type { Headline, TickerSentimentAggregate } from "@/lib/sentiment/types";

// ═══════════════════════════════════════════════════════════════════════════
// Distresse — an EvaluatorModel (the adversarial stress test).
//
// REAL IMPLEMENTATION (rebuilt 2026-09-13 — see PLATFORM_REBUILD_PLAN.md).
// The previous version of this file was a seeded-RNG demo; every number below
// is now grounded in a real source already wired into this app:
//
//   Dimension                    | Real source                          | Abstains when
//   ----------------------------|---------------------------------------|----------------------------------
//   Macro regime fit             | FRED T10Y2Y (10Y-2Y Treasury spread)  | FRED_API_KEY unset or fetch fails
//   Factor exposure              | WW-Factor (Fama-French + momentum)    | not exported, not covered, or WW-Factor itself abstains
//   Positioning / crowding       | WW-Insider (SEC EDGAR Form 4)         | ticker not found, EDGAR unreachable, or zero signal transactions
//   Valuation vs history         | Incepta equity engine                | not covered / insufficient confidence
//   News attention & sentiment   | Google News RSS + FinBERT             | zero headlines or none scoreable
//   Liquidity / correlation      | Incepta equity engine (risk read)     | not covered / insufficient confidence
//
// Every dimension carries `available: boolean` (see types.ts). An unavailable
// dimension is NEVER given a fabricated neutral score — the UI (ModelPanels.tsx)
// renders its note instead of a bar, same abstention discipline as every other
// real model in this codebase (equity.ts, WW-Factor, WW-Insider, WW-Sentiment).
//
// What this deliberately does NOT do:
//   - No LLM call. Every number traces to a real, cited computation below —
//     nothing here is a paraphrase or "considering the above, I think...".
//   - No Options (Alpha Vantage) data — that panel already exists standalone
//     (OptionsPanel) and per its own header comment is deliberately never
//     folded into a directional composite; same reasoning applies here.
//   - No fabricated "vs its own 5-year history" valuation comparison — Incepta
//     doesn't export a historical percentile in this build, so the Valuation
//     dimension is honestly labeled as an absolute-level read, not a trend.
//   - No fabricated catalyst/earnings calendar — no free source for this
//     exists (same gap /watch already documents), so it isn't a dimension
//     here at all rather than being faked.
//
// Research grounding for the shape of the output (devil's advocate / tail
// risks / bottom line) — see PLATFORM_REBUILD_PLAN.md's "Research grounding"
// section: a staged vetting pipeline, red-teaming discipline (assume the
// position is wrong, find the real "if this, then what kills me"), and
// crowding-as-its-own-axis (no free short-interest/13F-by-ticker data exists,
// so insider activity + factor loadings are the closest real proxy, and this
// file says so explicitly rather than pretending otherwise).
// ═══════════════════════════════════════════════════════════════════════════

function clampScore(n: number): number {
  return Math.round(Math.max(-100, Math.min(100, n)));
}

function money0(x: number): string {
  const a = Math.abs(x);
  if (a >= 1e9) return `$${(x / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(x / 1e6).toFixed(1)}M`;
  if (a >= 1e3) return `$${(x / 1e3).toFixed(0)}K`;
  return `$${x.toFixed(0)}`;
}

type DimResult = {
  dim: Dimension;
  devil?: string;
  tail?: string;
};

async function getCompanyName(ticker: string): Promise<string | null> {
  try {
    const data = await getEquityExport();
    if (!data) return null;
    const sec = findSecurity(data, ticker);
    return sec?.name ?? null;
  } catch {
    return null;
  }
}

// ─── Macro regime fit — real FRED T10Y2Y ────────────────────────────────────
// One real, free, keyless-once-a-key-is-set macro input: the 10-year minus
// 2-year Treasury spread. Positive/steep = historically a risk-on-supportive
// regime; negative/inverted = the textbook recession-warning signal. This is
// a coarse, EXPLICITLY market-wide proxy — it says nothing about this specific
// ticker's own sector or macro beta. A full per-name Macro Tracker rebuild
// (PLATFORM_REBUILD_PLAN.md priority #5) is the planned next step past this.
const FRED_CACHE_TTL_MS = 6 * 60 * 60 * 1000; // 6h — matches the commodities route's own FRED TTL
const fredCache = new Map<string, { value: number; date: string; fetchedAt: number }>();

async function fetchFredLatest(seriesId: string): Promise<{ value: number; date: string } | null> {
  const apiKey = process.env.FRED_API_KEY;
  if (!apiKey) return null;

  const cached = fredCache.get(seriesId);
  const now = Date.now();
  if (cached && now - cached.fetchedAt < FRED_CACHE_TTL_MS) return cached;

  try {
    const url = `https://api.stlouisfed.org/fred/series/observations?series_id=${seriesId}&api_key=${apiKey}&file_type=json&sort_order=desc&limit=5`;
    const resp = await fetch(url, { signal: AbortSignal.timeout(12000) });
    if (!resp.ok) return null;
    const json = await resp.json();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const obs = ((json.observations || []) as any[]).filter((o) => o.value !== "."); // FRED uses "." for missing days
    const latest = obs[0];
    if (!latest) return null;
    const result = { value: Number(latest.value), date: latest.date, fetchedAt: now };
    fredCache.set(seriesId, result);
    return result;
  } catch {
    return null;
  }
}

async function buildMacroRegimeDimension(
  ticker: string,
  isShort: boolean,
): Promise<DimResult & { regimeLine?: string }> {
  const label = "Macro regime fit";
  const fred = await fetchFredLatest("T10Y2Y");

  if (!fred) {
    return {
      dim: {
        label,
        score: 0,
        available: false,
        note: process.env.FRED_API_KEY
          ? "Couldn't reach FRED for the 10Y-2Y Treasury spread right now — this dimension abstains rather than guessing the regime."
          : "FRED_API_KEY not set — this dimension abstains rather than guessing the regime.",
      },
    };
  }

  // Scaling choice, stated plainly: +2.0pp spread -> +100, -1.0pp inversion ->
  // -50. This is a deliberately simple, explicitly-labeled linear map, not a
  // backtested or fitted one — the note says so.
  const riskOnRead = clampScore(fred.value * 50);
  const score = isShort ? -riskOnRead : riskOnRead;
  const spreadTxt = `${fred.value >= 0 ? "+" : ""}${fred.value.toFixed(2)}pp`;
  const regimeWord = fred.value < -0.1 ? "inverted (recession-warning)" : fred.value < 0.15 ? "flat" : "normal/steep";

  return {
    dim: {
      label,
      score,
      available: true,
      note: `10Y-2Y Treasury spread ${spreadTxt} as of ${fred.date} (FRED series T10Y2Y) — a ${regimeWord} curve. One real, market-wide macro input, on a deliberately simple linear scale (not backtested); it says nothing about ${ticker}'s own sector or macro beta specifically.`,
    },
    devil: `The regime read above is market-wide, not ${ticker}-specific — a name with unusually high macro sensitivity could get hurt in a regime that looks fine in aggregate, and vice versa.`,
    tail: regimeWord.startsWith("inverted")
      ? `A recession materializes faster than currently priced, and ${ticker}'s own macro sensitivity turns out higher than a broad curve read suggests.`
      : undefined,
    regimeLine: `${regimeWord} yield curve (10Y-2Y ${spreadTxt} as of ${fred.date})`,
  };
}

// ─── Factor exposure — real WW-Factor (Fama-French + momentum) ─────────────
// Individual betas are DESCRIPTIVE RISK CONTEXT, never a directional signal
// (see factor-export.ts's header comment and FactorPanel.tsx) — this
// dimension does not point a beta at "bullish/bearish". Instead it scores
// DIVERSIFICATION: how much of the name's return is explained by common
// factors (R²) vs left over as idiosyncratic, thesis-specific return. That is
// a legitimate, non-directional use of the same real regression.
async function buildFactorDimension(ticker: string): Promise<DimResult> {
  const label = "Factor exposure";

  let data;
  try {
    data = await getFactorExport();
  } catch {
    data = null;
  }
  if (!data) {
    return {
      dim: {
        label,
        score: 0,
        available: false,
        note: "WW-Factor hasn't exported data yet (no public/data/factor/latest.json) — this dimension abstains rather than guessing.",
      },
    };
  }

  const exposure = data.exposures.find((e) => e.ticker.toUpperCase() === ticker);
  if (!exposure) {
    return {
      dim: {
        label,
        score: 0,
        available: false,
        note: `${ticker} isn't in WW-Factor's current universe (${data.exposures.length} names covered) — this dimension abstains rather than guessing.`,
      },
    };
  }
  if (exposure.confidence !== "ok" || !exposure.betas) {
    return {
      dim: {
        label,
        score: 0,
        available: false,
        note: `WW-Factor itself abstains on ${ticker}: ${exposure.abstain_reason ?? exposure.confidence}.`,
      },
    };
  }

  const r2 = exposure.r2 ?? 0;
  // r2=0 (pure idiosyncratic) -> +60; r2=1 (fully systematic) -> -60.
  const diversificationScore = clampScore(60 - r2 * 120);
  const sig = exposure.betas.filter((b) => b.significant);
  const betaTxt = sig.length
    ? sig.map((b) => `${b.factor} ${b.beta >= 0 ? "+" : ""}${b.beta.toFixed(2)}`).join(", ")
    : "no significant loadings this window";
  const topSig = [...sig].sort((a, b) => Math.abs(b.beta) - Math.abs(a.beta))[0];

  return {
    dim: {
      label,
      score: diversificationScore,
      available: true,
      note: `R² ${(r2 * 100).toFixed(0)}% of return explained by ${data.factors.length} common factors (n=${exposure.n_obs} obs); significant: ${betaTxt}. Betas are descriptive risk context here, never a directional call.`,
    },
    devil: topSig
      ? `Significant ${topSig.factor} loading (β ${topSig.beta.toFixed(2)}) means part of this thesis's return is really a bet on that factor doing well, not on ${ticker} specifically.`
      : undefined,
    tail:
      r2 > 0.6
        ? `${ticker}'s returns are dominated by common factors (R² ${(r2 * 100).toFixed(0)}%) — a broad factor drawdown could hit it hard even if the idiosyncratic thesis is completely right.`
        : undefined,
  };
}

// ─── Positioning / crowding — real WW-Insider (SEC EDGAR Form 4) ───────────
// No free short-interest or 13F-by-ticker data exists anywhere (researched
// and documented in insider-export.ts's THIRTEEN_F_GAP_REASON) — insider
// buy/sell activity is the closest real, free proxy for "crowding" this app
// has, and that limitation is stated on the verdict, not hidden.
const INSIDER_CACHE_TTL_MS = 30 * 60 * 1000; // matches the insider route's own TTL
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const insiderCache = new Map<string, { raw: any; fetchedAt: number }>();

async function buildPositioningDimension(ticker: string, isShort: boolean): Promise<DimResult> {
  const label = "Positioning / crowding";

  const now = Date.now();
  const cached = insiderCache.get(ticker);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  let raw: any;
  if (cached && now - cached.fetchedAt < INSIDER_CACHE_TTL_MS) {
    raw = cached.raw;
  } else {
    try {
      raw = await fetchInsiderTransactions(ticker, { windowDays: 90 });
    } catch (err) {
      raw = { status: "unreachable", message: `Couldn't reach SEC EDGAR: ${(err as Error).message}` };
    }
    insiderCache.set(ticker, { raw, fetchedAt: now });
  }

  if (raw.status === "not_found" || raw.status === "unreachable") {
    return {
      dim: {
        label,
        score: 0,
        available: false,
        note: raw.message ?? `Couldn't get an insider-activity read for ${ticker}.`,
      },
    };
  }

  const summary = raw.summary;
  if (!summary || summary.signalTransactionCount === 0) {
    return {
      dim: {
        label,
        score: 0,
        available: false,
        note: `No open-market insider buy/sell filings for ${ticker} in the trailing ${raw.windowDays ?? 90} days — no signal to score.`,
      },
    };
  }

  const insiderScore: number = summary.score ?? 0;
  const score = clampScore(isShort ? -insiderScore : insiderScore);
  const netWord = summary.netDirection > 0 ? "net buyers" : summary.netDirection < 0 ? "net sellers" : "mixed";
  const ideaOpposesInsiders = (isShort && summary.netDirection > 0.1) || (!isShort && summary.netDirection < -0.1);

  return {
    dim: {
      label,
      score,
      available: true,
      note: `Insiders were ${netWord} over the trailing ${raw.windowDays} days: ${summary.buyCount} buy(s) (${money0(summary.buyDollars)}) vs ${summary.sellCount} sale(s) (${money0(summary.sellDollars)}) across ${summary.distinctInsiders} insider(s). Closest real, free proxy we have for positioning — no free short-interest or 13F-by-ticker data exists.`,
    },
    devil: ideaOpposesInsiders
      ? `Insiders have been ${netWord} while this idea is ${isShort ? "short" : "long"} — the people inside the company with the most information are positioned the other way.`
      : undefined,
    tail:
      summary.distinctInsiders === 1
        ? "Only one insider drove this read — could be one person's own liquidity need or a scheduled 10b5-1 plan, not a broad signal."
        : undefined,
  };
}

// ─── Valuation vs history — real Incepta valuation read ────────────────────
// Prefers evidence already attached to the idea (route.ts's Incepta lookup);
// falls back to an independent lookup so this dimension still works even when
// the route didn't attach evidence (e.g. confidence was "insufficient" there
// but a valuation number still exists). Explicitly an ABSOLUTE-level read —
// Incepta doesn't export a historical percentile in this build, so "vs
// history" in the label is honestly caveated as not yet true.
async function buildValuationDimension(
  ticker: string,
  evidence: TradeEvidence | undefined,
  isShort: boolean,
): Promise<DimResult> {
  const label = "Valuation vs history";

  let valuation: Record<string, number | null> | null | undefined = evidence?.valuation;
  let confidence: string | undefined = evidence?.confidence;
  let asOf: string | undefined = evidence?.asOf;

  if (!valuation) {
    try {
      const data = await getEquityExport();
      const sec = data ? findSecurity(data, ticker) : undefined;
      if (sec?.valuation && sec.confidence !== "insufficient") {
        valuation = sec.valuation as unknown as Record<string, number | null>;
        confidence = sec.confidence;
        asOf = sec.as_of;
      }
    } catch {
      // falls through to the unavailable branch below
    }
  }

  const pe = valuation?.pe ?? null;
  const fcfYield = valuation?.fcf_yield ?? null;
  const flags = (evidence?.flags ?? []) as string[];

  if (pe == null && fcfYield == null) {
    return {
      dim: {
        label,
        score: 0,
        available: false,
        note: "Incepta has no usable valuation read for this ticker (not covered by the equity engine, or confidence too low) — this dimension abstains rather than guessing.",
      },
    };
  }

  const parts: number[] = [];
  const metricNotes: string[] = [];
  if (fcfYield != null) {
    // ~8%+ FCF yield reads as cheap; ~0% or negative as rich/cash-burning.
    parts.push(clampScore((fcfYield - 0.03) * 1500));
    metricNotes.push(`FCF yield ${(fcfYield * 100).toFixed(1)}%`);
  }
  if (pe != null && pe > 0) {
    // A simple, stated midpoint (P/E 20 ~ neutral) — not sector-adjusted.
    parts.push(clampScore((20 - pe) * 4));
    metricNotes.push(`P/E ${pe.toFixed(1)}`);
  }
  const cheapness = clampScore(parts.reduce((a, b) => a + b, 0) / parts.length);
  const score = isShort ? -cheapness : cheapness;

  return {
    dim: {
      label,
      score,
      available: true,
      note: `${metricNotes.join(", ")} (Incepta${confidence ? `, ${confidence} confidence` : ""}${asOf ? `, as of ${asOf}` : ""}). Absolute level only — this build has no historical percentile, so it isn't truly "vs history" yet.${flags.length ? ` Flags: ${flags.join("; ")}.` : ""}`,
    },
    devil: `${ticker}'s valuation read here is today's absolute level, not a comparison to its own historical range — "${cheapness > 0 ? "cheap" : "rich"}" can still be expensive or cheap relative to where the name normally trades.`,
  };
}

// ─── Liquidity / correlation — real Incepta risk read ──────────────────────
async function buildLiquidityDimension(
  ticker: string,
  evidence: TradeEvidence | undefined,
): Promise<DimResult> {
  const label = "Liquidity / correlation";

  let risk: Record<string, number | null> | null | undefined = evidence?.risk;
  if (!risk) {
    try {
      const data = await getEquityExport();
      const sec = data ? findSecurity(data, ticker) : undefined;
      if (sec?.risk && sec.confidence !== "insufficient") {
        risk = sec.risk as unknown as Record<string, number | null>;
      }
    } catch {
      // falls through to the unavailable branch below
    }
  }

  const spread = risk?.spread_bps ?? null;
  const idioVol = risk?.idio_vol ?? null;
  const betaMkt = risk?.beta_mkt ?? null;

  if (spread == null && idioVol == null) {
    return {
      dim: {
        label,
        score: 0,
        available: false,
        note: "Incepta has no usable liquidity/risk read for this ticker — this dimension abstains rather than guessing.",
      },
    };
  }

  const parts: number[] = [];
  const notes: string[] = [];
  if (spread != null) {
    // Tighter estimated spread = more liquid = mildly supportive (less
    // execution cost eating the edge).
    parts.push(clampScore((30 - spread) * 2));
    notes.push(`est. spread ~${spread.toFixed(0)}bps`);
  }
  if (idioVol != null) {
    // Higher idiosyncratic vol = more of the return is name-specific, i.e.
    // less correlated to a broad market move — a genuinely differentiated
    // bet, not a leveraged index play.
    parts.push(clampScore((idioVol - 0.25) * 200));
    notes.push(`idio vol ${(idioVol * 100).toFixed(0)}%`);
  }
  const score = clampScore(parts.reduce((a, b) => a + b, 0) / parts.length);

  return {
    dim: {
      label,
      score,
      available: true,
      note: `${notes.join(", ")}${betaMkt != null ? `, β(mkt) ${betaMkt.toFixed(2)}` : ""} (Incepta risk read).`,
    },
    tail:
      spread != null && spread > 50
        ? `Wide/estimated spread (~${spread.toFixed(0)}bps) on ${ticker} means slippage eats into any edge faster than a slow-moving thesis has time to play out.`
        : undefined,
  };
}

// ─── News attention & sentiment — real Google News RSS + FinBERT ──────────
// Same pipeline as /api/models/sentiment, but with its own small cache and a
// tighter headline cap: HF's free monthly inference credit is small (see
// finbert.ts), and this dimension is an additional consumer beyond the
// Ticker Hub's own Sentiment panel, so it deliberately spends less of it.
const SENTIMENT_CACHE_TTL_MS = 30 * 60 * 1000;
const sentimentCache = new Map<string, { aggregate: TickerSentimentAggregate; fetchedAt: number }>();
const MAX_SCORED_HEADLINES_DISTRESSE = 6;

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

async function buildSentimentDimension(
  ticker: string,
  companyName: string | null,
  isShort: boolean,
): Promise<DimResult> {
  const label = "News attention & sentiment";

  const now = Date.now();
  const cached = sentimentCache.get(ticker);
  let aggregate: TickerSentimentAggregate;
  if (cached && now - cached.fetchedAt < SENTIMENT_CACHE_TTL_MS) {
    aggregate = cached.aggregate;
  } else {
    const raw = await fetchTickerHeadlines(ticker, companyName).catch(() => []);
    const limited = raw.slice(0, MAX_SCORED_HEADLINES_DISTRESSE);
    const configured = finbertConfigured();
    const headlines: Headline[] = await mapWithConcurrency(limited, 3, async (h): Promise<Headline> => {
      if (!configured) {
        return {
          ...h,
          sentiment: { label: "unavailable", score: 0, method: "unavailable", note: "HF_API_KEY not set." },
        };
      }
      const r = await callFinbert(h.title);
      return r.ok ? { ...h, sentiment: r.sentiment } : { ...h, sentiment: keywordFallbackSentiment(h.title, r.reason) };
    });
    aggregate = computeAggregate(headlines);
    sentimentCache.set(ticker, { aggregate, fetchedAt: now });
  }

  if (aggregate.abstained || aggregate.score == null) {
    return {
      dim: { label, score: 0, available: false, note: aggregate.abstainReason ?? "No sentiment read available for this ticker." },
    };
  }

  const score = clampScore(isShort ? -aggregate.score : aggregate.score);

  return {
    dim: {
      label,
      score,
      available: true,
      note: `${aggregate.nScored} of ${aggregate.n} recent headlines scored (${aggregate.method}), aggregate confidence ${(aggregate.confidence * 100).toFixed(0)}%. This decays over hours/days — a much shorter horizon than the other dimensions here.`,
    },
    devil: `A single good or bad headline week can move this dimension a lot without anything structural about ${ticker} having changed — weight it accordingly.`,
    tail:
      aggregate.counts.positive >= 2 && aggregate.counts.negative >= 2
        ? `Coverage is genuinely split (${aggregate.counts.positive} positive vs ${aggregate.counts.negative} negative headlines) — a single follow-up story could flip the tone.`
        : undefined,
  };
}

// ─── Outlook relevance — what "long"/"short" alone doesn't say ─────────────
// The instrument (long/short/call/put/future) says direction. It says nothing
// about the WINDOW the idea is meant to play out over — "long AAPL" as a
// multi-quarter fundamental thesis and "long AAPL just for earnings, betting
// on the print" are different bets that should lean on different evidence.
// `idea.timeframe`/`idea.catalystType` (types.ts) let the caller say which one
// this is; this table turns that into a per-dimension relevance weight in
// [0, 1] used below instead of a plain average. Both default to the values
// that reproduce the ORIGINAL unweighted behavior ("position" timeframe,
// "general-thesis" catalyst = all dimensions at full weight) so every
// existing caller that doesn't set these fields is unaffected.
//
// Rationale, briefly:
//   - An intraday/swing bet lives and dies on news/positioning right now, not
//     on a multi-quarter valuation level or the broad macro regime — those get
//     down-weighted, not zeroed (a inverted curve can still spoil an intraday
//     long, just less than it would a 6-month hold).
//   - A long-term thesis is the opposite: today's headline sentiment decays in
//     hours/days (buildSentimentDimension's own note says so) and matters much
//     less than valuation, factor exposure, and the macro regime over a
//     multi-quarter hold.
//   - An earnings-specific bet (the concrete case this table exists for) is a
//     bet on ONE dated event: news/positioning going into the print dominate;
//     valuation and the macro regime say almost nothing about which way a
//     single print goes, so they're heavily de-emphasized rather than driving
//     the call.
// No fabricated options/IV/earnings-move-history dimension is added here —
// this app has no free source for that (same gap /watch already documents) —
// this table only reweights the six REAL dimensions that already exist.
const TIMEFRAME_RELEVANCE: Record<IdeaTimeframe, Record<string, number>> = {
  intraday: {
    "Macro regime fit": 0.2,
    "Factor exposure": 0.3,
    "Positioning / crowding": 0.4,
    "Valuation vs history": 0.15,
    "News attention & sentiment": 1.0,
    "Liquidity / correlation": 0.85,
  },
  swing: {
    "Macro regime fit": 0.5,
    "Factor exposure": 0.6,
    "Positioning / crowding": 0.8,
    "Valuation vs history": 0.4,
    "News attention & sentiment": 1.0,
    "Liquidity / correlation": 0.7,
  },
  position: {
    "Macro regime fit": 1.0,
    "Factor exposure": 1.0,
    "Positioning / crowding": 1.0,
    "Valuation vs history": 1.0,
    "News attention & sentiment": 1.0,
    "Liquidity / correlation": 1.0,
  },
  "long-term": {
    "Macro regime fit": 1.0,
    "Factor exposure": 1.0,
    "Positioning / crowding": 0.5,
    "Valuation vs history": 1.0,
    "News attention & sentiment": 0.3,
    "Liquidity / correlation": 0.6,
  },
};

// Multiplicative on top of the timeframe weight, clamped to [0, 1] after.
// "general-thesis" is the identity (×1 everywhere) so it never changes
// behavior for callers that don't set a catalyst.
const CATALYST_MULTIPLIER: Record<IdeaCatalystType, Record<string, number>> = {
  "general-thesis": {},
  earnings: {
    "Macro regime fit": 0.5,
    "Factor exposure": 0.7,
    "Valuation vs history": 0.5,
    "News attention & sentiment": 1.2,
    "Positioning / crowding": 1.1,
  },
  "fed-macro-event": {
    "Macro regime fit": 1.3,
    "Valuation vs history": 0.6,
    "Factor exposure": 0.9,
  },
  "product-launch": {
    "News attention & sentiment": 1.2,
    "Valuation vs history": 0.6,
  },
  "technical-level": {
    "Liquidity / correlation": 1.2,
    "Factor exposure": 1.1,
    "Macro regime fit": 0.8,
    "Valuation vs history": 0.8,
  },
};

function dimensionRelevance(label: string, timeframe: IdeaTimeframe, catalystType: IdeaCatalystType): number {
  const base = TIMEFRAME_RELEVANCE[timeframe]?.[label] ?? 1.0;
  const mult = CATALYST_MULTIPLIER[catalystType]?.[label] ?? 1.0;
  return Math.max(0, Math.min(1, base * mult));
}

// ─── Bottom line ────────────────────────────────────────────────────────────
function buildBottomLine(
  rating: Rating,
  coverage: number,
  dims: Dimension[],
  ticker: string,
  isShort: boolean,
  missing: string[],
  timeframe: IdeaTimeframe,
  catalystType: IdeaCatalystType,
  deemphasized: string[],
): string {
  const dirWord = isShort ? "short" : "long";
  const coveragePct = Math.round(coverage * 100);
  const available = dims.filter((d) => d.available);
  const strongest = [...available].sort((a, b) => Math.abs(b.score) - Math.abs(a.score))[0];

  let verdict: string;
  if (available.length === 0) {
    verdict = `No usable real evidence came back for ${ticker} right now — every real source either abstained or couldn't be reached. This isn't a "no-go" call, it's "come back once at least one real source is live."`;
  } else if (rating === "go") {
    verdict = `The real evidence lines up${strongest ? `, led by ${strongest.label.toLowerCase()} (${strongest.score > 0 ? "+" : ""}${strongest.score})` : ""} — clears the bar on ${coveragePct}% weighted coverage. Size the ${dirWord} and define the invalidation.`;
  } else if (rating === "no-go") {
    verdict = `The real evidence leans against this ${dirWord}${strongest ? `, mainly ${strongest.label.toLowerCase()} (${strongest.score})` : ""}. Pass, or wait for the picture to change.`;
  } else {
    verdict = `Mixed real evidence at ${coveragePct}% weighted coverage — nothing here is strong enough on its own to call a clean go or no-go on this ${dirWord}.`;
  }
  if (missing.length) {
    verdict += ` Abstained rather than guessed on: ${missing.join(", ")}.`;
  }
  if (timeframe !== "position" || catalystType !== "general-thesis") {
    const window =
      timeframe === "intraday" ? "an intraday" : timeframe === "swing" ? "a swing (days–weeks)" : "a long-term";
    const catalystTxt =
      catalystType !== "general-thesis" ? `, framed around ${catalystType.replace(/-/g, " ")}` : "";
    verdict += ` Read as ${window} idea${catalystTxt}: weighting leans on the dimensions that actually move over that window.`;
    if (deemphasized.length) {
      verdict += ` De-emphasized for this horizon: ${deemphasized.join(", ")}.`;
    }
  }
  return verdict;
}

export const distresse: EvaluatorModel = {
  meta: {
    id: "distresse",
    name: "Distresse",
    kind: "evaluator",
    status: "live",
    tagline: "Adversarial stress test grounded in real macro, factor, filing, valuation and news data.",
    description:
      "Takes a trade idea and tests it against every other real read this platform has — FRED's yield curve, WW-Factor's regression, SEC EDGAR insider filings, Incepta's valuation/risk numbers, and live news sentiment — then plays devil's advocate on the real conflicts between them and gives a blunt call. Abstains, dimension by dimension, wherever a real source doesn't cover the name rather than guessing.",
    etymology: "From Latin districtia — to be pulled apart, stretched, stressed.",
  },

  async evaluate(idea: TradeIdea): Promise<StressVerdict> {
    const ticker = idea.ticker.trim().toUpperCase();
    const isShort = idea.instrument === "short" || idea.instrument === "put";
    const timeframe: IdeaTimeframe = idea.timeframe ?? "position";
    const catalystType: IdeaCatalystType = idea.catalystType ?? "general-thesis";
    const companyName = await getCompanyName(ticker);

    const [macro, factor, positioning, valuation, sentiment, liquidity] = await Promise.all([
      buildMacroRegimeDimension(ticker, isShort),
      buildFactorDimension(ticker),
      buildPositioningDimension(ticker, isShort),
      buildValuationDimension(ticker, idea.evidence, isShort),
      buildSentimentDimension(ticker, companyName, isShort),
      buildLiquidityDimension(ticker, idea.evidence),
    ]);

    const parts: DimResult[] = [macro, factor, positioning, valuation, sentiment, liquidity];
    const dims: Dimension[] = parts.map((p) => p.dim);
    const availableDims = dims.filter((d) => d.available);
    // Coverage/average are RELEVANCE-WEIGHTED, not a plain count/mean, so an
    // idea's stated timeframe/catalyst (see the relevance table above) shapes
    // which real dimensions actually drive the call. For the defaults
    // ("position" / "general-thesis") every weight is 1.0 and this reduces
    // exactly to the original plain average — existing callers see no change.
    const weightOf = (d: Dimension) => dimensionRelevance(d.label, timeframe, catalystType);
    const totalWeight = dims.reduce((s, d) => s + weightOf(d), 0);
    const availableWeight = availableDims.reduce((s, d) => s + weightOf(d), 0);
    const coverage = totalWeight > 0 ? availableWeight / totalWeight : 0;
    const avg =
      availableWeight > 0
        ? availableDims.reduce((s, d) => s + d.score * weightOf(d), 0) / availableWeight
        : 0;
    // Dimensions materially down-weighted for this timeframe/catalyst (and
    // still available — no point flagging something that already abstained),
    // named plainly in the bottom line rather than left as a silent number
    // change from what a "position"-horizon read would have shown.
    const deemphasized = availableDims
      .filter((d) => weightOf(d) < 0.6)
      .map((d) => d.label);

    const rating: Rating = availableDims.length === 0 ? "conditional" : avg > 25 ? "go" : avg < -20 ? "no-go" : "conditional";
    // Conviction is scaled down by (weighted) coverage, not just by score
    // magnitude — a strong-looking average built on 1 of 6 real dimensions
    // should never read as confidently as the same average built on 6 of 6,
    // and a dimension that's real but de-emphasized for this horizon counts
    // for less coverage too.
    const magnitudeConviction = Math.min(95, 35 + Math.abs(avg) * 0.6);
    const conviction = Math.round(Math.max(5, magnitudeConviction * (0.35 + 0.65 * coverage)));

    const devils = Array.from(new Set(parts.map((p) => p.devil).filter((x): x is string => Boolean(x))));
    const tails = Array.from(new Set(parts.map((p) => p.tail).filter((x): x is string => Boolean(x))));

    // Structural caveats already researched and documented elsewhere in this
    // codebase — real, sourced gaps, always shown, not conditional filler.
    devils.push(
      "No free, real-time 13F institutional-positioning or short-interest data exists for any ticker (researched — see WW-Insider's own documented gap) — \"crowding\" above leans on insider Form 4 filings and factor loadings only, a real but incomplete proxy.",
    );
    tails.push(
      "This is a snapshot across today's real evidence, not a backtest — Distresse doesn't yet know whether an idea shaped like this one has actually worked historically (a backtest/track-record engine is a separate, tracked future build).",
    );
    if (idea.evidence?.flags?.length) {
      devils.push(`Incepta engine flags: ${idea.evidence.flags.join("; ")}.`);
    }

    const missing = dims.filter((d) => !d.available).map((d) => d.label);
    const bottomLine = buildBottomLine(
      rating,
      coverage,
      dims,
      ticker,
      isShort,
      missing,
      timeframe,
      catalystType,
      deemphasized,
    );

    const regime = macro.regimeLine ?? "Not available this read — FRED unreachable or FRED_API_KEY not set.";
    const evidenceTag = idea.evidence ? ` · Incepta evidence (${idea.evidence.confidence})` : "";
    const outlookTag =
      timeframe !== "position" || catalystType !== "general-thesis"
        ? ` · ${timeframe}${catalystType !== "general-thesis" ? `/${catalystType}` : ""} outlook`
        : "";
    const generatedBy = `Distresse · ${availableDims.length}/${dims.length} real dimensions covered${evidenceTag}${outlookTag}`;

    return {
      ticker,
      instrument: idea.instrument,
      rating,
      conviction,
      regime,
      dimensions: dims,
      devilsAdvocate: devils,
      tailRisks: tails,
      bottomLine,
      generatedBy,
    };
  },
};

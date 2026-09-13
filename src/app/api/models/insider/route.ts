import { NextResponse } from "next/server";
import { fetchInsiderTransactions } from "@/lib/whitewatch-data/edgar-sources";
import { THIRTEEN_F_GAP_REASON, type InsiderReading } from "@/lib/models/insider-export";

// ═══════════════════════════════════════════════════════════════════════════
// GET /api/models/insider?ticker=AAPL[&windowDays=90]
//
// WW-INSIDER — live, keyless SEC EDGAR Form 4 (insider transaction) read for
// an arbitrary ticker. See lib/whitewatch-data/edgar-sources.js's header
// comment for the full source verification writeup: which real endpoints
// this calls, exactly what was confirmed live via the WebFetch tool during
// development (this sandbox itself has zero outbound network access to
// sec.gov — confirmed by a direct curl 403 from the local egress proxy), and
// — importantly — the honest 13F institutional-ownership gap: there is no
// free, keyless, real-time, by-ticker API for "who changed their position in
// this ticker last quarter". See `thirteenF` on every response below.
//
// Same seam as every other model route in this codebase (sentiment,
// options, weekly): reads through the lib function, never touches SEC
// directly here, so the fetch/parse implementation can change without this
// route changing.
//
// THREE-WAY DISTINGUISHABLE RESULT — this task's core honesty requirement.
// edgar-sources.js's fetchInsiderTransactions never collapses "SEC has zero
// Form 4 filings for this ticker in the window" (a real, valid `ok` result
// with an empty `transactions` array) into the same shape as "this ticker
// doesn't resolve to a real SEC CIK" (`not_found`) or "a real network/HTTP
// failure talking to SEC" (`unreachable`). This route passes that
// distinction straight through — see insider-export.ts's InsiderStatus.
// ═══════════════════════════════════════════════════════════════════════════

export const runtime = "nodejs";

// Form 4s must be filed within 2 business days of a transaction (SEC Section
// 16 rule) — nothing about this signal changes meaningfully inside 30
// minutes, and this TTL keeps repeat lookups of a popular ticker from
// re-fetching (and re-parsing) up to MAX_FILINGS_TO_FETCH individual filing
// XML documents from SEC every time the Ticker Hub re-renders. Shorter than
// indicators/route.js's 12h (this genuinely does update within a trading
// day when a new Form 4 lands) but far longer than options/route.js's 5min
// (that data is itself already a live, fast-moving quote; this is a filing
// record that doesn't change once made).
const CACHE_TTL_MS = 30 * 60 * 1000;
const cache = new Map<string, { data: InsiderReading; fetchedAt: number }>();

const MIN_WINDOW_DAYS = 7;
const MAX_WINDOW_DAYS = 365;
const DEFAULT_WINDOW_DAYS = 90;

// THIRTEEN_F_GAP_REASON itself lives in insider-export.ts (single source of
// truth shared with any client-side fallback — see that file's comment).

export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const ticker = searchParams.get("ticker")?.trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json({ error: "ticker query param is required." }, { status: 400 });
  }

  const windowDaysParam = Number(searchParams.get("windowDays"));
  const windowDays =
    Number.isFinite(windowDaysParam) && windowDaysParam >= MIN_WINDOW_DAYS && windowDaysParam <= MAX_WINDOW_DAYS
      ? Math.round(windowDaysParam)
      : DEFAULT_WINDOW_DAYS;

  const cacheKey = `${ticker}:${windowDays}`;
  const cached = cache.get(cacheKey);
  if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
    return NextResponse.json(cached.data);
  }

  let result: InsiderReading;
  try {
    // edgar-sources.js is plain JS (matching this repo's existing
    // lib/whitewatch-data/ style — see econ-sources.js) with no .d.ts, so
    // its return shape is treated as `any` at this TS boundary rather than
    // relied on for compile-time narrowing. Every field read off it below
    // is passed through explicitly, not spread blindly, so a shape mismatch
    // fails into a visibly incomplete response rather than a crash.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const raw: any = await fetchInsiderTransactions(ticker, { windowDays });

    if (raw.status === "not_found" || raw.status === "unreachable") {
      result = {
        status: raw.status,
        ticker,
        cik: raw.cik,
        companyName: raw.companyName ?? null,
        message: raw.message ?? "Couldn't get an insider-activity read for this ticker.",
        thirteenF: { supported: false, reason: THIRTEEN_F_GAP_REASON },
        generatedBy: "SEC EDGAR Form 4 (data.sec.gov / www.sec.gov) — live, keyless",
      };
    } else {
      result = {
        status: "ok",
        ticker,
        cik: raw.cik,
        companyName: raw.companyName ?? null,
        windowDays: raw.windowDays,
        sinceDate: raw.sinceDate,
        filingsFound: raw.filingsFound,
        filingsFetched: raw.filingsFetched,
        filingFetchFailures: raw.filingFetchFailures,
        filingsCappedAt: raw.filingsCappedAt ?? null,
        windowMayBeIncomplete: Boolean(raw.windowMayBeIncomplete),
        transactions: raw.transactions ?? [],
        summary: raw.summary,
        message:
          raw.filingFetchFailures > 0
            ? `${raw.filingFetchFailures} of ${raw.filingsFetched} matching filings failed to fetch and are not reflected below — this is a partial, not a complete, read.`
            : undefined,
        thirteenF: { supported: false, reason: THIRTEEN_F_GAP_REASON },
        generatedBy: "SEC EDGAR Form 4 (data.sec.gov / www.sec.gov) — live, keyless",
      };
    }
  } catch (err) {
    // fetchInsiderTransactions is designed to catch its own network errors
    // and return status:"unreachable" rather than throw — this catch is a
    // defensive backstop for a genuinely unexpected failure (e.g. a bug),
    // and still returns the honest "unreachable" shape rather than a raw
    // 500 with no explanation the UI can render.
    console.error(`[insider] request failed for ${ticker}:`, err instanceof Error ? err.message : err);
    result = {
      status: "unreachable",
      ticker,
      message: "Unexpected error building an insider-activity read for this ticker.",
      thirteenF: { supported: false, reason: THIRTEEN_F_GAP_REASON },
      generatedBy: "SEC EDGAR Form 4 (data.sec.gov / www.sec.gov) — live, keyless",
    };
  }

  cache.set(cacheKey, { data: result, fetchedAt: Date.now() });
  return NextResponse.json(result);
}

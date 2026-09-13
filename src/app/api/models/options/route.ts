import { NextResponse } from "next/server";
import {
  isAlphaVantageConfigured,
  getOptionsSnapshot,
} from "@/lib/whitewatch-data/alphavantage-options";
import { summarizeChain } from "@/lib/whitewatch-data/options-summary";
import type { OptionsSummary } from "@/lib/models/options-export";

export const runtime = "nodejs";

// Per-ticker cache. TTL chosen at 24 HOURS — a deliberate, large jump from
// the old Tradier-sandbox route's 5-minute TTL, and it needs its own
// explanation because the reasoning that picked 5 minutes no longer holds:
//
//   - Tradier sandbox: 60 requests/minute budget, data already 15-min
//     delayed at the source, so a short cache barely mattered and a longer
//     one would have made the displayed delay misleading.
//   - Alpha Vantage free tier: ~25 requests/DAY total (not per minute), per
//     this integration's own research (see alphavantage-options.js's
//     header) — and each ticker lookup can cost TWO of those 25 (one
//     HISTORICAL_OPTIONS call, plus one GLOBAL_QUOTE call for spot, only
//     when the first one actually returned usable data). A 5-minute cache
//     against a 25/day budget would let a handful of back-to-back member
//     searches burn the ENTIRE day's quota for everyone before lunch. A
//     24-hour cache instead caps this feature at roughly a dozen distinct
//     ticker lookups per day, platform-wide, which is a real and honest
//     constraint of the free tier this app now runs on (see the owner's
//     decision to accept this trade-off in exchange for Tradier's identity-
//     verification requirement) — not an arbitrary number. HISTORICAL_
//     OPTIONS is itself an end-of-day dataset (see alphavantage-options.js),
//     so caching it for a day doesn't make the data meaningfully "more
//     stale" than it already, honestly, is.
//
// This is a bigger constraint than a code comment can fully convey to a
// member searching a new ticker and getting "not configured"-looking
// silence because the day's quota is gone — see OptionsPanel's own
// always-visible caveat banner (ModelPanels.tsx) for the member-facing
// warning about this same limit.
const CACHE_TTL_MS = 24 * 60 * 60 * 1000;

// A "rate_limited" result gets a MUCH shorter cache TTL than everything
// else: Alpha Vantage's rate-limit message can mean "hit the ~25/day cap"
// (won't clear for up to a day) or "hit the per-minute call-frequency cap"
// (clears in well under a minute) and this route can't always tell which
// from the message text alone — so it re-checks soon rather than either
// hammering Alpha Vantage every request (no cache) or showing a stale
// "rate limited" for a full day when the real cause cleared in seconds.
// "plan_gated" gets the full 24h TTL like "ok": Alpha Vantage saying an
// endpoint isn't on this key's plan will not change on its own, so there is
// nothing to gain from re-checking it sooner.
const RATE_LIMITED_CACHE_TTL_MS = 2 * 60 * 1000;
const cache = new Map<string, { data: OptionsSummary; fetchedAt: number; ttlMs: number }>();

function notConfigured(ticker: string): OptionsSummary {
  return {
    status: "not_configured",
    ticker,
    asOf: new Date().toISOString(),
    reason:
      "ALPHA_VANTAGE_API_KEY is not set. Get a free key (no identity verification, just an email address) at " +
      "https://www.alphavantage.co/support/#api-key.",
    generatedBy: "Alpha Vantage (options) — not configured",
  };
}

function errorSummary(ticker: string, message: string): OptionsSummary {
  return {
    status: "error",
    ticker,
    asOf: new Date().toISOString(),
    reason: message,
    generatedBy: "Alpha Vantage (options) — fetch failed",
  };
}

// alphavantage-options.js / options-summary.js are plain JS (matching this
// repo's existing lib/whitewatch-data/ style — see econ-sources.js) with no
// .d.ts, so their return shapes are treated as `any` at this TS boundary
// rather than relied on for compile-time narrowing. Every field this route
// reads off `snapshot`/`summary` is re-validated at runtime below (optional
// chaining, explicit field-by-field construction of the response) so a
// shape mismatch fails safe into "no_data"/"error", never a crash or a
// fabricated field.
export async function GET(req: Request) {
  const ticker = new URL(req.url).searchParams.get("ticker")?.trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json({ error: "ticker query param is required." }, { status: 400 });
  }

  if (!isAlphaVantageConfigured()) {
    return NextResponse.json(notConfigured(ticker));
  }

  const cached = cache.get(ticker);
  if (cached && Date.now() - cached.fetchedAt < cached.ttlMs) {
    return NextResponse.json(cached.data);
  }

  let result: OptionsSummary;
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const snapshot: any = await getOptionsSnapshot(ticker);
    const asOf: string = snapshot?.asOf ?? new Date().toISOString();

    if (snapshot?.status === "plan_gated") {
      // Alpha Vantage itself says this endpoint isn't on this key's plan —
      // NEVER shown as a generic fetch error, and never retried faster than
      // the cache TTL, since retrying sooner cannot possibly change this
      // outcome (see alphavantage-options.js's header for why this is a
      // real, researched possibility, not a hypothetical).
      result = {
        status: "plan_gated",
        ticker,
        asOf,
        reason:
          snapshot?.reason ??
          "Alpha Vantage says this endpoint is not available on this API key's plan.",
        generatedBy: "Alpha Vantage (options) — not available on this plan",
      };
    } else if (snapshot?.status === "rate_limited") {
      // Distinct from plan_gated: the free tier CAN reach this endpoint but
      // has hit its request budget for now (per-minute and/or the ~25/day
      // cap) — retrying later may work, which is exactly why this is not
      // collapsed into "error" or into "plan_gated".
      result = {
        status: "rate_limited",
        ticker,
        asOf,
        reason: snapshot?.reason ?? "Alpha Vantage's free-tier request limit was hit for this pull.",
        generatedBy: "Alpha Vantage (options) — rate limited",
      };
    } else if (snapshot?.status === "not_applicable") {
      result = {
        status: "not_applicable",
        ticker,
        asOf,
        reason: `Alpha Vantage returned no listed options chain for ${ticker} — most tickers on this platform (commodities, FX, and many equities) simply don't have exchange-listed options. This is expected, not a failure.`,
        generatedBy: "Alpha Vantage (options)",
      };
    } else if (snapshot?.status === "ok" && Array.isArray(snapshot.contracts) && snapshot.contracts.length > 0) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const summary: any = summarizeChain(snapshot);
      delete summary.symbol; // drop the raw adapter's `symbol` field — this route's contract uses `ticker`
      result = {
        ...summary,
        ticker,
        quoteDate: snapshot?.quoteDate ?? undefined,
        dataProvenance: "alphavantage-historical-options",
        generatedBy: "Alpha Vantage (options)",
      } as OptionsSummary;
    } else {
      // Covers getOptionsSnapshot's "no_data" status (listed but the
      // chain/quote pull came back empty) AND any unrecognized/partial
      // shape — same honest-abstention treatment either way.
      result = {
        status: "no_data",
        ticker,
        asOf,
        quoteDate: snapshot?.quoteDate ?? undefined,
        expiration: snapshot?.expiration,
        expirationBasis: snapshot?.expirationBasis,
        reason:
          snapshot?.reason ??
          `${ticker} has listed option expirations but Alpha Vantage returned no usable chain/quote this pull. This is usually temporary — try again after the cache TTL (24h) — but see this platform's free-tier request-budget caveat before assuming an immediate retry will help.`,
        generatedBy: "Alpha Vantage (options)",
      };
    }
  } catch (err) {
    result = errorSummary(ticker, err instanceof Error ? err.message : "Unknown error fetching Alpha Vantage data.");
  }

  const ttlMs = result.status === "rate_limited" ? RATE_LIMITED_CACHE_TTL_MS : CACHE_TTL_MS;
  cache.set(ticker, { data: result, fetchedAt: Date.now(), ttlMs });
  return NextResponse.json(result);
}

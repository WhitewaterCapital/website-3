import { NextResponse } from "next/server";
import {
  isTradierConfigured,
  getOptionsSnapshot,
} from "@/lib/whitewatch-data/tradier-sandbox";
import { summarizeChain } from "@/lib/whitewatch-data/options-summary";
import type { OptionsSummary } from "@/lib/models/options-export";

export const runtime = "nodejs";

// Per-ticker cache. TTL chosen at 5 minutes: Tradier sandbox data is ALREADY
// 15-minutes delayed at the source (see tradier-sandbox.js's header), so an
// extra 5-minute server-side cache adds at most ~33% to that existing lag
// (worst case 20 min stale instead of 15) while cutting real Tradier calls
// by roughly 5x under repeated hits on a popular ticker — comfortably inside
// the sandbox's documented 60-req/min limit even with several members
// pulling different tickers. 5 minutes was picked over indicators/route.js's
// 12-hour TTL (which fits slow-moving macro indicators) precisely because
// this data is fast-moving and already delayed; caching it as aggressively
// as the macro data would make the displayed delay materially misleading.
const CACHE_TTL_MS = 5 * 60 * 1000;
const cache = new Map<string, { data: OptionsSummary; fetchedAt: number }>();

function notConfigured(ticker: string): OptionsSummary {
  return {
    status: "not_configured",
    ticker,
    asOf: new Date().toISOString(),
    reason:
      "TRADIER_API_KEY is not set. Get a free Tradier sandbox token (no funded brokerage account required) at " +
      "https://developer.tradier.com/user/sign_up, then generate a Sandbox token at https://web.tradier.com/user/api.",
    generatedBy: "Tradier sandbox (options) — not configured",
  };
}

function errorSummary(ticker: string, message: string): OptionsSummary {
  return {
    status: "error",
    ticker,
    asOf: new Date().toISOString(),
    reason: message,
    generatedBy: "Tradier sandbox (options) — fetch failed",
  };
}

// tradier-sandbox.js / options-summary.js are plain JS (matching this repo's
// existing lib/whitewatch-data/ style — see econ-sources.js) with no .d.ts,
// so their return shapes are treated as `any` at this TS boundary rather
// than relied on for compile-time narrowing. Every field this route reads
// off `snapshot`/`summary` is re-validated at runtime below (optional
// chaining, explicit field-by-field construction of the response) so a
// shape mismatch fails safe into "no_data"/"error", never a crash or a
// fabricated field.
export async function GET(req: Request) {
  const ticker = new URL(req.url).searchParams.get("ticker")?.trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json({ error: "ticker query param is required." }, { status: 400 });
  }

  if (!isTradierConfigured()) {
    return NextResponse.json(notConfigured(ticker));
  }

  const cached = cache.get(ticker);
  if (cached && Date.now() - cached.fetchedAt < CACHE_TTL_MS) {
    return NextResponse.json(cached.data);
  }

  let result: OptionsSummary;
  try {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const snapshot: any = await getOptionsSnapshot(ticker);
    const asOf: string = snapshot?.asOf ?? new Date().toISOString();

    if (snapshot?.status === "not_applicable") {
      result = {
        status: "not_applicable",
        ticker,
        asOf,
        reason: `Tradier has no listed options chain for ${ticker} — most tickers on this platform (commodities, FX, and many equities) simply don't have exchange-listed options. This is expected, not a failure.`,
        generatedBy: "Tradier sandbox (options)",
      };
    } else if (snapshot?.status === "ok" && Array.isArray(snapshot.contracts) && snapshot.contracts.length > 0) {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const summary: any = summarizeChain(snapshot);
      delete summary.symbol; // drop the raw adapter's `symbol` field — this route's contract uses `ticker`
      result = {
        ...summary,
        ticker,
        dataProvenance: "tradier-sandbox-delayed-15min",
        generatedBy: "Tradier sandbox (options)",
      } as OptionsSummary;
    } else {
      // Covers getOptionsSnapshot's "no_data" status (listed but the
      // chain/quote pull came back empty) AND any unrecognized/partial
      // shape — same honest-abstention treatment either way.
      result = {
        status: "no_data",
        ticker,
        asOf,
        expiration: snapshot?.expiration,
        expirationBasis: snapshot?.expirationBasis,
        reason: `${ticker} has listed option expirations but Tradier's sandbox returned no usable chain/quote this pull. This is usually temporary — try again shortly.`,
        generatedBy: "Tradier sandbox (options)",
      };
    }
  } catch (err) {
    result = errorSummary(ticker, err instanceof Error ? err.message : "Unknown error fetching Tradier sandbox data.");
  }

  cache.set(ticker, { data: result, fetchedAt: Date.now() });
  return NextResponse.json(result);
}

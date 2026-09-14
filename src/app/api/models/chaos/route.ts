import { NextResponse } from "next/server";
import { getChaosExport } from "@/lib/chaos";

// Ticker-scoped read of WW-CHAOS's export, for the Ticker Hub (and anything
// else that wants "is this name on today's watchlist, and what's its
// intraday chaos/directional read" without pulling the whole latest.json).
// Same seam as every other model route (weekly/factor/graph): reads through
// the lib function, never the file path, so swapping the backing store
// later needs no UI change.
//
// `provenance` is passed straight through from the export (never dropped)
// — see chaos-export.ts's own honesty note: this export runs in
// synthetic-demo mode only today, and conviction.ts's CASCADE_EXPOSURE_SLOT
// builder (see TickerHubClient.tsx) relies on this field to cap the slot's
// confidence until the export flips to `"live"`.
export async function GET(req: Request) {
  const ticker = new URL(req.url).searchParams.get("ticker")?.trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json({ error: "ticker query param is required." }, { status: 400 });
  }

  const data = await getChaosExport();
  if (!data) {
    return NextResponse.json({ synced: false, covered: false, watchlistSize: 0, provenance: null, reading: null });
  }

  return NextResponse.json({
    synced: true,
    covered: data.watchlist.includes(ticker),
    watchlistSize: data.watchlist.length,
    provenance: data.provenance,
    disclaimer: data.disclaimer,
    reading: data.readings.find((r) => r.ticker.toUpperCase() === ticker) ?? null,
  });
}

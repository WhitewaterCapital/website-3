import { NextResponse } from "next/server";
import { getWeeklyExport } from "@/lib/weekly";

// Ticker-scoped read of WW-Weekly's export, for the Ticker Hub (and anything
// else that wants "is this name covered, and what's its rank" without
// pulling the whole latest.json). Same seam as every other model route:
// reads through the lib function, never the file path, so swapping the
// backing store later needs no UI change.
export async function GET(req: Request) {
  const ticker = new URL(req.url).searchParams.get("ticker")?.trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json({ error: "ticker query param is required." }, { status: 400 });
  }

  const data = await getWeeklyExport();
  if (!data) {
    return NextResponse.json({ synced: false, covered: false, universeSize: 0, forecast: null });
  }

  return NextResponse.json({
    synced: true,
    covered: data.universe.includes(ticker),
    universeSize: data.universe.length,
    forecast: data.forecasts.find((f) => f.ticker.toUpperCase() === ticker) ?? null,
  });
}

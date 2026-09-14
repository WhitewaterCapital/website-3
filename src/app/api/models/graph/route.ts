import { NextResponse } from "next/server";
import { getGraphExport } from "@/lib/graph";

// Ticker-scoped read of WW-GRAPH's export, for the Ticker Hub (and anything
// else that wants "is this name in today's graph universe, and what's its
// residual/half-life read" without pulling the whole latest.json). Same
// seam as every other model route (weekly/factor): reads through the lib
// function, never the file path, so swapping the backing store later needs
// no UI change.
//
// `dataProvenance` is passed straight through from the export (never
// dropped) — see graph-export.ts's own honesty note: a synthetic-demo read
// must never be presented as a real market read, and conviction.ts's
// GRAPH_RESIDUAL_SLOT builder (see TickerHubClient.tsx) relies on this field
// to cap the slot's confidence when the export hasn't flipped to `"live"`.
export async function GET(req: Request) {
  const ticker = new URL(req.url).searchParams.get("ticker")?.trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json({ error: "ticker query param is required." }, { status: 400 });
  }

  const data = await getGraphExport();
  if (!data) {
    return NextResponse.json({ synced: false, covered: false, universeSize: 0, dataProvenance: null, residual: null });
  }

  return NextResponse.json({
    synced: true,
    covered: data.universe.includes(ticker),
    universeSize: data.universe.length,
    dataProvenance: data.data_provenance,
    residual: data.residuals.find((r) => r.ticker.toUpperCase() === ticker) ?? null,
  });
}

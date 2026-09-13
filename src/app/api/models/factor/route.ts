import { NextResponse } from "next/server";
import { getFactorExport } from "@/lib/factor";

// Ticker-scoped read of WW-FACTOR's export, for the Ticker Hub (and anything
// else that wants "is this name covered, and what's its factor exposure"
// without pulling the whole latest.json). Same seam as every other model
// route: reads through the lib function, never the file path, so swapping
// the backing store later needs no UI change.
export async function GET(req: Request) {
  const ticker = new URL(req.url).searchParams.get("ticker")?.trim().toUpperCase();
  if (!ticker) {
    return NextResponse.json({ error: "ticker query param is required." }, { status: 400 });
  }

  const data = await getFactorExport();
  if (!data) {
    return NextResponse.json({ synced: false, covered: false, universeSize: 0, exposure: null });
  }

  return NextResponse.json({
    synced: true,
    covered: data.universe.includes(ticker),
    universeSize: data.universe.length,
    dataProvenance: data.data_provenance,
    factors: data.factors,
    factorExplainers: data.factor_explainers,
    exposure: data.exposures.find((e) => e.ticker.toUpperCase() === ticker) ?? null,
  });
}

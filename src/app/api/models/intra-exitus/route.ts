import { NextResponse } from "next/server";
import { models } from "@/lib/models/registry";
import type { TradeIdea, Instrument } from "@/lib/models/types";

// Standalone "type any ticker" endpoint for the Entry & Exit page. This is
// the exact same models.intraExitus.plan() the Stress Test flow already uses
// for arbitrary tickers (see /api/models/stress) — Entry & Exit's own page
// just never exposed a ticker input, so it only ever showed the ~5-name
// static export. No new model logic here, just a thin route so the page can
// call it directly without dragging in Stress Test's thesis/instrument form.
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));
  const ticker = String(body.ticker ?? "").trim().toUpperCase();
  const instrument = String(body.instrument ?? "long") as Instrument;

  if (!ticker) {
    return NextResponse.json({ error: "Ticker is required." }, { status: 400 });
  }

  const idea: TradeIdea = { ticker, instrument, thesis: "" };
  const plan = await models.intraExitus.plan(idea);

  return NextResponse.json({ plan });
}

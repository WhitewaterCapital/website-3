import { NextResponse } from "next/server";
import { primaryMacro } from "@/lib/models/registry";

// Daily macro refresh. Wire to a Vercel Cron (see vercel.json). Each run
// produces the day's reading and should persist it so the Models page shows
// history over time. Once real AI + a market-data feed are connected, this is
// where the ingestion happens.
export async function GET() {
  const today = new Date().toISOString().slice(0, 10);
  const reading = await primaryMacro().read(today);

  // TODO: insert `reading` into your database (one row per day).

  return NextResponse.json({ ok: true, date: reading.date, sentiment: reading.sentiment });
}

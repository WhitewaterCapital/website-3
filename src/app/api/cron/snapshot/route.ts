import { NextResponse } from "next/server";
import { getBroker } from "@/lib/broker";

// Scheduled snapshot capture.
//
// Wire this to a Vercel Cron (see vercel.json) so it runs a few times a day.
// Each run pulls the live account state from the broker and should append a row
// to your `snapshots` table — that stored history is what powers the equity
// curve (brokers rarely give you a clean one). Right now it just reads the
// account and echoes it back; add the DB insert where marked.
export async function GET() {
  const broker = getBroker();

  try {
    const account = await broker.getAccount();
    const snapshot = {
      date: new Date().toISOString().slice(0, 10),
      totalValueUsd: account.totalValueUsd,
      cashUsd: account.cashUsd,
      investedUsd: account.investedUsd,
      // spyPrice: fetch from a market-data source when you wire real data
    };

    // TODO: insert `snapshot` into your database here (Postgres / Supabase).

    return NextResponse.json({ ok: true, snapshot, source: broker.name });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: (err as Error).message },
      { status: 500 },
    );
  }
}

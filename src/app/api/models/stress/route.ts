import { NextResponse } from "next/server";
import { models } from "@/lib/models/registry";
import type { TradeIdea, Instrument, TradeEvidence } from "@/lib/models/types";
import { getEquityExport, findSecurity } from "@/lib/incepta";

// Runs both Stress Test engines on one idea: Distresse (verdict) + Intra (plan).
// If the ticker is covered by the Incepta equity engine, its risk/quality/
// valuation read is attached as evidence and fed into Distresse — the engine is
// the evidence source, Distresse is the judge on top.
export async function POST(req: Request) {
  const body = await req.json().catch(() => ({}));

  const ticker = String(body.ticker ?? "").trim().toUpperCase();
  const instrument = String(body.instrument ?? "long") as Instrument;
  const thesis = String(body.thesis ?? "").trim();

  if (!ticker) {
    return NextResponse.json({ error: "Ticker is required." }, { status: 400 });
  }

  // Look up engine evidence for this ticker (if the equity model covers it).
  let evidence: TradeEvidence | undefined;
  const equity = await getEquityExport();
  if (equity) {
    const sec = findSecurity(equity, ticker);
    // Insufficient-confidence names carry no usable numbers — don't attach them.
    if (sec && sec.confidence !== "insufficient") {
      evidence = {
        source: `Incepta ${equity.schema_version}`,
        confidence: sec.confidence,
        asOf: sec.as_of,
        risk: sec.risk as TradeEvidence["risk"],
        quality: sec.quality as TradeEvidence["quality"],
        valuation: sec.valuation as TradeEvidence["valuation"],
        flags: [
          ...(sec.data_quality.flags ?? []),
          ...(sec.valuation?.flags ?? []),
        ],
      };
    }
  }

  const idea: TradeIdea = {
    ticker,
    instrument,
    thesis,
    horizon: body.horizon ? String(body.horizon) : undefined,
    sizePct: body.sizePct ? Number(body.sizePct) : undefined,
    evidence,
  };

  const [distresse, intra] = await Promise.all([
    models.distresse.evaluate(idea),
    models.intraExitus.plan(idea),
  ]);

  return NextResponse.json({ idea, distresse, intra, evidence: evidence ?? null });
}

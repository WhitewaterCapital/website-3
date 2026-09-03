import type { EquityModel, EquityReading, EquitySignal } from "../types";
import { getEquityExport } from "@/lib/incepta";
import type { SecurityAnalysis } from "../incepta-export";

// ═══════════════════════════════════════════════════════════════════════════
// Equity — an EquityModel (Sentimentum · Equity).
//
// Always grounded in the real Incepta equity export (getEquityExport(),
// reading public/data/incepta/latest.json) — this model has no seeded-random
// demo body, because there's nothing honest a demo body could show that
// looks like a "bottom-up read" without inventing per-name numbers.
//
//   breadth ← mean of rankings.quality[].rank (0..100 percentile) mapped onto
//             -100..100 (percentile 50 == neutral). rankings.quality is
//             Incepta's own cross-sectional composite — a genuine aggregate
//             of real engine output, not something computed from thin air.
//   signals ← the top- and bottom-ranked names, each annotated with real
//             risk/quality/valuation numbers off securities[] (same
//             "engine read" grounding style as distresse.ts's evidence code).
//
// If Incepta hasn't exported yet, read() throws — the same "not implemented
// yet" style the template uses — rather than fabricate a reading. Nothing
// currently renders this model's output directly (SentimentumTabs reads the
// raw EquityExport itself), but any future caller gets the same honest
// contract the rest of the desk's models follow: never invent a number where
// real data is missing.
// ═══════════════════════════════════════════════════════════════════════════

const TOP_N = 3;
const BOTTOM_N = 3;

function percentileToScore(rank: number): number {
  return Math.round((rank - 50) * 2); // 0..100 percentile -> -100..100
}

function signalNote(entry: { rank: number; score: number }, sec: SecurityAnalysis | undefined): string {
  const bits: string[] = [];
  if (sec?.valuation?.pe != null) bits.push(`P/E ${sec.valuation.pe.toFixed(1)}`);
  if (sec?.valuation?.fcf_yield != null) bits.push(`FCF yield ${(sec.valuation.fcf_yield * 100).toFixed(1)}%`);
  if (sec?.quality?.piotroski_f != null) {
    bits.push(`Piotroski ${sec.quality.piotroski_f}/${sec.quality.piotroski_max ?? 9}`);
  }
  if (sec?.risk?.beta_mkt != null) bits.push(`β(mkt) ${sec.risk.beta_mkt.toFixed(2)}`);

  const grounding = bits.length > 0 ? bits.join(", ") : "no risk/quality/valuation data for this name";
  return `${grounding} — composite score ${entry.score.toFixed(2)}, ${entry.rank}th percentile of the universe (engine read).`;
}

export const equityModel: EquityModel = {
  meta: {
    id: "equity",
    name: "Equity",
    kind: "equity",
    status: "live",
    tagline: "Bottom-up, single-name and equity-market read — grounded in Incepta.",
    description:
      "The equity lens inside Sentimentum: aggregates Incepta's real risk/quality/valuation reads across the covered universe into an overall breadth score, and surfaces the strongest and weakest names with their real numbers. Throws rather than fabricates a reading when Incepta hasn't exported yet.",
  },

  async read(dateISO: string): Promise<EquityReading> {
    const data = await getEquityExport();
    if (!data) {
      // No Incepta export yet — never invent a reading. Mirrors the
      // _equity-template.ts contract so any future caller (or SentimentumTabs'
      // existing "not synced yet" card, for the raw export it reads directly)
      // handles this the same honest way the rest of the app does.
      throw new Error("equity model: not implemented yet — Incepta has no export");
    }

    const ranked = [...data.rankings.quality].sort((a, b) => b.rank - a.rank);

    const breadth =
      ranked.length > 0
        ? Math.round(ranked.reduce((s, r) => s + percentileToScore(r.rank), 0) / ranked.length)
        : 0;

    const bySecurity = new Map(data.securities.map((s) => [s.ticker.toUpperCase(), s]));

    // Top- and bottom-ranked names by the engine's own composite. With a
    // small universe (5 names today) these can overlap — dedupe by ticker
    // rather than pad with anything invented.
    const candidates = [...ranked.slice(0, TOP_N), ...ranked.slice(-BOTTOM_N).reverse()];
    const seen = new Set<string>();
    const signals: EquitySignal[] = [];
    for (const r of candidates) {
      if (seen.has(r.ticker)) continue;
      seen.add(r.ticker);
      signals.push({
        symbol: r.ticker,
        score: percentileToScore(r.rank),
        note: signalNote(r, bySecurity.get(r.ticker.toUpperCase())),
      });
    }

    const summary =
      `Ranking ${ranked.length} name${ranked.length === 1 ? "" : "s"} in the current universe on Incepta's ` +
      `composite quality score (engine read, as of ${data.as_of}). Overall breadth ` +
      `${breadth > 0 ? "+" : ""}${breadth} on a -100..100 scale, derived from each name's percentile rank — ` +
      `not a market-cap-weighted index. ${data.disclaimer}`;

    return {
      date: dateISO,
      breadth,
      signals,
      summary,
      generatedBy: "Equity",
    };
  },
};

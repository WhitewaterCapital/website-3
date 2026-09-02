import type { MacroModel, MacroReading } from "../types";
import { aiEnabled, seeded, pick } from "../shared";

// ═══════════════════════════════════════════════════════════════════════════
// Macro Tracker — a MacroModel.
//
// ⚠️  DEMO IMPLEMENTATION. The body of read() below is a stand-in so the UI
//     works today. Replace it with your real macro model.
//
//     Contract:  read(dateISO) → Promise<MacroReading>   (see types.ts)
//     You get:   the date to produce a reading for.
//     You return: regime, overall sentiment (-100..100), per-sector reads,
//                 catalysts, and a background narrative.
//     Real data/AI: pull your feeds + `if (aiEnabled())` call an LLM here.
//     Nothing else in the app changes when you swap this out.
// ═══════════════════════════════════════════════════════════════════════════

const SECTORS = [
  "Technology", "Financials", "Energy", "Healthcare",
  "Industrials", "Consumer Disc.", "Staples", "Materials",
];

export const macroTracker: MacroModel = {
  meta: {
    id: "macro-tracker",
    name: "Macro Tracker",
    kind: "macro",
    status: "live",
    tagline: "Daily cross-sector sentiment, catalysts, and regime read.",
    description:
      "Refreshes every day: reads across sectors, tracks the catalyst calendar, writes the background narrative, and scores overall sentiment. The ambient layer the desk starts the day on.",
  },

  async read(dateISO: string): Promise<MacroReading> {
    // ─── DEMO BODY — replace everything below with your model ──────────────
    const rng = seeded(`macro:${dateISO}`);
    const sectors = SECTORS.map((s) => ({
      sector: s,
      sentiment: Math.round((rng() - 0.45) * 160),
      note: pick(rng, [
        "Breadth improving under the surface.",
        "Earnings revisions rolling over.",
        "Flows positive but momentum stalling.",
        "Rate-sensitive; watch the long end.",
        "Defensive bid returning.",
      ]),
    }));
    const overall = Math.round(
      sectors.reduce((s, x) => s + x.sentiment, 0) / sectors.length,
    );

    const base = new Date(dateISO);
    const catalysts = [
      { offset: 1, event: "CPI print", importance: "high" as const },
      { offset: 3, event: "FOMC minutes", importance: "high" as const },
      { offset: 5, event: "Mega-cap earnings", importance: "medium" as const },
      { offset: 9, event: "Jobs report", importance: "high" as const },
    ].map((c) => ({
      date: new Date(base.getTime() + c.offset * 86400000).toISOString().slice(0, 10),
      event: c.event,
      importance: c.importance,
    }));

    return {
      date: dateISO,
      regime: pick(rng, [
        "Late-cycle, easing bias, dispersion rising",
        "Disinflation holding, soft-landing base case",
        "Growth scare fading, defensives unwinding",
      ]),
      sentiment: overall,
      sectors,
      catalysts,
      summary:
        "Cross-sector read is " +
        (overall > 15 ? "constructive" : overall < -15 ? "cautious" : "mixed") +
        `. Leadership is ${pick(rng, ["narrow", "broadening", "rotating"])}; the tape is trading the ${pick(rng, ["rate path", "earnings cycle", "liquidity backdrop"])} more than fundamentals.`,
      generatedBy: aiEnabled() ? "Macro Tracker" : "Macro Tracker (sample)",
    };
  },
};

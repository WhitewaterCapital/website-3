import type { LevelsModel, TradeIdea, EntryExitPlan } from "../types";
import { aiEnabled, seeded, pick, round } from "../shared";

// ═══════════════════════════════════════════════════════════════════════════
// Intra / Exitus — a LevelsModel (entry and exit).
//
// ⚠️  DEMO IMPLEMENTATION. Replace the body of plan() with your real model.
//
//     Contract:  plan(idea) → Promise<EntryExitPlan>   (see types.ts)
//     You get:   the trade idea.
//     You return: bias, entry zone, stop, targets, sizing, time-stop,
//                 rationale, invalidations.
//     Real data/AI: pull price/vol history, `if (aiEnabled())` add an LLM pass.
//
//     intrare (enter) + exitus (exit) — entry and exit, both defined up front.
// ═══════════════════════════════════════════════════════════════════════════

export const intraExitus: LevelsModel = {
  meta: {
    id: "intra-exitus",
    name: "Intra / Exitus",
    kind: "levels",
    status: "live",
    tagline: "Entry zone and exits — stop, targets, sizing, and time-stops.",
    description:
      "Turns a green-lit idea into a plan: where to get in, where you're wrong, where to scale out, how big, and when to walk away on time rather than price.",
    etymology: "From intrare (to enter) + exitus (a going out — the root of 'exit'). The entry-and-exit counterpart to Distresse.",
  },

  async plan(idea: TradeIdea): Promise<EntryExitPlan> {
    // ─── DEMO BODY — replace everything below with your model ──────────────
    const rng = seeded(`intra:${idea.ticker}:${idea.instrument}`);
    const bias: "long" | "short" =
      idea.instrument === "short" || idea.instrument === "put" ? "short" : "long";

    const anchor = 40 + seeded(idea.ticker)() * 360;
    const px = round(anchor);
    const band = px * (0.015 + rng() * 0.02);

    const entryZone: [number, number] =
      bias === "long"
        ? [round(px - band), round(px - band * 0.2)]
        : [round(px + band * 0.2), round(px + band)];
    const stop = bias === "long" ? round(px - band * 2.4) : round(px + band * 2.4);
    const targets =
      bias === "long"
        ? [round(px + band * 2), round(px + band * 4), round(px + band * 6.5)]
        : [round(px - band * 2), round(px - band * 4), round(px - band * 6.5)];

    return {
      ticker: idea.ticker,
      instrument: idea.instrument,
      bias,
      entryZone,
      stop,
      targets,
      sizingPct: idea.sizePct ?? Math.round((1.5 + rng() * 3) * 10) / 10,
      timeStop: pick(rng, [
        "Exit if the first target isn't tagged within 6 weeks.",
        "Re-evaluate at the next earnings print regardless of level.",
        "Cut on a weekly close back inside the entry band.",
      ]),
      rationale: `Entry is set into the ${bias === "long" ? "prior support / demand" : "prior supply / rejection"} shelf near ${px.toFixed(0)}, with the stop beyond the ${bias === "long" ? "swing low" : "swing high"} so you're wrong on structure, not noise. Targets scale out at ~2R, 4R, and 6R.`,
      invalidations: [
        `${bias === "long" ? "Weekly close below" : "Weekly close above"} ${stop} voids the setup.`,
        "A gap through the entry band on a catalyst — don't chase; re-plan.",
        "Volatility regime shift (VIX spike) — halve size or stand aside.",
      ],
      generatedBy: aiEnabled() ? "Intra / Exitus" : "Intra / Exitus (sample)",
    };
  },
};

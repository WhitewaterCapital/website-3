import type { LevelsModel, TradeIdea, EntryExitPlan } from "../types";
import { seeded, pick, round } from "../shared";
import { getIntraExitusExport } from "@/lib/intra-exitus";
import type { IntraExitusPlan } from "../intra-exitus-export";

// ═══════════════════════════════════════════════════════════════════════════
// Intra / Exitus — a LevelsModel (entry and exit).
//
// plan(idea) first tries the real Intra/Exitus engine export (
// getIntraExitusExport(), reading public/data/intra-exitus/latest.json) for a
// plan matching idea.ticker. Three outcomes:
//
//   1. Ticker not in the real export (outside its ~5-name covered universe,
//      or the engine hasn't synced at all) — fall back to the labelled demo
//      band, exactly as before. generatedBy: "Intra / Exitus (sample)".
//
//   2. Real plan found, and it's actionable/watch with real levels — map its
//      fields straight onto EntryExitPlan. generatedBy: "Intra / Exitus".
//
//   3. Real plan found, but the engine abstained (confidence "insufficient",
//      or any of entryZone/stop/sizingPct is null despite everything else) —
//      render an honest "abstained" plan. EntryExitPlan's fields are plain,
//      non-nullable numbers (we don't own types.ts, so we can't widen them to
//      allow null); rather than synthesize a plausible-looking band — which
//      this codebase's honesty rules forbid, see intra-exitus-export.ts and
//      aurora-export.ts — we surface literal NaN, the one numeric value that
//      cannot be mistaken for a real price. Never use lastClose to fake a
//      band here — that's exactly the "synthesized level" this case exists to
//      avoid. generatedBy: "Intra / Exitus (insufficient — engine abstained)".
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
      "Turns a green-lit idea into a plan: where to get in, where you're wrong, where to scale out, how big, and when to walk away on time rather than price. Reads the real Intra/Exitus engine export for covered tickers — including its honest abstains — and falls back to a clearly-labelled sample band outside that coverage.",
    etymology: "From intrare (to enter) + exitus (a going out — the root of 'exit'). The entry-and-exit counterpart to Distresse.",
  },

  async plan(idea: TradeIdea): Promise<EntryExitPlan> {
    const data = await getIntraExitusExport();
    const wanted = idea.ticker.trim().toUpperCase();
    const real = data?.plans.find((p) => p.ticker.toUpperCase() === wanted);

    if (!real) return demoPlan(idea); // outside coverage, or engine not synced

    const abstained =
      real.confidence === "insufficient" ||
      (real.bias !== "long" && real.bias !== "short") ||
      real.entryZone == null ||
      real.stop == null ||
      real.sizingPct == null;

    return abstained ? abstainedPlan(idea, real) : realPlan(idea, real);
  },
};

// ─── Real, actionable/watch plan ────────────────────────────────────────────

function realPlan(idea: TradeIdea, real: IntraExitusPlan): EntryExitPlan {
  return {
    ticker: idea.ticker,
    instrument: idea.instrument,
    bias: real.bias as "long" | "short", // checked above: only "long"/"short" reach here
    entryZone: real.entryZone as [number, number],
    stop: real.stop as number,
    targets: real.targets,
    sizingPct: real.sizingPct as number,
    timeStop: real.timeStop,
    rationale: real.rationale,
    invalidations: real.invalidations,
    generatedBy: "Intra / Exitus",
  };
}

// ─── Real plan, but the engine abstained — honest "no levels" render ───────

function abstainedPlan(idea: TradeIdea, real: IntraExitusPlan): EntryExitPlan {
  const bias: "long" | "short" =
    idea.instrument === "short" || idea.instrument === "put" ? "short" : "long";

  return {
    ticker: idea.ticker,
    instrument: idea.instrument,
    // The engine's own call was "none" (no direction) — this is only the
    // idea's stated instrument direction, not an engine signal.
    bias,
    // No fabricated band: NaN, not a synthesized number derived from lastClose.
    entryZone: [Number.NaN, Number.NaN],
    stop: Number.NaN,
    targets: [],
    sizingPct: Number.NaN,
    timeStop:
      real.timeStop && real.timeStop !== "—"
        ? real.timeStop
        : "No time-stop — the engine abstained; there is no plan to time out of.",
    rationale:
      `Intra / Exitus abstained on ${real.ticker} (confidence: ${real.confidence}): ${real.rationale} ` +
      `No entry, stop, or size are computed here — this is a "stand aside" read, not a plan, and the ` +
      `numeric fields above are not real levels.`,
    invalidations: real.invalidations,
    generatedBy: "Intra / Exitus (insufficient — engine abstained)",
  };
}

// ─── Demo fallback — unchanged from the original seeded-random implementation,
//     used only when the real engine doesn't cover this ticker at all. ─────

function demoPlan(idea: TradeIdea): EntryExitPlan {
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
    generatedBy: "Intra / Exitus (sample)",
  };
}

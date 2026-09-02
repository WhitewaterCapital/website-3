import type { EvaluatorModel, TradeIdea, StressVerdict, Rating, Dimension } from "../types";
import { aiEnabled, seeded, pick } from "../shared";

// ═══════════════════════════════════════════════════════════════════════════
// Distresse — an EvaluatorModel (the adversarial stress test).
//
// ⚠️  DEMO IMPLEMENTATION. Replace the body of evaluate() with your real model.
//
//     Contract:  evaluate(idea) → Promise<StressVerdict>   (see types.ts)
//     You get:   the trade idea (ticker, instrument, thesis, horizon, size).
//     You return: rating (go/conditional/no-go), conviction, a dimension
//                 scorecard, devil's-advocate points, tail risks, bottom line.
//     Real AI:   `if (aiEnabled())` call an LLM with the idea + your quant/macro
//                inputs and return the same StressVerdict shape.
// ═══════════════════════════════════════════════════════════════════════════

export const distresse: EvaluatorModel = {
  meta: {
    id: "distresse",
    name: "Distresse",
    kind: "evaluator",
    status: "live",
    tagline: "Adversarial quant/macro stress test — a straight go / no-go.",
    description:
      "Takes a trade idea and sees it from an eagle-eye: macro regime fit, factor exposure, crowding, valuation, catalyst and tail risk. Plays devil's advocate, then gives a blunt call.",
    etymology: "From Latin districtia — to be pulled apart, stretched, stressed.",
  },

  async evaluate(idea: TradeIdea): Promise<StressVerdict> {
    // ─── DEMO BODY — replace everything below with your model ──────────────
    const rng = seeded(`distresse:${idea.ticker}:${idea.instrument}`);
    const isShort = idea.instrument === "short" || idea.instrument === "put";

    const dims: Dimension[] = [
      { label: "Macro regime fit", score: Math.round((rng() - 0.5) * 160), note: "" },
      { label: "Factor exposure", score: Math.round((rng() - 0.5) * 160), note: "" },
      { label: "Positioning / crowding", score: Math.round((rng() - 0.5) * 160), note: "" },
      { label: "Valuation vs history", score: Math.round((rng() - 0.5) * 160), note: "" },
      { label: "Catalyst path", score: Math.round((rng() - 0.5) * 160), note: "" },
      { label: "Liquidity / correlation", score: Math.round((rng() - 0.5) * 160), note: "" },
    ];
    const notes: Record<string, string[]> = {
      "Macro regime fit": [
        "Rate path is a headwind to the multiple here.",
        "Fits a soft-landing, disinflation regime.",
        "Cyclically exposed into a slowing ISM.",
      ],
      "Factor exposure": [
        "Loads heavily on momentum — crowded factor.",
        "Quality tilt cushions a drawdown.",
        "High-beta; amplifies any index move.",
      ],
      "Positioning / crowding": [
        "Consensus long; little marginal buyer left.",
        "Under-owned vs peers — room to re-rate.",
        "Elevated short interest; squeeze risk both ways.",
      ],
      "Valuation vs history": [
        "Rich on every multiple vs its own 5y range.",
        "Cheap only if you believe the out-year numbers.",
        "Mid-range — valuation isn't the edge here.",
      ],
      "Catalyst path": [
        "Next print is the whole thesis — binary.",
        "Several small catalysts, none decisive.",
        "Catalyst is 2+ quarters out; carry cost matters.",
      ],
      "Liquidity / correlation": [
        "Moves with the index — not a differentiated bet.",
        "Idiosyncratic; low correlation to the book.",
        "Thin borrow / wide spreads raise the cost.",
      ],
    };
    for (const d of dims) d.note = pick(rng, notes[d.label]);

    const avg = dims.reduce((s, d) => s + d.score, 0) / dims.length;
    const rating: Rating = avg > 25 ? "go" : avg < -20 ? "no-go" : "conditional";
    const conviction = Math.min(95, Math.round(40 + Math.abs(avg) * 0.6));

    const devils = [
      `The bull case leans on ${pick(rng, ["multiple expansion", "flawless execution", "a macro tailwind"])} that isn't in your control.`,
      `If ${idea.ticker} ${isShort ? "surprises to the upside" : "misses next quarter"}, where is your out — and is the crowd on the same side of that door?`,
      `You're being paid ${pick(rng, ["thin", "average", "decent"])} risk-adjusted return for a ${pick(rng, ["macro", "single-name", "factor"])} risk you can't hedge cleanly.`,
    ];
    const tails = [
      "A sharp move in rates or the dollar swamps the single-name thesis.",
      `A liquidity air-pocket around the catalyst gaps ${idea.ticker} through your stop.`,
      isShort ? "A takeout / activist headline forces a cover at the worst price." : "A guide-down resets the whole sector, not just the name.",
    ];

    const bottom =
      rating === "go"
        ? `Straight up: this clears the bar. The macro and positioning line up, and the risk you're taking is the one your thesis is actually about. Size it and define the invalidation.`
        : rating === "no-go"
          ? `Straight up: pass. Too much of the return depends on things you don't control, and the regime is leaning against you. Good name, wrong setup.`
          : `Straight up: only with conditions. The idea has legs but the ${pick(rng, ["valuation", "crowding", "catalyst timing"])} is doing too much work. Wait for a better entry or hedge the macro leg.`;

    // If engine evidence rode along (e.g. Incepta), ground the scorecard notes
    // in the real numbers — the engine is the evidence, this judge sits on top.
    if (idea.evidence) {
      const r: Record<string, number | null> = idea.evidence.risk ?? {};
      const v: Record<string, number | null> = idea.evidence.valuation ?? {};
      const pctS = (x?: number | null) => (x == null ? "—" : `${(x * 100).toFixed(0)}%`);
      const numS = (x?: number | null, d = 2) => (x == null ? "—" : x.toFixed(d));
      const set = (label: string, note: string) => {
        const dim = dims.find((x) => x.label === label);
        if (dim) dim.note = note;
      };
      set("Factor exposure", `β(mkt) ${numS(r.beta_mkt)}, 12-1 momentum ${pctS(r.mom_12_1)} (engine read).`);
      set(
        "Valuation vs history",
        v.pe == null ? "P/E not meaningful here — see flags." : `P/E ${numS(v.pe, 1)}, FCF yield ${pctS(v.fcf_yield)} (engine read).`,
      );
      set("Liquidity / correlation", `Est. spread ${numS(r.spread_bps, 0)} bps, idio vol ${pctS(r.idio_vol)} (engine read).`);
      if (idea.evidence.flags?.length) {
        devils.push(`Engine flags: ${idea.evidence.flags.join("; ")}.`);
      }
    }

    const evidenceTag = idea.evidence
      ? ` · on ${idea.evidence.source} evidence (${idea.evidence.confidence})`
      : "";

    return {
      ticker: idea.ticker,
      instrument: idea.instrument,
      rating,
      conviction,
      regime: pick(rng, [
        "Late-cycle, easing bias, dispersion rising",
        "Disinflationary soft-landing, momentum-led tape",
        "Slowing growth, sticky rates, defensive rotation",
      ]),
      dimensions: dims,
      devilsAdvocate: devils,
      tailRisks: tails,
      bottomLine: bottom,
      generatedBy: (aiEnabled() ? "Distresse" : "Distresse (sample)") + evidenceTag,
    };
  },
};

import type { MacroModel, MacroReading, SectorRead, Catalyst } from "../types";
import { seeded, pick } from "../shared";
import { getMacroExport } from "@/lib/aurora";
import type { MacroExport, RegimeRead } from "../aurora-export";

// ═══════════════════════════════════════════════════════════════════════════
// Macro Tracker — a MacroModel.
//
// read(dateISO) first tries the real Aurora macro snapshot (getMacroExport(),
// reading public/data/aurora/latest.json). Aurora is a structural regime/
// scenario model, not a sector-picker or a news calendar, so not every field
// below has a direct Aurora source — each one says exactly where its number
// came from, and falls back to the old seeded demo ONLY for the pieces Aurora
// genuinely doesn't provide (or hasn't synced yet), never silently.
//
//   regime     ← export.regime.label                      (real, when present)
//   sentiment  ← nowcast skillful factors, else regime     (real, when present)
//               scenario-affinity skew, else demo
//   sectors    ← tilt.sectors, else tilt.factors,          (real, when present)
//               else demo
//   catalysts  ← ALWAYS the demo calendar — Aurora has no discrete event
//               calendar (it does scenario/regime modeling, not news), so
//               these are explicitly labelled sample entries, never claimed
//               as real scheduled events.
//   summary    ← nowcast.summary / book_read / regime,     (real, when present)
//               else the old demo narrative
//
// generatedBy is "Macro Tracker" the moment ANY real Aurora field made it into
// the reading, "Macro Tracker (sample)" only when nothing real was available
// (Aurora not synced yet, or every field on the export was null).
// ═══════════════════════════════════════════════════════════════════════════

const SECTORS = [
  "Technology", "Financials", "Energy", "Healthcare",
  "Industrials", "Consumer Disc.", "Staples", "Materials",
];

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function leanScore(lean: "overweight" | "neutral" | "underweight"): number {
  return lean === "overweight" ? 60 : lean === "underweight" ? -60 : 0;
}

// ─── Demo pieces — unchanged from the original seeded-random implementation,
//     kept as named fallbacks so each field can fall back independently. ─────

function demoSectors(rng: () => number): SectorRead[] {
  return SECTORS.map((s) => ({
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
}

function demoCatalysts(dateISO: string): Catalyst[] {
  const base = new Date(dateISO);
  return [
    { offset: 1, event: "CPI print", importance: "high" as const },
    { offset: 3, event: "FOMC minutes", importance: "high" as const },
    { offset: 5, event: "Mega-cap earnings", importance: "medium" as const },
    { offset: 9, event: "Jobs report", importance: "high" as const },
  ].map((c) => ({
    date: new Date(base.getTime() + c.offset * 86400000).toISOString().slice(0, 10),
    event: c.event,
    importance: c.importance,
  }));
}

function demoRegime(rng: () => number): string {
  return pick(rng, [
    "Late-cycle, easing bias, dispersion rising",
    "Disinflation holding, soft-landing base case",
    "Growth scare fading, defensives unwinding",
  ]);
}

function demoNarrative(rng: () => number, overall: number): string {
  return (
    "Cross-sector read is " +
    (overall > 15 ? "constructive" : overall < -15 ? "cautious" : "mixed") +
    `. Leadership is ${pick(rng, ["narrow", "broadening", "rotating"])}; the tape is trading the ${pick(rng, ["rate path", "earnings cycle", "liquidity backdrop"])} more than fundamentals.`
  );
}

function fullDemoReading(dateISO: string): MacroReading {
  const rng = seeded(`macro:${dateISO}`);
  const sectors = demoSectors(rng);
  const overall = Math.round(sectors.reduce((s, x) => s + x.sentiment, 0) / sectors.length);
  return {
    date: dateISO,
    regime: demoRegime(rng),
    sentiment: overall,
    sectors,
    catalysts: demoCatalysts(dateISO),
    summary: demoNarrative(rng, overall),
    generatedBy: "Macro Tracker (sample)",
  };
}

// ─── Sentiment from real Aurora data ────────────────────────────────────────
//
// HONESTY: Aurora's nowcast only surfaces `expected_return` when a factor is
// out-of-sample `skillful` — in the live export today every factor comes back
// `skillful: false` with `expected_return: null` (no factor-timing edge right
// now), so this path currently falls through every time. It's kept as the
// preferred source because it's the most direct forward-looking number Aurora
// produces, for whenever the nowcaster does find an edge.
//
// Falling back to the regime's scenario-affinity mix: a coarse, documented
// risk-on/risk-off skew across Aurora's named regime scenarios, damped by the
// regime read's own confidence (real data today: confidence "low") so a shaky
// call doesn't read as a strong signal.
//
// Schema-drift note: the aurora-export.ts contract (schema doc v0.1.0) names
// this field `probabilities`; the live v0.2.0 export instead names it
// `scenario_affinity`. Both are read here so this keeps working either way.
function sentimentFromAurora(data: MacroExport): number | null {
  const skillful = (data.nowcast?.factors ?? []).filter(
    (f) =>
      f.skillful &&
      f.expected_return != null &&
      (f.confidence === "high" || f.confidence === "medium"),
  );
  if (skillful.length > 0) {
    const avg =
      skillful.reduce((s, f) => s + (f.expected_return as number), 0) / skillful.length;
    // expected_return is a forward-horizon % as a decimal (e.g. 0.03 = 3%);
    // scale onto the -100..100 read the rest of the desk uses.
    return clamp(Math.round(avg * 1000), -100, 100);
  }

  const regime = data.regime;
  if (!regime || regime.confidence === "insufficient") return null;

  const regimeCompat = regime as RegimeRead & { scenario_affinity?: Record<string, number> | null };
  const affinity = regime.probabilities ?? regimeCompat.scenario_affinity ?? null;
  if (!affinity || Object.keys(affinity).length === 0) return null;

  const weightOf = (label: string): number => {
    if (/restrictive|tighten/i.test(label)) return -1; // risk-off
    if (/expansion|valuation boom|demand.*boom/i.test(label)) return 1; // risk-on
    return 0; // housing-driven, mixed/transitional, or unrecognized — no clear broad lean
  };
  const skew = Object.entries(affinity).reduce((s, [label, prob]) => s + weightOf(label) * prob, 0);
  const confidenceMultiplier =
    regime.confidence === "high" ? 1 : regime.confidence === "medium" ? 0.7 : 0.4;
  return clamp(Math.round(skew * 100 * confidenceMultiplier), -100, 100);
}

export const macroTracker: MacroModel = {
  meta: {
    id: "macro-tracker",
    name: "Macro Tracker",
    kind: "macro",
    status: "live",
    tagline: "Daily cross-sector sentiment, catalysts, and regime read.",
    description:
      "Refreshes every day: reads across sectors, tracks the catalyst calendar, writes the background narrative, and scores overall sentiment. The ambient layer the desk starts the day on. Backed by the real Aurora macro snapshot where Aurora provides a signal; the catalyst calendar is always an illustrative sample, since Aurora is a scenario/regime model, not a news calendar.",
  },

  async read(dateISO: string): Promise<MacroReading> {
    const data = await getMacroExport();
    if (!data) return fullDemoReading(dateISO); // Aurora not synced yet

    const rng = seeded(`macro:${dateISO}`); // only used for whichever pieces fall back
    let usedReal = false;
    const honestyNotes: string[] = [];

    // ── regime ────────────────────────────────────────────────────────────
    let regime: string;
    if (data.regime?.label) {
      regime = data.regime.label;
      usedReal = true;
    } else {
      regime = demoRegime(rng);
      honestyNotes.push("no regime label from Aurora yet — regime above is an illustrative sample");
    }

    // ── sectors ───────────────────────────────────────────────────────────
    const tiltSectors = data.tilt?.sectors ?? [];
    const tiltFactors = data.tilt?.factors ?? [];
    let sectors: SectorRead[];
    if (tiltSectors.length > 0) {
      sectors = tiltSectors.map((s) => ({
        sector: s.name,
        sentiment: leanScore(s.lean),
        note: `${s.rationale} (Aurora tilt — engine read).`,
      }));
      usedReal = true;
    } else if (tiltFactors.length > 0) {
      sectors = tiltFactors.map((f) => ({
        sector: `${f.name} (factor)`,
        sentiment: leanScore(f.lean),
        note: `${f.rationale} (Aurora's factor tilt — engine read).`,
      }));
      usedReal = true;
      honestyNotes.push("Aurora's sector tilt is empty right now; showing its factor tilt in its place");
    } else {
      sectors = demoSectors(rng);
      honestyNotes.push("Aurora's sector and factor tilt are both empty right now — sector reads above are an illustrative sample, not engine output");
    }

    // ── sentiment ─────────────────────────────────────────────────────────
    const realSentiment = sentimentFromAurora(data);
    let overall: number;
    if (realSentiment != null) {
      overall = realSentiment;
      usedReal = true;
    } else {
      overall = Math.round((rng() - 0.5) * 60);
      honestyNotes.push("no skillful nowcast factor and no usable regime-affinity signal — overall sentiment above is an illustrative sample number");
    }

    // ── catalysts — always the sample calendar; Aurora models scenarios and
    //    regimes, not a discrete event calendar, so there is no real source
    //    to read here at all. ─────────────────────────────────────────────
    const catalysts = demoCatalysts(dateISO).map((c) => ({ ...c, event: `${c.event} (sample)` }));
    honestyNotes.push("Aurora has no discrete event calendar — the catalyst dates above are illustrative sample entries, not real scheduled events");

    // ── summary ───────────────────────────────────────────────────────────
    const realSummaryParts: string[] = [];
    if (data.nowcast?.summary) realSummaryParts.push(data.nowcast.summary);
    if (data.nowcast?.book_read) realSummaryParts.push(data.nowcast.book_read);
    if (data.regime?.label) {
      realSummaryParts.push(`Regime read: "${data.regime.label}" (confidence: ${data.regime.confidence}).`);
    }
    if (data.regime?.flags?.length) realSummaryParts.push(`Flags: ${data.regime.flags.join("; ")}.`);

    const base = realSummaryParts.length > 0 ? realSummaryParts.join(" ") : demoNarrative(rng, overall);
    const summary = `${base} Honesty note: ${honestyNotes.join("; ")}.`;

    return {
      date: dateISO,
      regime,
      sentiment: overall,
      sectors,
      catalysts,
      summary,
      generatedBy: usedReal ? "Macro Tracker" : "Macro Tracker (sample)",
    };
  },
};

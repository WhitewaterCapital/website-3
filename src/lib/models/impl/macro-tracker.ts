import type { MacroModel, MacroReading, SectorRead, Catalyst } from "../types";
import { seeded, pick } from "../shared";
import { getMacroExport } from "@/lib/aurora";
import type { MacroExport, RegimeRead } from "../aurora-export";
import { fetchFredLatest, fetchFredSeries } from "@/lib/fred";

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
//               else FRED yield-curve + jobless-claims read (real, when present — see below)
//               else demo
//   sentiment  ← nowcast skillful factors, else regime     (real, when present)
//               scenario-affinity skew,
//               else FRED yield-curve + jobless-claims read (real, when present)
//               else demo
//   sectors    ← tilt.sectors, else tilt.factors,          (real, when present)
//               else demo
//   catalysts  ← ALWAYS the demo calendar — Aurora has no discrete event
//               calendar (it does scenario/regime modeling, not news), so
//               these are explicitly labelled sample entries, never claimed
//               as real scheduled events.
//   summary    ← nowcast.summary / book_read / regime,     (real, when present)
//               else the old demo narrative
//
// [Added 2026-09-13, PLATFORM_REBUILD_PLAN.md priority #5] Regime/sentiment
// now have a THIRD, genuinely real tier between "Aurora" and "demo RNG":
// `fredRegimeFallback()` below reads the 10Y-2Y Treasury spread (T10Y2Y) and
// initial jobless claims (ICSA) directly from FRED — the same free source,
// via the same shared `@/lib/fred` helper, Distresse's own "Macro regime
// fit" dimension already uses. This fires whenever Aurora hasn't synced at
// all (`getMacroExport()` returns null — previously 100% RNG in that case)
// or when Aurora's own export is present but doesn't carry a usable
// regime/sentiment read yet. It is deliberately coarse and market-wide (says
// nothing about any one sector), same honesty framing as Distresse's use of
// the identical data.
//
// generatedBy is "Macro Tracker" the moment ANY real Aurora field made it into
// the reading, "Macro Tracker (FRED)" when regime/sentiment came from the
// FRED fallback instead (with sectors/catalysts still demo, since FRED has
// no sector-level view), "Macro Tracker (sample)" only when nothing real was
// available at all.
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

// ─── Real regime/sentiment fallback — FRED yield curve + jobless claims ────
// Two real, free (once FRED_API_KEY is set), market-wide series, read via the
// shared `@/lib/fred` helper (the same one Distresse's "Macro regime fit"
// dimension uses): the 10Y-2Y Treasury spread (curve shape) and initial
// jobless claims (a real-time labor-market read). Deliberately simple,
// explicitly unbacktested linear scoring — same honesty framing as
// Distresse's own use of T10Y2Y — a real cross-check, not a substitute for
// Aurora's own (considerably more sophisticated) regime model. Returns null
// when FRED_API_KEY is unset or BOTH series are unreachable — callers must
// fall through to the demo path rather than fabricate a reading.
type FredRegimeRead = { regime: string; sentiment: number; note: string };

async function fredRegimeFallback(): Promise<FredRegimeRead | null> {
  const [curve, claims] = await Promise.all([
    fetchFredLatest("T10Y2Y"),
    fetchFredSeries("ICSA", 8), // weekly initial jobless claims, most-recent-first
  ]);

  const parts: string[] = [];
  let scoreSum = 0;
  let signals = 0;
  let claimsTrend: "rising" | "falling" | "flat" | null = null;

  if (curve) {
    const curveWord = curve.value < -0.1 ? "inverted" : curve.value < 0.15 ? "flat" : "normal/steep";
    const spreadTxt = `${curve.value >= 0 ? "+" : ""}${curve.value.toFixed(2)}pp`;
    parts.push(`10Y-2Y curve ${spreadTxt} (${curveWord}) as of ${curve.date}`);
    // Same linear scale as Distresse's own use of this series: +2.0pp -> +100.
    scoreSum += clamp(curve.value * 50, -100, 100);
    signals++;
  }

  if (claims.length >= 2) {
    const latest = claims[0].value;
    const priorWindow = claims.slice(1, Math.min(5, claims.length));
    const priorAvg = priorWindow.reduce((s, o) => s + o.value, 0) / priorWindow.length;
    const pctChange = priorAvg > 0 ? (latest - priorAvg) / priorAvg : 0;
    claimsTrend = pctChange > 0.05 ? "rising" : pctChange < -0.05 ? "falling" : "flat";
    parts.push(
      `initial jobless claims ${claimsTrend} (latest ${Math.round(latest / 1000)}k vs. ${priorWindow.length}-week avg ${Math.round(priorAvg / 1000)}k) as of ${claims[0].date}`,
    );
    // Rising claims = labor market softening = risk-off lean; falling = risk-on.
    scoreSum += clamp(-pctChange * 400, -100, 100);
    signals++;
  }

  if (signals === 0) return null; // FRED_API_KEY unset, or both series unreachable right now

  const sentiment = clamp(Math.round(scoreSum / signals), -100, 100);
  let regime: string;
  if (curve && curve.value < -0.1 && claimsTrend === "rising") {
    regime = "Yield curve inverted, jobless claims rising — real macro data leans late-cycle/growth-scare";
  } else if (curve && curve.value >= 0.15 && claimsTrend !== "rising") {
    regime = "Yield curve normal/steep, labor market steady — real macro data leans expansion-consistent";
  } else if (curve) {
    regime = `Yield curve ${curve.value < 0.15 ? "flat" : "steep"}, labor-market signal ${claimsTrend ?? "unavailable"} — mixed real macro data, no clean regime call`;
  } else {
    regime = `Jobless claims ${claimsTrend ?? "unavailable"} — yield curve unavailable this read, partial real macro data only`;
  }

  return {
    regime,
    sentiment,
    note: `Real FRED data (not Aurora, not fabricated): ${parts.join("; ")}.`,
  };
}

async function fullDemoReading(dateISO: string): Promise<MacroReading> {
  const rng = seeded(`macro:${dateISO}`);
  const sectors = demoSectors(rng);
  const demoOverall = Math.round(sectors.reduce((s, x) => s + x.sentiment, 0) / sectors.length);

  // [2026-09-13] Aurora hasn't synced at all — try the real FRED fallback
  // before giving up to full RNG, rather than the previous behavior (100%
  // fabricated regime/sentiment whenever Aurora's export was simply missing).
  const fred = await fredRegimeFallback();
  const usedReal = fred != null;
  const regime = fred?.regime ?? demoRegime(rng);
  const overall = fred?.sentiment ?? demoOverall;
  const narrative = demoNarrative(rng, overall);
  const summary = fred
    ? `${narrative} Real macro cross-check (Aurora not synced yet): ${fred.note}`
    : narrative;

  return {
    date: dateISO,
    regime,
    sentiment: overall,
    sectors,
    catalysts: demoCatalysts(dateISO),
    summary,
    generatedBy: usedReal ? "Macro Tracker (FRED, Aurora not synced)" : "Macro Tracker (sample)",
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
    let usedFred = false;
    const honestyNotes: string[] = [];

    // [2026-09-13] Aurora synced, but may not carry a regime label and/or a
    // usable sentiment read (its own doc above notes every nowcast factor
    // currently comes back non-skillful) — only pay for the FRED fetch when
    // at least one of those is actually missing; the result is cached 6h
    // either way (see @/lib/fred), so a second read in that window is free.
    const auroraSentiment = sentimentFromAurora(data);
    const needsFredFallback = !data.regime?.label || auroraSentiment == null;
    const fred = needsFredFallback ? await fredRegimeFallback() : null;

    // ── regime ────────────────────────────────────────────────────────────
    let regime: string;
    if (data.regime?.label) {
      regime = data.regime.label;
      usedReal = true;
    } else if (fred) {
      regime = fred.regime;
      usedReal = true;
      usedFred = true;
      honestyNotes.push("no regime label from Aurora yet — regime above is a real FRED yield-curve/jobless-claims read, not Aurora's own regime model");
    } else {
      regime = demoRegime(rng);
      honestyNotes.push("no regime label from Aurora yet, and FRED_API_KEY unset or FRED unreachable — regime above is an illustrative sample");
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
    let overall: number;
    if (auroraSentiment != null) {
      overall = auroraSentiment;
      usedReal = true;
    } else if (fred) {
      overall = fred.sentiment;
      usedReal = true;
      usedFred = true;
      honestyNotes.push("no skillful nowcast factor and no usable regime-affinity signal from Aurora — sentiment above is a real FRED yield-curve/jobless-claims read instead");
    } else {
      overall = Math.round((rng() - 0.5) * 60);
      honestyNotes.push("no skillful nowcast factor and no usable regime-affinity signal, and FRED_API_KEY unset or FRED unreachable — overall sentiment above is an illustrative sample number");
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

    let base = realSummaryParts.length > 0 ? realSummaryParts.join(" ") : demoNarrative(rng, overall);
    if (fred) base += ` Real FRED cross-check: ${fred.note}`;
    const summary = `${base} Honesty note: ${honestyNotes.join("; ")}.`;

    return {
      date: dateISO,
      regime,
      sentiment: overall,
      sectors,
      catalysts,
      summary,
      generatedBy: !usedReal ? "Macro Tracker (sample)" : usedFred ? "Macro Tracker (Aurora + FRED)" : "Macro Tracker",
    };
  },
};

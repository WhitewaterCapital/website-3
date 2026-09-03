import type { Position } from "@/lib/types";
import type { PositionEntryContext } from "@/lib/types";
import type { EntryExitPlan, StressVerdict } from "@/lib/models/types";
import type { GraphExport } from "@/lib/models/graph-export";
import type { WeeklyExport, WeeklyForecast } from "@/lib/models/weekly-export";
import type { StateExport } from "@/lib/models/state-export";
import { getHorizon } from "@/lib/models/horizons";

// ═══════════════════════════════════════════════════════════════════════════
// WATCH-01 — the rules-based position monitor.
//
// `runChecks(...)` is the single entry point: give it one open position plus
// whatever real-engine reads happen to be available, and it returns a typed
// PositionCheck — a list of individually-labelled CheckResults, each of which
// is either a genuine read (`available: true`) or an honest "can't compute
// this, here's why" (`available: false, reason: "..."`). NOTHING in this file
// invents a number. Where this codebase has no real data source at all for
// something the design doc asks for (options-implied expected move, a real
// news/event vector, real positioning/flow data), that shows up as a fixed
// `available: false` entry with a reason string — see the bottom of
// `runChecks` — never as a fabricated placeholder.
//
// Signature note: the task brief describes this as
//   runChecks(position, plan, verdict, graphExport?, weeklyExport?, stateExport?)
// which this keeps verbatim as the first six parameters. Two more inputs
// turned out to be genuinely required once the checks were written for real
// (a book-wide correlation/concentration read needs the REST of the book; the
// "did the forecast change since entry" check needs an entry-time snapshot,
// and there is no history store anywhere in this codebase to fetch one from —
// see PositionEntryContext in src/lib/types.ts) — those are bundled into a
// trailing `opts` object rather than silently added as positional params.
// ═══════════════════════════════════════════════════════════════════════════

export type CheckSeverity = "ok" | "info" | "warn" | "alert";

export interface CheckResult {
  id: string; // stable machine key
  label: string; // human label, shown as a section heading
  severity: CheckSeverity; // meaningless when available is false — always "info" then
  available: boolean; // false => this check produced no real signal at all
  reason?: string; // REQUIRED context for why, whenever available is false
  detail: string; // one-paragraph human explanation of the read (or the gap)
  data?: Record<string, unknown>; // raw numbers behind `detail`, for the UI / eyeballing
}

// The book-wide context a check computed along the way, carried on the result
// so urgency.ts (WATCH-02) can build an honest expected-range WITHOUT having
// to re-fetch or recompute any of it — see urgency.ts's header comment for why
// this exists as its own object instead of just re-deriving from `checks`.
export interface PositionCheckContext {
  currentPriceUsd: number;
  bias: "long" | "short" | null; // null when the plan itself is unusable (see below)
  weeklyQuantile: { p10: number; p50: number; p90: number } | null; // real WW-WEEKLY band, when covered
  dimensionDispersion: number | null; // stdev of StressVerdict.dimensions scores (-100..100 scale) — a rough uncertainty proxy for tickers WW-WEEKLY doesn't cover
  stateVolatilityZ: number | null; // WW-STATE's realised-vol z-read, book-wide, when the export exists
}

export interface PositionCheck {
  symbol: string;
  asOf: string; // ISO timestamp this whole read was computed at
  checks: CheckResult[];
  context: PositionCheckContext;
}

export interface RunChecksOptions {
  entryContext?: PositionEntryContext; // the hand-authored "as of entry" snapshot, if one exists for this symbol
  book?: Position[]; // the rest of the open book, for the concentration/correlation proxy (include this position too, or not — both are handled)
  nowIso?: string; // inject "now" for deterministic testing; defaults to the real clock
}

// ─────────────────────────────────────────────────────────────────────────
// Small shared helpers
// ─────────────────────────────────────────────────────────────────────────

const SEVERITY_RANK: Record<CheckSeverity, number> = { ok: 0, info: 1, warn: 2, alert: 3 };
function worseOf(a: CheckSeverity, b: CheckSeverity): CheckSeverity {
  return SEVERITY_RANK[a] >= SEVERITY_RANK[b] ? a : b;
}

// A demo/fallback plan is tagged with "(sample)" in generatedBy by every
// model in this codebase (see impl/intra-exitus.ts, impl/distresse.ts) — the
// same convention EquityReader.tsx already keys its own "⚠ SAMPLE" banner off
// of. Reused here rather than re-invented.
function isSampleGenerated(generatedBy: string): boolean {
  return generatedBy.toLowerCase().includes("sample");
}

function isAbstainedPlan(plan: EntryExitPlan): boolean {
  return (
    Number.isNaN(plan.stop) ||
    plan.entryZone.some((v) => Number.isNaN(v)) ||
    plan.generatedBy.toLowerCase().includes("abstain")
  );
}

// A real, price-anchored plan: not abstained, and not the demo fallback.
// impl/intra-exitus.ts's demo fallback (`demoPlan`) derives its price levels
// from a hash of the ticker string alone — entirely unrelated to the actual
// position's avgCostUsd/lastPriceUsd — so distance-to-stop/target math against
// a demo plan would compare a real dollar price to a number that just happens
// to share its currency. That is exactly the kind of "looks like a number,
// isn't a real read" this file is written to avoid — see the comment on
// `invalidationTrafficLight` below for how that plays out for the sample book.
function isUsablePricedPlan(plan: EntryExitPlan): boolean {
  return !isAbstainedPlan(plan) && !isSampleGenerated(plan.generatedBy);
}

function daysBetween(fromIso: string, toIso: string): number {
  const from = new Date(fromIso).getTime();
  const to = new Date(toIso).getTime();
  return Math.floor((to - from) / (24 * 60 * 60 * 1000));
}

function mean(xs: number[]): number {
  return xs.reduce((s, x) => s + x, 0) / xs.length;
}

function stdev(xs: number[]): number {
  const m = mean(xs);
  return Math.sqrt(mean(xs.map((x) => (x - m) ** 2)));
}

// ─────────────────────────────────────────────────────────────────────────
// Check 1 — invalidation-condition traffic light
// ─────────────────────────────────────────────────────────────────────────
//
// Distance-based proxy for "how close is price to forcing the invalidation
// question", scored against the plan's own stop/targets — NOT an NLP parse of
// the free-text `invalidations` list (no such thing exists here); that list
// is surfaced alongside the number for a human to read.
//
// Honesty note found while building this: as of the synthetic-demo data this
// sandbox currently ships, EVERY position in the sample book ends up
// `available: false` here, for two different genuine reasons —
//   • NVDA and MSFT ARE inside Intra/Exitus's real covered universe (see
//     public/data/intra-exitus/latest.json), but the real engine's own
//     mean-reversion test found nothing significant for either name right now
//     and abstained (confidence: "insufficient", bias: "none") — so there is
//     no real stop/target to check distance against. That is the engine
//     correctly declining to guess, and this check correctly declining to
//     pretend otherwise.
//   • COST and AMD are outside that ~5-name universe entirely, so
//     `intraExitus.plan()` falls back to its seeded demo band — whose price
//     levels (see impl/intra-exitus.ts's demoPlan) are NOT anchored to the
//     position's real price at all, so a distance-to-stop % computed against
//     them would be meaningless, not just approximate.
// This isn't hand-picked to make a point — it is what today's synthetic data
// actually produces. Wire in a real, price-anchored plan for any of these
// four names (or add one to the real Intra/Exitus universe) and this check
// starts reading for real with no code change.
function invalidationTrafficLight(position: Position, plan: EntryExitPlan): CheckResult {
  const id = "invalidation-traffic-light";
  const label = "Invalidation-condition traffic light";

  if (isAbstainedPlan(plan)) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: `Intra/Exitus abstained on ${position.symbol} (confidence: insufficient, bias: none) — no real stop/target levels were published to check price against, and no invalidation conditions came with the abstained read.`,
      detail: "No usable plan to check against — see reason.",
    };
  }
  if (isSampleGenerated(plan.generatedBy)) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: `${position.symbol} is outside Intra/Exitus's real covered universe, so the plan shown is the seeded demo fallback. Its stop/target levels are derived from a hash of the ticker string, not this position's real price — comparing ${position.symbol}'s real $${position.lastPriceUsd.toFixed(2)} to a synthetic level would produce a number, not a read. Skipped rather than faked.`,
      detail: "No price-anchored plan to check against — see reason.",
    };
  }

  const side = plan.bias;
  const price = position.lastPriceUsd;
  const stopDist = side === "long" ? price - plan.stop : plan.stop - price;
  const entryToStop = side === "long" ? plan.entryZone[1] - plan.stop : plan.stop - plan.entryZone[0];
  const cushion = entryToStop > 0 ? Math.max(0, stopDist) / entryToStop : 0;

  let severity: CheckSeverity;
  let reasonNote: string;
  if (stopDist <= 0) {
    severity = "alert";
    reasonNote = `Price has traded through the stop (${plan.stop}).`;
  } else if (cushion <= 0.2) {
    severity = "alert";
    reasonNote = `Only ${(cushion * 100).toFixed(0)}% of the entry-to-stop cushion remains.`;
  } else if (cushion <= 0.5) {
    severity = "warn";
    reasonNote = `${(cushion * 100).toFixed(0)}% of the entry-to-stop cushion remains — thesis under pressure.`;
  } else {
    severity = "ok";
    reasonNote = "Price has ample room before the stop.";
  }

  const invalidationsText = plan.invalidations.length
    ? plan.invalidations.join(" ")
    : "(Intra/Exitus published no free-text invalidation conditions with this plan.)";

  return {
    id,
    label,
    severity,
    available: true,
    detail: `${reasonNote} Stated invalidation conditions: ${invalidationsText}`,
    data: { currentPriceUsd: price, stop: plan.stop, targets: plan.targets, cushionRemainingFraction: cushion, bias: side },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// Check 2 — time-in-trade vs. the plan's registered horizon
// ─────────────────────────────────────────────────────────────────────────
//
// There is no numeric "expected holding period" field anywhere in this
// codebase's real data — EntryExitPlan.timeStop is free text ("exit if the
// thesis hasn't played by…"), not a day count. What DOES exist, already
// landed, is horizons.ts's HORIZON_REGISTRY: every registered model declares
// a HorizonBand. All plans today come from the single registered LevelsModel
// (`intra-exitus`), so this looks that model's band up and treats the band's
// upper bound as the horizon threshold. (If a second LevelsModel is ever
// registered, this should key off which model actually produced `plan`
// rather than hardcoding "intra-exitus" — there's only one today.)
const HORIZON_BAND_UPPER_DAYS: Record<string, number> = {
  "1min-4h": 1,
  "1-10d": 10,
  "1w": 7,
  "1-3m": 90,
  "1-3y": 1095,
};

function timeInTradeVsHorizon(position: Position, nowIso: string): CheckResult {
  const id = "time-in-trade-vs-horizon";
  const label = "Time in trade vs. plan horizon";
  const horizonEntry = getHorizon("intra-exitus");

  if (!horizonEntry || horizonEntry.band === "unspecified" || !(horizonEntry.band in HORIZON_BAND_UPPER_DAYS)) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: "No numeric horizon is registered for the model that produced this plan (see src/lib/models/horizons.ts's HORIZON_REGISTRY).",
      detail: "Cannot compute — see reason.",
    };
  }

  const daysInTrade = daysBetween(position.openedAt, nowIso);
  const horizonDays = HORIZON_BAND_UPPER_DAYS[horizonEntry.band];
  const daysPast = daysInTrade - horizonDays;
  const pastHorizon = daysPast > 0;
  const ratio = horizonDays > 0 ? daysPast / horizonDays : 0;

  const severity: CheckSeverity = !pastHorizon ? "ok" : ratio >= 1 ? "alert" : "warn";

  return {
    id,
    label,
    severity,
    available: true,
    detail: pastHorizon
      ? `${daysInTrade} days in trade vs. a ${horizonEntry.band} (~${horizonDays}d) registered horizon for Intra/Exitus (${horizonEntry.note}) — ${daysPast} days past. This fires purely on elapsed time, independent of price: a thesis that hasn't played out in its stated window is itself information, per WATCH-01.`
      : `${daysInTrade} days in trade, within the ${horizonEntry.band} (~${horizonDays}d) registered horizon.`,
    data: { daysInTrade, horizonDays, horizonBand: horizonEntry.band, daysPast: Math.max(0, daysPast), pastHorizon },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// Check 3 — change in the originating model's forecast since entry
// ─────────────────────────────────────────────────────────────────────────
//
// Data-contract note (there is no history store in this codebase — verdicts
// and plans are generated live, on demand, and never persisted; see
// src/app/api/models/stress/route.ts): this check needs TWO reads of the same
// model to compare — a "forecast at entry" snapshot and a "forecast now".
// "Forecast now" is the live `verdict`/`plan` this function is already given.
// "Forecast at entry" is NOT re-derived here; it must be supplied by the
// caller as `PositionEntryContext.entryScoreSnapshot` / `.forecastAtEntry`
// (src/lib/types.ts) — a hand-authored SAMPLE record standing in for a real
// decision-ledger entry. When no such snapshot exists for a symbol, this
// check is honestly `available: false`, not silently skipped.
//
// It compares StressVerdict fields only (rating, conviction), not the plan's
// dollar levels — Distresse's demo scoring has no dependency on real price at
// all, so it survives the same-anchor-mismatch problem `invalidationTrafficLight`
// documents above; comparing dollar levels from a demo-fallback plan would not.
const RATING_RANK: Record<StressVerdict["rating"], number> = { go: 2, conditional: 1, "no-go": 0 };

function forecastDriftSinceEntry(verdict: StressVerdict, entryContext: PositionEntryContext | undefined): CheckResult {
  const id = "forecast-drift-since-entry";
  const label = "Forecast drift since entry";

  if (!entryContext) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: "No entry-time forecast snapshot recorded for this symbol (see sample-data.ts's positionEntryContext) — there is nothing to diff the live verdict against.",
      detail: "Cannot compute — see reason.",
    };
  }

  const entry = entryContext.entryScoreSnapshot;
  const ratingSteps = RATING_RANK[entry.rating] - RATING_RANK[verdict.rating]; // positive = downgrade
  const convictionDelta = verdict.conviction - entry.conviction;

  const ratingSeverity: CheckSeverity = ratingSteps >= 2 ? "alert" : ratingSteps === 1 ? "warn" : "ok";
  const convictionSeverity: CheckSeverity =
    Math.abs(convictionDelta) >= 30 ? "alert" : Math.abs(convictionDelta) >= 15 ? "warn" : Math.abs(convictionDelta) >= 8 ? "info" : "ok";
  const severity = worseOf(ratingSeverity, convictionSeverity);

  const regimeChanged = entry.regime !== verdict.regime;

  return {
    id,
    label,
    severity,
    available: true,
    detail:
      `Entry read: ${entry.rating} at ${entry.conviction} conviction ("${entry.regime}"). ` +
      `Now: ${verdict.rating} at ${verdict.conviction} conviction ("${verdict.regime}"). ` +
      `${ratingSteps > 0 ? `Rating has stepped down ${ratingSteps} level(s). ` : ratingSteps < 0 ? "Rating has improved. " : ""}` +
      `Conviction has moved ${convictionDelta >= 0 ? "+" : ""}${convictionDelta} points.` +
      (regimeChanged ? " The regime read has also changed." : "") +
      " (Demo-model caveat: this repo's Distresse implementation is a deterministic, time-invariant seeded function of ticker+instrument — see impl/distresse.ts — so re-running it never drifts on its own; any drift shown here comes entirely from the hand-authored entry snapshot differing from that fixed demo output, not from a real model changing its mind. A real, non-deterministic model would make this check meaningful on its own.)",
    data: { entryRating: entry.rating, liveRating: verdict.rating, entryConviction: entry.conviction, liveConviction: verdict.conviction, convictionDelta, regimeChanged },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// Check 4 — WW-GRAPH residual pull-through
// ─────────────────────────────────────────────────────────────────────────
function graphResidualPullThrough(position: Position, graphExport: GraphExport | null | undefined): CheckResult {
  const id = "graph-residual-pull-through";
  const label = "WW-GRAPH residual";

  if (!graphExport) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: "WW-GRAPH has not exported anything yet (public/data/graph/latest.json missing) — the engine hasn't synced.",
      detail: "Cannot compute — see reason.",
    };
  }
  const residual = graphExport.residuals.find((r) => r.ticker.toUpperCase() === position.symbol.toUpperCase());
  if (!residual) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: `${position.symbol} is not in WW-GRAPH's current universe (today's export only covers ${graphExport.universe.length} synthetic-demo names — see graph-engine's README on current coverage).`,
      detail: "Cannot compute — see reason.",
    };
  }
  if (residual.confidence === "insufficient" || residual.residual_z == null) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: `WW-GRAPH found ${position.symbol} but reports confidence "insufficient" (too little residual history) — no usable residual_z.`,
      detail: "Cannot compute — see reason.",
    };
  }

  const z = residual.residual_z;
  const severity: CheckSeverity = Math.abs(z) >= 2 ? "alert" : Math.abs(z) >= 1 ? "warn" : "ok";
  const provenanceNote =
    graphExport.data_provenance === "synthetic-demo"
      ? " (synthetic-demo data — not a real market read; see graph-engine's own disclaimer.)"
      : "";

  return {
    id,
    label,
    severity,
    available: true,
    detail:
      `Residual z-score ${z.toFixed(2)} vs. graph-implied neighbourhood value. ` +
      (residual.half_life_significant
        ? `A statistically significant reversion half-life of ${residual.half_life_days?.toFixed(1)} days is reported.`
        : "No statistically significant reversion half-life (the Dickey-Fuller gate did not clear) — the residual is reported without one, on purpose.") +
      provenanceNote,
    data: { residual_z: z, half_life_days: residual.half_life_days, half_life_significant: residual.half_life_significant, data_provenance: graphExport.data_provenance },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// Check 5 — WW-WEEKLY quantile band pull-through
// ─────────────────────────────────────────────────────────────────────────
function findWeeklyForecast(weeklyExport: WeeklyExport, symbol: string): WeeklyForecast | undefined {
  return weeklyExport.forecasts.find((f) => f.ticker.toUpperCase() === symbol.toUpperCase());
}

function weeklyQuantileBandPullThrough(position: Position, weeklyExport: WeeklyExport | null | undefined, bias: "long" | "short" | null): CheckResult {
  const id = "weekly-quantile-band-pull-through";
  const label = "WW-WEEKLY quantile band";

  if (!weeklyExport) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: "WW-WEEKLY has not exported anything yet (public/data/weekly/latest.json missing) — the engine hasn't synced.",
      detail: "Cannot compute — see reason.",
    };
  }
  const f = findWeeklyForecast(weeklyExport, position.symbol);
  if (!f || f.decile == null || f.quantile_p10 == null || f.quantile_p50 == null || f.quantile_p90 == null) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: `${position.symbol} is not in WW-WEEKLY's current universe (${weeklyExport.universe.length} names covered today).`,
      detail: "Cannot compute — see reason.",
    };
  }

  // Rank agreement: a long held in the bottom rank tier (or a short held in
  // the top tier) is a genuine cross-check, not a fabricated one — decile is
  // the model's actual cross-sectional rank output. Read magnitude off the
  // quantiles, ranking off the decile — never confuse the two, per
  // weekly-export.ts's own header comment.
  const effectiveBias = bias ?? "long"; // a book only ever holds long or short; default long if the plan itself is unusable
  const conflicting = effectiveBias === "long" ? f.decile <= 3 : f.decile >= 8;
  const severity: CheckSeverity = conflicting ? "warn" : "ok";

  return {
    id,
    label,
    severity,
    available: true,
    detail:
      `WW-WEEKLY decile ${f.decile}/10 (10 = most bullish this week), quantile band p10 ${(f.quantile_p10 * 100).toFixed(1)}% / p50 ${(f.quantile_p50 * 100).toFixed(1)}% / p90 ${(f.quantile_p90 * 100).toFixed(1)}% predicted relative return. ` +
      (conflicting
        ? `This conflicts with the book's ${effectiveBias} position — WW-WEEKLY's cross-sectional rank leans the other way this week.`
        : `This is broadly consistent with the book's ${effectiveBias} position.`) +
      ` ${weeklyExport.disclaimer}`,
    data: { decile: f.decile, quantile_p10: f.quantile_p10, quantile_p50: f.quantile_p50, quantile_p90: f.quantile_p90, model_version: f.model_version, provisional: f.provisional },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// Check 6 — WW-STATE book-wide regime context (not per-symbol; same read is
// attached to every position, since it describes the whole market, not one
// name — src/lib/models/state-export.ts documents each element's own
// available/reason semantics, which are passed straight through here).
// ─────────────────────────────────────────────────────────────────────────
function marketRegimeContext(stateExport: StateExport | null | undefined): CheckResult {
  const id = "market-regime-context";
  const label = "Book-wide market regime (WW-STATE)";

  if (!stateExport) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: "WW-STATE has not exported anything yet (public/data/state/latest.json missing).",
      detail: "Cannot compute — see reason.",
    };
  }
  const vol = stateExport.state_vector.volatility;
  const corr = stateExport.state_vector.correlation;

  if (!vol.available && !corr.available) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: `Volatility (${vol.reason ?? "unavailable"}) and correlation (${corr.reason ?? "unavailable"}) elements are both unavailable in this WW-STATE read.`,
      detail: "Cannot compute — see reason.",
    };
  }

  const volZ = vol.available ? vol.value : null;
  const corrZ = corr.available ? corr.value : null;
  const volFlag = volZ != null && volZ > 1;
  const corrFlag = corrZ != null && corrZ > 1;
  const severity: CheckSeverity = volFlag || corrFlag ? "warn" : "ok";

  return {
    id,
    label,
    severity,
    available: true,
    detail:
      `${stateExport.plain_language.volatility} ${stateExport.plain_language.correlation}` +
      (stateExport.universe_note ? ` (${stateExport.universe_note})` : ""),
    data: { volatilityZ: volZ, correlationZ: corrZ },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// Check 7 — correlation / concentration proxy against the rest of the book
// ─────────────────────────────────────────────────────────────────────────
//
// SIMPLIFICATION, documented: a real correlation read needs a return
// covariance matrix from per-ticker price history, which does not exist
// anywhere in this codebase (sample-data.ts only carries portfolio-level
// snapshots, not per-position time series). This substitutes two things that
// ARE computable from real fields on `Position` —
//   1. single-name concentration: marketValueUsd as a % of the book's total.
//   2. a categorical sector-overlap flag, using a small hand-maintained
//      lookup (SECTOR_HINT below) limited to the symbols actually in the
//      sample book. This is a static tag, not a computed correlation
//      coefficient, and it is explicitly labelled as such below. A symbol
//      missing from the lookup is treated as "unknown sector" and excluded
//      from the overlap calculation — never guessed.
export const SECTOR_HINT: Record<string, string> = {
  NVDA: "Semiconductors / AI compute",
  AMD: "Semiconductors / AI compute",
  MSFT: "Software / mega-cap tech",
  COST: "Consumer staples / retail",
};

function concentrationCorrelationProxy(position: Position, book: Position[] | undefined): CheckResult {
  const id = "concentration-correlation-proxy";
  const label = "Concentration / correlation proxy";

  if (!book || book.length === 0) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: "No book context was supplied (pass `opts.book` to runChecks) — cannot assess concentration against the rest of the portfolio.",
      detail: "Cannot compute — see reason.",
    };
  }

  const total = book.reduce((s, p) => s + p.marketValueUsd, 0);
  if (total <= 0) {
    return {
      id,
      label,
      severity: "info",
      available: false,
      reason: "Book's total market value is zero or negative — cannot compute a concentration percentage.",
      detail: "Cannot compute — see reason.",
    };
  }
  const weightPct = (position.marketValueUsd / total) * 100;

  const sector = SECTOR_HINT[position.symbol.toUpperCase()];
  let sectorOverlapPct = 0;
  let overlapSymbols: string[] = [];
  if (sector) {
    const sameSector = book.filter((p) => SECTOR_HINT[p.symbol.toUpperCase()] === sector);
    sectorOverlapPct = (sameSector.reduce((s, p) => s + p.marketValueUsd, 0) / total) * 100;
    overlapSymbols = sameSector.map((p) => p.symbol);
  }

  const singleNameSeverity: CheckSeverity = weightPct >= 45 ? "alert" : weightPct >= 30 ? "warn" : "ok";
  const overlapSeverity: CheckSeverity = sectorOverlapPct >= 55 ? "alert" : sectorOverlapPct >= 40 ? "warn" : "ok";
  const severity = worseOf(singleNameSeverity, overlapSeverity);

  return {
    id,
    label,
    severity,
    available: true,
    detail:
      `${position.symbol} is ${weightPct.toFixed(1)}% of the book by market value. ` +
      (sector
        ? `Sector tag (hand-maintained, not computed): "${sector}" — combined with ${overlapSymbols.filter((s) => s !== position.symbol).join(", ") || "no other position"} that's ${sectorOverlapPct.toFixed(1)}% of the book in the same tag. This is a categorical overlap proxy, NOT a computed correlation coefficient — no per-ticker return history exists in this codebase to compute one.`
        : "No sector tag on file for this symbol — sector-overlap check skipped rather than guessed."),
    data: { weightPct, sector: sector ?? null, sectorOverlapPct: sector ? sectorOverlapPct : null, overlapSymbols: sector ? overlapSymbols : [] },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// Checks 8-10 — explicitly out of reach with data this codebase actually has
// ─────────────────────────────────────────────────────────────────────────
function unavailableChecks(): CheckResult[] {
  return [
    {
      id: "options-implied-expected-move",
      label: "Options-implied expected move",
      severity: "info",
      available: false,
      reason:
        "No options-chain / implied-vol feed exists anywhere in this codebase. WW-STATE's own volatility element documents the same gap — state_vector.volatility.raw.implied_vol and implied_vol_term_structure are both null pending a live options-market-data vendor.",
      detail: "Not available.",
    },
    {
      id: "news-event-vector",
      label: "Real news / event vector",
      severity: "info",
      available: false,
      reason:
        "No real news or event/catalyst ingestion exists. The Nova module (src/app/nova/page.tsx) is an intentionally empty placeholder shell — 'build the news/catalyst model' is its own header comment.",
      detail: "Not available.",
    },
    {
      id: "positioning-fast-block",
      label: "Real positioning / flow fast-block",
      severity: "info",
      available: false,
      reason: "No real positioning/flow data source (13F filings, short interest, options skew, dealer gamma) is wired into any part of this codebase.",
      detail: "Not available.",
    },
  ];
}

// ─────────────────────────────────────────────────────────────────────────
// The entry point
// ─────────────────────────────────────────────────────────────────────────
export function runChecks(
  position: Position,
  plan: EntryExitPlan,
  verdict: StressVerdict,
  graphExport?: GraphExport | null,
  weeklyExport?: WeeklyExport | null,
  stateExport?: StateExport | null,
  opts: RunChecksOptions = {},
): PositionCheck {
  const nowIso = opts.nowIso ?? new Date().toISOString();
  const bias = isUsablePricedPlan(plan) ? plan.bias : null;

  const checks: CheckResult[] = [
    invalidationTrafficLight(position, plan),
    timeInTradeVsHorizon(position, nowIso),
    forecastDriftSinceEntry(verdict, opts.entryContext),
    graphResidualPullThrough(position, graphExport),
    weeklyQuantileBandPullThrough(position, weeklyExport, bias),
    marketRegimeContext(stateExport),
    concentrationCorrelationProxy(position, opts.book),
    ...unavailableChecks(),
  ];

  const weeklyForecast = weeklyExport ? findWeeklyForecast(weeklyExport, position.symbol) : undefined;
  const weeklyQuantile =
    weeklyForecast && weeklyForecast.quantile_p10 != null && weeklyForecast.quantile_p50 != null && weeklyForecast.quantile_p90 != null
      ? { p10: weeklyForecast.quantile_p10, p50: weeklyForecast.quantile_p50, p90: weeklyForecast.quantile_p90 }
      : null;

  const context: PositionCheckContext = {
    currentPriceUsd: position.lastPriceUsd,
    bias,
    weeklyQuantile,
    dimensionDispersion: verdict.dimensions.length ? stdev(verdict.dimensions.map((d) => d.score)) : null,
    stateVolatilityZ: stateExport?.state_vector.volatility.available ? stateExport.state_vector.volatility.value : null,
  };

  return { symbol: position.symbol, asOf: nowIso, checks, context };
}

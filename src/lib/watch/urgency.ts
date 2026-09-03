import type { PositionCheck, CheckSeverity } from "./checks";

// ═══════════════════════════════════════════════════════════════════════════
// WATCH-02 — urgency banding.
//
// `computeUrgency(checks)` turns a PositionCheck (checks.ts) into a band —
// how soon a human needs to look at this — plus an expected price RANGE, and
// a note on what actually drove that range's width. Per the design doc: "A
// single expected price a week out is not something we can produce honestly"
// — there is no single-number forecast anywhere in this file, on purpose.
//
// The doc also wants the width driver to distinguish "wide because the model
// is uncertain" from "wide because a scheduled event lands this week". Only
// the first is implemented here, honestly: there is no real event/earnings
// calendar anywhere in this codebase (see checks.ts's `news-event-vector`
// entry, and Nova's placeholder page) to drive the second. Rather than fake a
// calendar, `driverAvailable.eventCalendar` is hard-coded `false` with a
// reason, and the range is always widened on model-uncertainty grounds alone.
// ═══════════════════════════════════════════════════════════════════════════

export type UrgencyBand = "watch" | "act-this-week" | "act-today";

export interface UrgencyDriverAvailability {
  modelUncertainty: boolean; // was there a real (or real-proxy) uncertainty signal to widen the band with?
  eventCalendar: false; // always false — see header comment. Never flip this without wiring in a real calendar.
  eventCalendarReason: string;
}

export interface UrgencyResult {
  band: UrgencyBand;
  expectedRangeLow: number; // a price level, never a bare percentage
  expectedRangeHigh: number;
  drivenBy: string; // names the input that actually set the range's width, per the doc's exact ask
  driverAvailable: UrgencyDriverAvailability;
}

const SEVERITY_RANK: Record<CheckSeverity, number> = { ok: 0, info: 1, warn: 2, alert: 3 };

// Heuristic scale factor, documented as exactly that: it exists only to put
// the "dimension dispersion" fallback proxy (checks.ts's context.dimensionDispersion,
// a -100..100-scale stdev of Distresse's dimension scores) into roughly the
// same order of magnitude as WW-WEEKLY's real p10/p90 return quantiles for
// names it does cover, so the two paths produce comparable-looking ranges in
// the demo. It is NOT derived from any calibration study — do not treat it as
// one.
const DISPERSION_TO_RETURN_FRACTION_SCALE = 0.15;

// Fixed, clearly-labelled fallback when neither a real WW-WEEKLY band nor a
// verdict to compute dispersion from is available at all. Conservative on
// purpose (wide enough to admit "we don't actually know"), and always
// disclosed as a default in `drivenBy`, never presented as computed.
const DEFAULT_UNCERTAIN_FRACTION = 0.06;

export function computeUrgency(checks: PositionCheck): UrgencyResult {
  const available = checks.checks.filter((c) => c.available);
  const worst = available.reduce<CheckSeverity>(
    (acc, c) => (SEVERITY_RANK[c.severity] > SEVERITY_RANK[acc] ? c.severity : acc),
    "ok",
  );
  const band: UrgencyBand = worst === "alert" ? "act-today" : worst === "warn" ? "act-this-week" : "watch";

  const { currentPriceUsd, weeklyQuantile, dimensionDispersion } = checks.context;

  let fractionLow: number;
  let fractionHigh: number;
  let drivenBy: string;
  let modelUncertaintyAvailable: boolean;

  if (weeklyQuantile) {
    fractionLow = weeklyQuantile.p10;
    fractionHigh = weeklyQuantile.p90;
    drivenBy = `Range width is WW-WEEKLY's own real p10-p90 predicted-return quantiles for ${checks.symbol} this week — wide or narrow because the model's own quantile spread is, not a fixed assumption. (Research-grade rank signal — see weekly-export.ts's disclaimer; not a price target.)`;
    modelUncertaintyAvailable = true;
  } else if (dimensionDispersion != null) {
    const fraction = (dimensionDispersion / 100) * DISPERSION_TO_RETURN_FRACTION_SCALE;
    fractionLow = -fraction;
    fractionHigh = fraction;
    drivenBy = `${checks.symbol} isn't covered by WW-WEEKLY, so there's no real predicted-return band to use. Falling back to how much Distresse's own dimension scores disagree with each other (a stdev of ${dimensionDispersion.toFixed(1)} on a -100..100 scale) as a rough model-uncertainty proxy — wide because the model itself is internally split, narrow because it's coherent. This is a documented heuristic (scale factor ${DISPERSION_TO_RETURN_FRACTION_SCALE}), not a probability-calibrated forecast.`;
    modelUncertaintyAvailable = true;
  } else {
    fractionLow = -DEFAULT_UNCERTAIN_FRACTION;
    fractionHigh = DEFAULT_UNCERTAIN_FRACTION;
    drivenBy = `No model-uncertainty signal was available at all (no WW-WEEKLY coverage and no verdict to compute dimension dispersion from) — using a fixed, conservative ±${(DEFAULT_UNCERTAIN_FRACTION * 100).toFixed(0)}% default band. This is explicitly a placeholder width, not a computed one.`;
    modelUncertaintyAvailable = false;
  }

  return {
    band,
    expectedRangeLow: Math.min(
      currentPriceUsd * (1 + fractionLow),
      currentPriceUsd * (1 + fractionHigh),
    ),
    expectedRangeHigh: Math.max(
      currentPriceUsd * (1 + fractionLow),
      currentPriceUsd * (1 + fractionHigh),
    ),
    drivenBy,
    driverAvailable: {
      modelUncertainty: modelUncertaintyAvailable,
      eventCalendar: false,
      eventCalendarReason:
        "No real earnings/event calendar exists in this codebase (see checks.ts's news-event-vector entry) — event-driven band widening is not implemented; only the model-uncertainty path above is.",
    },
  };
}

// ─────────────────────────────────────────────────────────────────────────
// "Score the scorer" — the doc's own phrase: log the predicted range against
// the realised move every week, so the monitor's own honesty is auditable
// over time. This is a plain typed array — it needs a real persistence
// backend (a DB table) before it survives a server restart or is visible
// across instances; that swap is the same seam pattern used everywhere else
// in this codebase (src/lib/graph.ts, weekly.ts, state.ts all read a JSON
// file today and are documented to become a DB read later with no call-site
// change). Nothing here should be mistaken for that real store.
// ─────────────────────────────────────────────────────────────────────────

export interface ScoreHistoryEntry {
  symbol: string;
  asOf: string; // when the prediction was logged
  band: UrgencyBand;
  expectedRangeLow: number;
  expectedRangeHigh: number;
  drivenBy: string;
  realisedPriceUsd: number | null; // filled in later, once the week has played out
  realisedAt: string | null;
  realisedMovePct: number | null; // computed once realisedPriceUsd is filled in
  withinPredictedRange: boolean | null; // did the realised price actually land inside the logged range?
}

// Module-level in-memory array — resets on every server restart / cold start.
// A real implementation is a DB table keyed by (symbol, asOf).
const scoreHistoryLog: ScoreHistoryEntry[] = [];

export function logUrgencyPrediction(symbol: string, urgency: UrgencyResult, asOf: string): ScoreHistoryEntry {
  const entry: ScoreHistoryEntry = {
    symbol,
    asOf,
    band: urgency.band,
    expectedRangeLow: urgency.expectedRangeLow,
    expectedRangeHigh: urgency.expectedRangeHigh,
    drivenBy: urgency.drivenBy,
    realisedPriceUsd: null,
    realisedAt: null,
    realisedMovePct: null,
    withinPredictedRange: null,
  };
  scoreHistoryLog.push(entry);
  return entry;
}

// Finds the most recent not-yet-realised prediction for `symbol` and fills in
// what actually happened. Returns null if there is nothing to reconcile.
export function recordRealisedOutcome(symbol: string, realisedPriceUsd: number, realisedAt: string): ScoreHistoryEntry | null {
  const candidates = scoreHistoryLog.filter((e) => e.symbol === symbol && e.realisedPriceUsd == null);
  if (candidates.length === 0) return null;
  const entry = candidates[candidates.length - 1];
  entry.realisedPriceUsd = realisedPriceUsd;
  entry.realisedAt = realisedAt;
  const basisPrice = (entry.expectedRangeLow + entry.expectedRangeHigh) / 2;
  entry.realisedMovePct = basisPrice !== 0 ? (realisedPriceUsd - basisPrice) / basisPrice : null;
  entry.withinPredictedRange = realisedPriceUsd >= entry.expectedRangeLow && realisedPriceUsd <= entry.expectedRangeHigh;
  return entry;
}

export function listScoreHistory(symbol?: string): ScoreHistoryEntry[] {
  const rows = symbol ? scoreHistoryLog.filter((e) => e.symbol === symbol) : scoreHistoryLog;
  return rows.slice(); // copy — never hand out the live array
}

// ---------------------------------------------------------------------------
// WATCH-01/02 — rules-based position monitor + urgency banding.
//
// Pure, typed, dependency-free logic. No live broker feed exists in this
// sandbox: every function here takes a `WatchPosition` the caller supplies
// (see src/lib/watch/sample-positions.ts for SAMPLE data) and returns a
// derived read. Nothing in this file talks to a network, a DB, or Slack.
//
// `InvalidationState` is the SHARED vocabulary WATCH-01 and IMP-04 (and, per
// the doc, the alert system in watch/notifier.ts) all use for the same
// traffic-light concept — defined once here so nobody re-invents a second
// enum with slightly different bucket names.
// ---------------------------------------------------------------------------

export type InvalidationState = "green" | "amber" | "red";

export type Side = "long" | "short";

// A position as the monitor needs to see it. Deliberately narrower than the
// dashboard's `Position` type (src/lib/types.ts) — this carries the trade's
// thesis/plan detail (stop, targets, horizon) that a raw broker position
// record does not have, and that only exists here because it's SAMPLE data
// authored alongside the position.
export type WatchPosition = {
  symbol: string;
  side: Side;
  entryPriceUsd: number;
  currentPriceUsd: number;
  stopUsd: number;
  targetsUsd: number[]; // scale-out levels, in the direction of the trade
  thesis: string;
  invalidation: string; // plain-language "what kills this setup"
  horizonDays: number; // stated holding horizon, in days
  daysInTrade: number; // how long the position has actually been open
};

export type PositionRead = {
  symbol: string;
  invalidationState: InvalidationState;
  invalidationReason: string;
  distanceToStopPct: number; // % move (signed, always >= 0 by construction) still available before the stop
  distanceToNearestTargetPct: number; // % move to the closest target ahead
  pastHorizon: boolean; // WATCH-01: "past its horizon" fires even with no price movement
  daysPastHorizon: number; // 0 if not past horizon
};

// Directional helper: how far price has moved in the position's favor, as a
// fraction of entry (positive = favorable). Long profits on price up, short
// profits on price down.
function favorableMoveFraction(p: WatchPosition): number {
  const raw = (p.currentPriceUsd - p.entryPriceUsd) / p.entryPriceUsd;
  return p.side === "long" ? raw : -raw;
}

// % distance from current price to the stop, expressed as a positive number
// shrinking toward zero as price approaches the stop. Guards against
// division by zero / a stop already blown through (clamped to 0).
export function distanceToStopPct(p: WatchPosition): number {
  const dist =
    p.side === "long"
      ? (p.currentPriceUsd - p.stopUsd) / p.currentPriceUsd
      : (p.stopUsd - p.currentPriceUsd) / p.currentPriceUsd;
  return Math.max(0, dist) * 100;
}

// % distance to the nearest UNMET target ahead of price, in the trade's
// direction. Returns 0 if every target has already been reached (a real
// system would prompt "take profit / raise stop" at that point — out of
// scope here).
export function distanceToNearestTargetPct(p: WatchPosition): number {
  const ahead = p.targetsUsd.filter((t) =>
    p.side === "long" ? t > p.currentPriceUsd : t < p.currentPriceUsd,
  );
  if (ahead.length === 0) return 0;
  const nearest = ahead.reduce((best, t) =>
    Math.abs(t - p.currentPriceUsd) < Math.abs(best - p.currentPriceUsd) ? t : best,
  );
  return (Math.abs(nearest - p.currentPriceUsd) / p.currentPriceUsd) * 100;
}

// The traffic light. Rule of thumb (documented, not hidden):
//   RED   — price has traded through the stop, OR is within 1/5 of the
//           original entry-to-stop distance from the stop (i.e. the move
//           against the thesis has eaten ~80%+ of the stop cushion).
//   AMBER — within 1/2 of the entry-to-stop distance from the stop, i.e.
//           the thesis is under real pressure but not yet broken.
//   GREEN — everything else: more than half the original stop cushion
//           remains.
// This is a distance-based proxy for "is the invalidation condition close
// to triggering" — it does NOT parse the free-text `invalidation` field
// (no NLP here), so a human still reads that text; this just says how much
// room is left before price forces the question.
export function invalidationState(p: WatchPosition): {
  state: InvalidationState;
  reason: string;
} {
  const entryToStop = Math.abs(p.entryPriceUsd - p.stopUsd);
  if (entryToStop === 0) {
    // Degenerate input (stop == entry) — treat as maximally strict.
    return { state: "red", reason: "Stop equals entry price — no cushion defined." };
  }
  const moveAgainst =
    p.side === "long" ? p.entryPriceUsd - p.currentPriceUsd : p.currentPriceUsd - p.entryPriceUsd;
  const fractionOfCushionUsed = moveAgainst / entryToStop; // can exceed 1 if stop already breached

  if (fractionOfCushionUsed >= 1) {
    return {
      state: "red",
      reason: `Price has traded through the stop (${p.stopUsd}) — invalidation condition met.`,
    };
  }
  if (fractionOfCushionUsed >= 0.8) {
    return {
      state: "red",
      reason: `Within ${(1 - fractionOfCushionUsed) * 100 < 0 ? 0 : ((1 - fractionOfCushionUsed) * 100).toFixed(0)}% of the stop cushion left — thesis close to invalidated.`,
    };
  }
  if (fractionOfCushionUsed >= 0.5) {
    return {
      state: "amber",
      reason: `${(fractionOfCushionUsed * 100).toFixed(0)}% of the stop cushion has been used — thesis under pressure.`,
    };
  }
  return {
    state: "green",
    reason: "Price has room before the stop; no invalidation pressure detected.",
  };
}

// WATCH-01's "past its horizon" alert: fires purely on elapsed time,
// independent of price action, because a thesis that hasn't played out in
// the time it was supposed to is itself information.
export function pastHorizon(p: WatchPosition): { pastHorizon: boolean; daysPast: number } {
  const daysPast = p.daysInTrade - p.horizonDays;
  return { pastHorizon: daysPast > 0, daysPast: Math.max(0, daysPast) };
}

// Convenience: compute the full read for one position in one call — this is
// what the position detail page and the notifier both want.
export function readPosition(p: WatchPosition): PositionRead {
  const inv = invalidationState(p);
  const horizon = pastHorizon(p);
  return {
    symbol: p.symbol,
    invalidationState: inv.state,
    invalidationReason: inv.reason,
    distanceToStopPct: distanceToStopPct(p),
    distanceToNearestTargetPct: distanceToNearestTargetPct(p),
    pastHorizon: horizon.pastHorizon,
    daysPastHorizon: horizon.daysPast,
  };
}

// Exposed for callers (e.g. urgency.ts) that want the raw favorable-move
// fraction without recomputing it.
export { favorableMoveFraction };

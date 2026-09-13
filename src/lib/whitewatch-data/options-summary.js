// ═══════════════════════════════════════════════════════════════════════════
// Pure math over an already-fetched Tradier options chain — no network I/O in
// this file on purpose, so the formulas below can be hand-verified against
// constructed example payloads without a live API call (see the task's
// constraint that this environment cannot reach sandbox.tradier.com).
// See scripts/verify-options.mjs for the actual worked-example verification
// (same "no jest/vitest, so a plain-node script asserts on constructed
// payloads" convention as scripts/verify-conviction.mjs) — run it with
// `node scripts/verify-options.mjs`.
//
// ── ATM selection: NEAREST-STRIKE, not interpolated ─────────────────────────
// Documented choice (per this task's instruction to state which): this picks
// the single listed strike closest to spot and reads its IV directly, rather
// than interpolating a synthetic "IV at exactly spot" between two straddling
// strikes. Nearest-strike is simpler, never invents a value between two real
// quotes, and standard strike spacing (most liquid names: $1-$5 near the
// money) keeps the nearest strike close enough to spot that the difference
// from a true interpolation is immaterial for a "how much movement does the
// market expect" read — this is descriptive market context, not a priced
// hedge, so sub-strike precision isn't the point.
//
// ── ATM IV: averaged across the call and put at that strike ────────────────
// When both legs have a usable mid_iv, this averages them. Reasoning: at a
// genuinely at-the-money strike, put-call parity implies the call and put
// should imply very similar volatility; averaging cancels a little bid/ask
// noise on either leg. When only one leg has a usable mid_iv (thin quotes are
// common away from the very largest names), this falls back to that one leg
// rather than abstaining — a single real quote beats no read. Only abstains
// (returns null) when NEITHER leg has a usable mid_iv.
//
// ── Expected move formula ────────────────────────────────────────────────
//   expectedMovePct = atmIv * sqrt(daysToExpiration / 365)
// This is the standard "implied 1-standard-deviation move" formula: it
// rescales an ANNUALIZED implied volatility (that's what mid_iv already is)
// down to the fraction of a year actually remaining, using the square-root-
// of-time scaling of a lognormal price model (annualized volatility of a
// return over T years scales with sqrt(T)). Verified against a worked
// example found during this task's research (IV=30%, 30 DTE, spot $500 ->
// $500 * 0.30 * sqrt(30/365) = $500 * 0.30 * 0.2867 = $43.01, i.e. an
// implied +/-8.6% move) and reproduced exactly by scripts/verify-options.mjs
// Example 1 below (spot $190, IV 30%, 30 DTE -> ±8.60%, i.e. ±$16.34).
// IMPORTANT CAVEAT (documented here AND surfaced in the UI, not just here):
// this is a ONE-STANDARD-DEVIATION range under a lognormal assumption with
// no skew adjustment — it means "the options market is pricing roughly a
// 68% chance the move stays inside this band by expiration," not a hard cap,
// and it ignores volatility skew (this simple formula treats IV as a single
// number, even though real chains price OTM puts/calls at different IVs).
// ═══════════════════════════════════════════════════════════════════════════

const MS_PER_DAY = 24 * 60 * 60 * 1000;

function daysBetween(fromISO, toISO) {
  const from = new Date(fromISO.slice(0, 10) + "T00:00:00Z").getTime();
  const to = new Date(toISO.slice(0, 10) + "T00:00:00Z").getTime();
  return Math.round((to - from) / MS_PER_DAY);
}

// Finds the strike closest to spot among strikes that have at least one
// contract (call or put). Ties broken toward the lower strike — an arbitrary
// but documented and stable choice; it never affects which contracts exist,
// only which of two equidistant strikes is reported as "the" ATM strike.
function findAtmStrike(contracts, spot) {
  let best = null;
  let bestDist = Infinity;
  for (const c of contracts) {
    const dist = Math.abs(c.strike - spot);
    if (dist < bestDist || (dist === bestDist && best !== null && c.strike < best)) {
      best = c.strike;
      bestDist = dist;
    }
  }
  return best;
}

function atmIvAtStrike(contracts, strike) {
  const call = contracts.find((c) => c.strike === strike && c.optionType === "call");
  const put = contracts.find((c) => c.strike === strike && c.optionType === "put");
  const callIv = call?.greeks?.mid_iv ?? null;
  const putIv = put?.greeks?.mid_iv ?? null;
  if (callIv != null && putIv != null) return (callIv + putIv) / 2;
  if (callIv != null) return callIv;
  if (putIv != null) return putIv;
  return null;
}

function putCallOiRatio(contracts) {
  let callOi = 0;
  let putOi = 0;
  let haveAny = false;
  for (const c of contracts) {
    if (c.openInterest == null) continue;
    haveAny = true;
    if (c.optionType === "call") callOi += c.openInterest;
    else putOi += c.openInterest;
  }
  if (!haveAny || callOi === 0) {
    return { ratio: null, callOi, putOi };
  }
  return { ratio: putOi / callOi, callOi, putOi };
}

// Builds the full member-facing summary from a "ok"-status snapshot (see
// tradier-sandbox.js's getOptionsSnapshot). Never called on a
// not_applicable/no_data/error snapshot — the route handles those statuses
// directly without reaching this function, so this function can assume
// `contracts.length > 0` and a valid `spot`.
export function summarizeChain({ symbol, asOf, expiration, expirationBasis, spot, contracts }) {
  const atmStrike = findAtmStrike(contracts, spot);
  const atmIv = atmStrike == null ? null : atmIvAtStrike(contracts, atmStrike);
  const dte = daysBetween(asOf, expiration);
  const { ratio: putCallOi, callOi, putOi } = putCallOiRatio(contracts);

  if (atmIv == null) {
    // Real chain, real strikes, but no usable IV at the ATM strike (ORATS
    // hadn't computed one, or both legs are missing bid/ask entirely) —
    // abstain on the IV-derived numbers specifically, honestly, rather than
    // showing a fabricated 0% expected move. Still report what IS real
    // (strike count, OI ratio) since that came from actual chain data.
    return {
      status: "no_data",
      symbol,
      asOf,
      expiration,
      expirationBasis,
      spot,
      atmStrike,
      contractsCount: contracts.length,
      putCallOi,
      callOi,
      putOi,
      reason: "Chain returned but no ATM implied volatility was available from ORATS for this expiration.",
    };
  }

  const expectedMovePct = atmIv * Math.sqrt(Math.max(dte, 0) / 365);
  const expectedMoveDollars = spot * expectedMovePct;

  return {
    status: "ok",
    symbol,
    asOf,
    expiration,
    expirationBasis,
    daysToExpiration: dte,
    spot,
    atmStrike,
    atmIv,
    expectedMovePct,
    expectedMoveDollars,
    expectedMoveLow: spot - expectedMoveDollars,
    expectedMoveHigh: spot + expectedMoveDollars,
    putCallOi,
    callOi,
    putOi,
    contractsCount: contracts.length,
  };
}

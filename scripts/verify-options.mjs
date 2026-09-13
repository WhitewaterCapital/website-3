#!/usr/bin/env node
// Plain-node verification for src/lib/whitewatch-data/options-summary.js —
// same situation as scripts/verify-conviction.mjs: no jest/vitest in this
// repo, no network access in this sandbox to reach Tradier itself, so this
// hand-traces the expected-move / ATM-IV / put-call-OI math against
// CONSTRUCTED example payloads shaped exactly like the real, independently-
// verified Tradier sandbox schema (see tradier-sandbox.js's header comment
// for the citations) — not live data, but real arithmetic over a real
// schema, checkable by anyone reading this file.
//
// options-summary.js has no imports beyond plain JS (no "server-only", no
// Next.js APIs), so this runs with plain `node` — no TS-stripping flags
// needed, unlike verify-conviction.mjs.
//
// Run with:
//   node scripts/verify-options.mjs

import { summarizeChain } from "../src/lib/whitewatch-data/options-summary.js";

let passed = 0;
let failed = 0;

function ok(label, condition) {
  if (condition) {
    passed++;
    console.log(`  PASS: ${label}`);
  } else {
    failed++;
    console.log(`  FAIL: ${label}`);
  }
}

function approx(a, b, eps = 1e-6) {
  return Math.abs(a - b) < eps;
}

function contract(strike, optionType, { midIv = null, oi = null } = {}) {
  return {
    strike,
    optionType,
    bid: null,
    ask: null,
    openInterest: oi,
    volume: null,
    greeks: midIv == null ? null : { mid_iv: midIv, delta: null, gamma: null, theta: null, vega: null, bid_iv: null, ask_iv: null },
  };
}

console.log("=== Example 1: clean chain, spot exactly at a listed strike ===");
{
  // Spot = 190.00, expiration 30 calendar days out. Strikes 185/190/195, each
  // with a call and a put. ATM strike must be 190 (exact match).
  const contracts = [
    contract(185, "call", { midIv: 0.28, oi: 500 }),
    contract(185, "put", { midIv: 0.3, oi: 600 }),
    contract(190, "call", { midIv: 0.29, oi: 1200 }),
    contract(190, "put", { midIv: 0.31, oi: 1400 }),
    contract(195, "call", { midIv: 0.27, oi: 300 }),
    contract(195, "put", { midIv: 0.29, oi: 250 }),
  ];
  const snapshot = {
    symbol: "TEST1",
    asOf: "2026-09-13T00:00:00.000Z",
    expiration: "2026-10-13",
    expirationBasis: "standard-monthly",
    spot: 190.0,
    contracts,
  };
  const s = summarizeChain(snapshot);

  // Hand-traced expectations:
  //   atmStrike = 190 (exact spot match)
  //   atmIv = (0.29 + 0.31) / 2 = 0.30
  //   dte = 30 (2026-09-13 -> 2026-10-13)
  //   expectedMovePct = 0.30 * sqrt(30/365) = 0.30 * 0.286718... = 0.0860155...
  //   expectedMoveDollars = 190 * 0.0860155 = 16.3429...
  //   totalCallOi = 500+1200+300 = 2000; totalPutOi = 600+1400+250 = 2250
  //   putCallOi = 2250/2000 = 1.125
  const expectedDte = 30;
  const expectedAtmIv = 0.3;
  const expectedMovePct = 0.3 * Math.sqrt(30 / 365);

  ok("status is ok", s.status === "ok");
  ok(`atmStrike is 190 (got ${s.atmStrike})`, s.atmStrike === 190);
  ok(`atmIv is 0.30 (got ${s.atmIv})`, approx(s.atmIv, expectedAtmIv));
  ok(`daysToExpiration is 30 (got ${s.daysToExpiration})`, s.daysToExpiration === expectedDte);
  ok(
    `expectedMovePct matches atmIv*sqrt(dte/365) (got ${s.expectedMovePct}, expected ${expectedMovePct})`,
    approx(s.expectedMovePct, expectedMovePct)
  );
  ok(
    `expectedMoveDollars = spot * expectedMovePct (got ${s.expectedMoveDollars}, expected ${190 * expectedMovePct})`,
    approx(s.expectedMoveDollars, 190 * expectedMovePct)
  );
  ok(`expectedMoveLow/High bracket spot symmetrically`, approx(s.spot - s.expectedMoveDollars, s.expectedMoveLow) && approx(s.spot + s.expectedMoveDollars, s.expectedMoveHigh));
  ok(`callOi totals 2000 (got ${s.callOi})`, s.callOi === 2000);
  ok(`putOi totals 2250 (got ${s.putOi})`, s.putOi === 2250);
  ok(`putCallOi is 2250/2000 = 1.125 (got ${s.putCallOi})`, approx(s.putCallOi, 1.125));
  console.log(
    `    Reference numbers for the report: atmIv=${(s.atmIv * 100).toFixed(1)}%, expectedMove=±${(s.expectedMovePct * 100).toFixed(2)}% (±$${s.expectedMoveDollars.toFixed(2)}), putCallOi=${s.putCallOi.toFixed(3)}`
  );
}

console.log("=== Example 2: spot between two strikes (tie-break + one-leg-only IV) ===");
{
  // Spot = 100.00, strikes 95/100/105 exist but ALSO a 97.5/102.5 pair to
  // exercise "nearest, not interpolated" — nearest strike to 100 is 100
  // itself here, so instead make spot land exactly between two real
  // strikes (97 and 103, both distance 3) to exercise the documented
  // lower-strike tie-break. Also: at strike 97, only the PUT has a usable
  // mid_iv (call's greeks are entirely missing — thin quote) to exercise
  // the one-leg-only fallback.
  const contracts = [
    contract(97, "call", {}), // no greeks at all
    contract(97, "put", { midIv: 0.42, oi: 80 }),
    contract(103, "call", { midIv: 0.33, oi: 150 }),
    contract(103, "put", { midIv: 0.35, oi: 90 }),
  ];
  const snapshot = {
    symbol: "TEST2",
    asOf: "2026-09-13T00:00:00.000Z",
    expiration: "2026-09-20", // 7 days out — exercises a short-dated case too
    expirationBasis: "nearest-available",
    spot: 100.0,
    contracts,
  };
  const s = summarizeChain(snapshot);

  ok(`tie-break picks the LOWER equidistant strike, 97 (got ${s.atmStrike})`, s.atmStrike === 97);
  ok(`ATM IV falls back to the single available leg (put, 0.42) when the call has no greeks (got ${s.atmIv})`, approx(s.atmIv, 0.42));
  const expectedMovePct = 0.42 * Math.sqrt(7 / 365);
  ok(
    `7-day expected move = 0.42 * sqrt(7/365) (got ${s.expectedMovePct}, expected ${expectedMovePct})`,
    approx(s.expectedMovePct, expectedMovePct)
  );
  console.log(
    `    Reference numbers for the report: atmStrike=${s.atmStrike}, atmIv=${(s.atmIv * 100).toFixed(1)}%, 7d expectedMove=±${(s.expectedMovePct * 100).toFixed(2)}%`
  );
}

console.log("=== Example 3: real strikes and OI, but NO usable IV anywhere (honest abstention) ===");
{
  // A thinly-quoted name: strikes and open interest are real, but ORATS
  // hadn't computed greeks for either leg at the ATM strike this pull.
  // Must abstain on atmIv/expectedMove* (status "no_data") WITHOUT
  // dropping the real OI numbers that ARE available.
  const contracts = [
    contract(50, "call", { oi: 20 }), // no greeks
    contract(50, "put", { oi: 35 }), // no greeks
    contract(45, "call", { oi: 10 }),
    contract(55, "put", { oi: 15 }),
  ];
  const snapshot = {
    symbol: "TEST3",
    asOf: "2026-09-13T00:00:00.000Z",
    expiration: "2026-11-20",
    expirationBasis: "standard-monthly",
    spot: 50.0,
    contracts,
  };
  const s = summarizeChain(snapshot);

  ok('status is "no_data", not "ok", when ATM IV is unresolvable', s.status === "no_data");
  ok("atmIv is absent/undefined on the no_data result (never fabricated as 0 or null-as-a-number)", s.atmIv === undefined);
  ok("expectedMovePct is absent on the no_data result", s.expectedMovePct === undefined);
  ok(`real OI is still reported: callOi=30, putOi=50 (got ${s.callOi}, ${s.putOi})`, s.callOi === 30 && s.putOi === 50);
  ok(`putCallOi = 50/30 still computed (got ${s.putCallOi})`, approx(s.putCallOi, 50 / 30));
  ok("a human-readable reason is present", typeof s.reason === "string" && s.reason.length > 0);
  console.log(`    reason: "${s.reason}"`);
}

console.log("=== Example 4: zero call open interest (ratio must abstain, not divide by zero) ===");
{
  const contracts = [
    contract(10, "call", { midIv: 0.5, oi: 0 }),
    contract(10, "put", { midIv: 0.5, oi: 40 }),
  ];
  const snapshot = {
    symbol: "TEST4",
    asOf: "2026-09-13T00:00:00.000Z",
    expiration: "2026-10-13",
    expirationBasis: "nearest-available",
    spot: 10.0,
    contracts,
  };
  const s = summarizeChain(snapshot);
  ok("status is ok (IV was resolvable even though call OI is 0)", s.status === "ok");
  ok(`putCallOi is null, not Infinity/NaN, when call OI is 0 (got ${s.putCallOi})`, s.putCallOi === null);
}

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}

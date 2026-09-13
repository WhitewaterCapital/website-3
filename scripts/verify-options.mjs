#!/usr/bin/env node
// Plain-node verification for the options/implied-volatility integration —
// src/lib/whitewatch-data/{alphavantage-options,options-summary}.js. Same
// situation as scripts/verify-conviction.mjs: no jest/vitest in this repo,
// no network access in this sandbox to reach Alpha Vantage itself, so this
// hand-traces:
//   (a) the ATM-IV / expected-move / put-call-OI math in options-summary.js
//       (UNCHANGED math — this file previously verified it against a
//       Tradier-shaped chain; it's vendor-agnostic, see that file's header),
//       against CONSTRUCTED example payloads, and
//   (b) alphavantage-options.js's `classifyAlphaVantageResponse` — the
//       function this task specifically requires to distinguish three real
//       situations correctly: actual option-chain data, a plan-gated
//       rejection ("this endpoint is not on your plan"), and a rate-limited
//       rejection ("try again later") — against CONSTRUCTED payloads shaped
//       exactly like the response bodies documented/observed for Alpha
//       Vantage (see that file's header for the citations, and its honest
//       flagging of what was and wasn't directly confirmed).
//
// Run with:
//   node scripts/verify-options.mjs

import { summarizeChain } from "../src/lib/whitewatch-data/options-summary.js";
import { classifyAlphaVantageResponse, pickExpiration, parseGlobalQuoteLast } from "../src/lib/whitewatch-data/alphavantage-options.js";

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

console.log("=== Part 1: options-summary.js math (vendor-agnostic — unchanged by the Tradier -> Alpha Vantage switch) ===");

console.log("--- Example 1: clean chain, spot exactly at a listed strike ---");
{
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

console.log("--- Example 2: spot between two strikes (tie-break + one-leg-only IV) ---");
{
  const contracts = [
    contract(97, "call", {}),
    contract(97, "put", { midIv: 0.42, oi: 80 }),
    contract(103, "call", { midIv: 0.33, oi: 150 }),
    contract(103, "put", { midIv: 0.35, oi: 90 }),
  ];
  const snapshot = {
    symbol: "TEST2",
    asOf: "2026-09-13T00:00:00.000Z",
    expiration: "2026-09-20",
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
}

console.log("--- Example 3: real strikes and OI, but NO usable IV anywhere (honest abstention) ---");
{
  const contracts = [
    contract(50, "call", { oi: 20 }),
    contract(50, "put", { oi: 35 }),
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
}

console.log("--- Example 4: zero call open interest (ratio must abstain, not divide by zero) ---");
{
  const contracts = [contract(10, "call", { midIv: 0.5, oi: 0 }), contract(10, "put", { midIv: 0.5, oi: 40 })];
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
console.log("=== Part 2: alphavantage-options.js response classification (the plan_gated vs rate_limited distinction) ===");

console.log("--- Case A: real option-chain data (success) ---");
{
  // Shaped per alphavantage-options.js's header's cross-checked field list —
  // envelope itself is RECONSTRUCTED, not directly observed (see that
  // file's header), which is exactly why this test exists: to pin down, in
  // one runnable place, the exact shape this parser is built against.
  const payload = {
    endpoint: "Historical Options",
    message: "success",
    data: [
      {
        contractID: "AAPL260116C00190000",
        symbol: "AAPL",
        expiration: "2026-01-16",
        strike: "190.00",
        type: "call",
        bid: "5.10",
        ask: "5.30",
        volume: "120",
        open_interest: "980",
        date: "2026-09-12",
        implied_volatility: "0.31",
        delta: "0.54",
        gamma: "0.02",
        theta: "-0.04",
        vega: "0.18",
      },
    ],
  };
  const cls = classifyAlphaVantageResponse(payload);
  ok('classified as "data" for a real chain', cls.kind === "data");
  ok("data array has 1 row", Array.isArray(cls.data) && cls.data.length === 1);
}

console.log("--- Case B: PLAN-GATED rejection (endpoint not on this key's plan) ---");
{
  // Wording matches, as closely as this research could confirm, the exact
  // message quoted in the 2023 GitHub issue (portfolio-performance/
  // portfolio#3275) for a DIFFERENT endpoint (TIME_SERIES_DAILY) that
  // Alpha Vantage moved behind the same premium gate — see
  // alphavantage-options.js's header. This is the shape this task requires
  // to be distinguished from a rate-limit rejection, NOT collapsed into a
  // generic "error".
  const payload = {
    Information:
      "Thank you for using Alpha Vantage! This is a premium endpoint. You may subscribe to any of the premium plans at https://www.alphavantage.co/premium/ to instantly unlock all premium endpoints",
  };
  const cls = classifyAlphaVantageResponse(payload);
  ok('classified as "plan_gated", NOT "error" and NOT "rate_limited"', cls.kind === "plan_gated");
  ok("Alpha Vantage's own message text is preserved verbatim", cls.message === payload.Information);
}

console.log("--- Case C: RATE-LIMITED rejection (daily/frequency cap hit) — two known wordings ---");
{
  const dailyLimitPayload = {
    Information:
      "Thank you for using Alpha Vantage! Our standard API rate limit is 25 requests per day. Please subscribe to any of the premium plans at https://www.alphavantage.co/premium/ to instantly remove all daily rate limits.",
  };
  const perMinutePayload = {
    Note: "Thank you for using Alpha Vantage! Our standard API call frequency is 5 calls per minute and 25 calls per day.",
  };
  const clsDaily = classifyAlphaVantageResponse(dailyLimitPayload);
  const clsMinute = classifyAlphaVantageResponse(perMinutePayload);
  ok('daily-limit wording (in "Information") classified as "rate_limited"', clsDaily.kind === "rate_limited");
  ok('per-minute wording (in "Note") classified as "rate_limited"', clsMinute.kind === "rate_limited");
  ok(
    'rate_limited is NEVER confused with plan_gated (kind differs even though both use "Information")',
    clsDaily.kind !== "plan_gated"
  );
}

console.log("--- Case D: malformed request (Error Message field) ---");
{
  const payload = { "Error Message": "Invalid API call. Please retry or visit the documentation." };
  const cls = classifyAlphaVantageResponse(payload);
  ok('classified as "error"', cls.kind === "error");
  ok("message preserved", cls.message === payload["Error Message"]);
}

console.log("--- Case E: real 'success' response but zero contracts (inferred not_applicable) ---");
{
  const payload = { endpoint: "Historical Options", message: "success", data: [] };
  const cls = classifyAlphaVantageResponse(payload);
  ok('classified as "empty"', cls.kind === "empty");
}

console.log("--- Case F: unrecognized shape (never silently miscategorized) ---");
{
  const payload = { something: "unexpected" };
  const cls = classifyAlphaVantageResponse(payload);
  ok('falls through to "error" rather than guessing', cls.kind === "error");
}

console.log("--- Case G: GLOBAL_QUOTE spot-price parsing ---");
{
  const good = { "Global Quote": { "05. price": "233.45" } };
  const bad = { "Global Quote": {} };
  ok("parses a valid spot price", parseGlobalQuoteLast(good) === 233.45);
  ok("returns null (never 0 or NaN) for a missing price field", parseGlobalQuoteLast(bad) === null);
}

console.log("--- Case H: pickExpiration (standard-monthly vs nearest-available, unchanged logic) ---");
{
  const today = "2026-09-13";
  // 2026-09-18 and 2026-10-16 are both real 3rd Fridays (verified: day-of-
  // week Friday, day-of-month in 15-21) — 2026-09-25 is a Friday but NOT a
  // 3rd Friday (day-of-month 25, the 4th Friday), used below as a genuine
  // weekly mixed in alongside two monthlies.
  const withMonthly = pickExpiration(["2026-09-25", "2026-09-18", "2026-10-16"], today);
  ok(
    `picks 2026-09-18 as the NEAREST standard monthly (3rd Friday) (got ${withMonthly?.date}, basis ${withMonthly?.basis})`,
    withMonthly?.date === "2026-09-18" && withMonthly?.basis === "standard-monthly"
  );
  // 2026-09-25 (4th Friday) and 2026-10-02 (1st Friday) are both real
  // Fridays but NEITHER is a 3rd Friday, and both are >= today.
  const weekliesOnly = pickExpiration(["2026-09-25", "2026-10-02"], today);
  ok(
    `falls back to nearest-available when no monthly exists (got ${weekliesOnly?.date}, basis ${weekliesOnly?.basis})`,
    weekliesOnly?.date === "2026-09-25" && weekliesOnly?.basis === "nearest-available"
  );
  ok("returns null when every listed date is in the past", pickExpiration(["2026-01-01"], today) === null);
}

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}

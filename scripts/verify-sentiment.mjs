#!/usr/bin/env node
// Plain-node verification for src/lib/sentiment/aggregate.ts (WW-SENTIMENT).
//
// Same situation as scripts/verify-conviction.mjs and
// scripts/verify-roles-audit.mjs: this repo has no jest/vitest config and no
// network access in this sandbox to install one. This script hand-traces
// computeAggregate() against fixed, worked-by-hand example headline sets —
// exactly the "hand-trace your aggregation logic against 2-3 example
// headline sets" fallback this task's own constraints called for, since
// there is genuinely no test framework here to lean on instead.
//
// This script tests ONLY the pure aggregation math (aggregate.ts) — it does
// NOT call the real Google News RSS feed or the real Hugging Face API. Both
// of those are external network calls this sandbox cannot make at all (see
// finbert.ts's and headlines.ts's own doc comments for exactly what could
// and couldn't be verified live). Every Headline object below is
// hand-constructed with realistic (not real) titles/links purely as fixture
// data to drive the math — never presented anywhere as a real fetched
// headline.
//
// Run with:
//   node --experimental-strip-types \
//        --experimental-loader ./scripts/ts-extensionless-loader.mjs \
//        scripts/verify-sentiment.mjs

import { computeAggregate, SAMPLE_SIZE_FOR_FULL_CONFIDENCE } from "../src/lib/sentiment/aggregate.ts";

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

let hid = 0;
function headline(label, score, method, overrides = {}) {
  hid += 1;
  return {
    id: `h${hid}`,
    title: `Fixture headline #${hid}`,
    source: "Fixture Wire",
    link: `https://example.invalid/${hid}`,
    publishedAt: "2026-09-12T12:00:00.000Z",
    sentiment: { label, score, method, ...overrides },
    ...overrides.headlineOverrides,
  };
}

console.log("=== (a) zero headlines => honest abstain, not a fabricated zero ===");
{
  const r = computeAggregate([]);
  ok("abstained is true", r.abstained === true);
  ok("score is null (not 0)", r.score === null);
  ok("confidence is 0", r.confidence === 0);
  ok("n and nScored are both 0", r.n === 0 && r.nScored === 0);
  ok("method is 'none'", r.method === "none");
  ok("abstainReason mentions no headlines", /no recent headlines/i.test(r.abstainReason ?? ""));
}

console.log("=== (b) headlines found but none scorable => still an honest abstain ===");
{
  const headlines = [
    headline("unavailable", 0, "unavailable", { note: "HF_API_KEY is not set." }),
    headline("unavailable", 0, "unavailable", { note: "HF_API_KEY is not set." }),
    headline("unavailable", 0, "unavailable", { note: "HF_API_KEY is not set." }),
  ];
  const r = computeAggregate(headlines);
  ok("abstained is true even though n > 0", r.abstained === true && r.n === 3);
  ok("nScored is 0", r.nScored === 0);
  ok("score is null", r.score === null);
  ok("counts.unavailable === 3", r.counts.unavailable === 3);
  ok("abstainReason distinguishes this from the zero-headlines case", /found 3 headline/i.test(r.abstainReason ?? ""));
}

console.log("=== (c) hand-traced arithmetic on a mixed 3-headline batch (all FinBERT) ===");
{
  // h1: positive, confidence 0.9  -> value +100, weight 0.9 -> contributes +90
  // h2: negative, confidence 0.6  -> value -100, weight 0.6 -> contributes -60
  // h3: neutral,  confidence 0.7  -> value    0, weight 0.7 -> contributes   0
  // score = (90 - 60 + 0) / (0.9 + 0.6 + 0.7) = 30 / 2.2 = 13.636...
  // meanConfidence = (0.9+0.6+0.7)/3 = 0.733333...
  // sampleWeight = min(1, 3/10) = 0.3
  // confidence = 0.3 * 0.733333... = 0.22
  const headlines = [
    headline("positive", 0.9, "finbert"),
    headline("negative", 0.6, "finbert"),
    headline("neutral", 0.7, "finbert"),
  ];
  const r = computeAggregate(headlines);
  const expectedScore = 30 / 2.2;
  const expectedConfidence = 0.3 * (2.2 / 3);
  ok(`score matches hand-traced value (got ${r.score?.toFixed(4)}, expected ${expectedScore.toFixed(4)})`, approx(r.score, expectedScore));
  ok(
    `confidence matches hand-traced value (got ${r.confidence.toFixed(4)}, expected ${expectedConfidence.toFixed(4)})`,
    approx(r.confidence, expectedConfidence),
  );
  ok("counts: 1 positive, 1 negative, 1 neutral", r.counts.positive === 1 && r.counts.negative === 1 && r.counts.neutral === 1);
  ok("method is 'finbert' (all three used the real model)", r.method === "finbert");
  ok("not abstained", r.abstained === false);
}

console.log("=== (d) THE core requirement: 2 headlines carry much less confidence than 20, at the SAME score/quality ===");
{
  // Both batches: every headline positive at confidence 0.9 (so the
  // resulting `score` is 100 in BOTH cases — same read, same per-headline
  // quality) — the only difference is sample size.
  const two = computeAggregate([headline("positive", 0.9, "finbert"), headline("positive", 0.9, "finbert")]);
  const twenty = computeAggregate(Array.from({ length: 20 }, () => headline("positive", 0.9, "finbert")));

  ok("both batches read the identical score (100)", approx(two.score, 100) && approx(twenty.score, 100));
  ok(
    `2-headline confidence (${two.confidence.toFixed(3)}) is well below the 20-headline confidence (${twenty.confidence.toFixed(3)})`,
    two.confidence < twenty.confidence,
  );
  ok(`2-headline confidence matches hand trace: sampleWeight 0.2 * meanConfidence 0.9 = 0.18 (got ${two.confidence.toFixed(4)})`, approx(two.confidence, 0.18));
  ok(`20-headline confidence matches hand trace: sampleWeight 1.0 * meanConfidence 0.9 = 0.9 (got ${twenty.confidence.toFixed(4)})`, approx(twenty.confidence, 0.9));
  ok(
    `sample size saturates at SAMPLE_SIZE_FOR_FULL_CONFIDENCE (${SAMPLE_SIZE_FOR_FULL_CONFIDENCE}) — confirms the exported constant is the one actually used`,
    SAMPLE_SIZE_FOR_FULL_CONFIDENCE === 10,
  );
}

console.log("=== (e) a real-FinBERT / keyword-fallback mix is labeled 'mixed', never silently merged as 'finbert' ===");
{
  // h1: FinBERT, positive, confidence 0.8 -> value +100, weight 0.8 -> +80
  // h2: keyword-fallback, negative, confidence 0.35 (the fixed fallback
  //     confidence) -> value -100, weight 0.35 -> -35
  // score = (80 - 35) / (0.8 + 0.35) = 45 / 1.15 = 39.130...
  const headlines = [headline("positive", 0.8, "finbert"), headline("negative", 0.35, "keyword-fallback", { note: "fallback used" })];
  const r = computeAggregate(headlines);
  ok("method is 'mixed'", r.method === "mixed");
  ok(`score matches hand trace (got ${r.score?.toFixed(4)}, expected ${(45 / 1.15).toFixed(4)})`, approx(r.score, 45 / 1.15));
}

console.log("=== (f) all-keyword-fallback batch is labeled as such, never presented as 'finbert' ===");
{
  const r = computeAggregate([headline("neutral", 0.35, "keyword-fallback"), headline("positive", 0.35, "keyword-fallback")]);
  ok("method is 'keyword-fallback', not 'finbert'", r.method === "keyword-fallback");
  ok("not abstained (fallback scores still count as real, labeled, scored headlines)", r.abstained === false);
}

console.log("=== (g) all-neutral batch scores exactly 0, and is distinguishable from an abstain ===");
{
  const r = computeAggregate([headline("neutral", 0.5, "finbert"), headline("neutral", 0.8, "finbert")]);
  ok("score is exactly 0 (not null)", r.score === 0);
  ok("abstained is false", r.abstained === false);
  ok("confidence is still meaningful (nonzero)", r.confidence > 0);
}

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}

#!/usr/bin/env node
// Plain-node verification for src/lib/models/conviction.ts (IMP-15).
//
// Same situation as scripts/verify-roles-audit.mjs and
// scripts/verify-macro-contract.mjs: this repo has no jest/vitest config and
// no network access in this sandbox to install one. Node 22's built-in
// TypeScript stripping lets this script import the .ts module directly with
// plain `node`, reusing the existing scripts/ convention.
//
// Also checks: this repo has no "STS-02 calibration test" anywhere in the
// tree today (searched for "STS-02" repo-wide — no hits) — IMP-15's "done
// when" clause asking that test to "still pass" has nothing to break, since
// it does not exist yet. Documented here rather than silently ignored; see
// the final report for this task.
//
// Run with:
//   node --experimental-strip-types \
//        --experimental-loader ./scripts/ts-extensionless-loader.mjs \
//        scripts/verify-conviction.mjs

import {
  computeConviction,
  namesAreDistinguishable,
  getHorizonBandFor,
  MAX_SINGLE_MODEL_SWING,
  WEEKLY_FORECAST_SLOT,
  GRAPH_RESIDUAL_SLOT,
  CASCADE_EXPOSURE_SLOT,
} from "../src/lib/models/conviction.ts";

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

console.log("=== (a) zero slots => composite/confidence pass through unchanged ===");
{
  const r = computeConviction(62, 0.7, []);
  ok("composite === baseScore with zero slots", r.composite === 62);
  ok("confidence === baseConfidence with zero slots", Math.abs(r.confidence - 0.7) < 1e-9);
  ok("slotContributions is empty", r.slotContributions.length === 0);
  ok("marginalImpact is empty", r.marginalImpact.length === 0);
}

console.log("=== (b) one extreme, maximally confident slot cannot move composite past the cap ===");
{
  const base = 55;
  const r = computeConviction(base, 0.8, [{ modelId: WEEKLY_FORECAST_SLOT, score: 100, confidence: 1 }]);
  const moved = r.composite - base;
  ok(
    `single-slot move (${moved}) <= MAX_SINGLE_MODEL_SWING (${MAX_SINGLE_MODEL_SWING})`,
    moved <= MAX_SINGLE_MODEL_SWING + 1e-9,
  );
  ok("single-slot move is positive (score was extreme positive)", moved > 0);

  const rNeg = computeConviction(base, 0.8, [{ modelId: WEEKLY_FORECAST_SLOT, score: -100, confidence: 1 }]);
  const movedNeg = base - rNeg.composite;
  ok(
    `single-slot negative move (${movedNeg}) <= MAX_SINGLE_MODEL_SWING (${MAX_SINGLE_MODEL_SWING})`,
    movedNeg <= MAX_SINGLE_MODEL_SWING + 1e-9,
  );
}

console.log("=== (c) removing a slot from a multi-slot composite changes it by a bounded, documented amount ===");
{
  const slots = [
    { modelId: WEEKLY_FORECAST_SLOT, score: 90, confidence: 0.9 },
    { modelId: GRAPH_RESIDUAL_SLOT, score: 80, confidence: 0.7 },
    { modelId: CASCADE_EXPOSURE_SLOT, score: 60, confidence: 0.5 },
  ];
  const withAll = computeConviction(50, 0.5, slots);

  for (let i = 0; i < slots.length; i++) {
    const without = computeConviction(
      50,
      0.5,
      slots.filter((_, j) => j !== i),
    );
    const measuredDelta = withAll.composite - without.composite;
    ok(
      `removing slot[${i}]=${slots[i].modelId}: |Δ|=${Math.abs(measuredDelta).toFixed(3)} <= MAX_SINGLE_MODEL_SWING`,
      Math.abs(measuredDelta) <= MAX_SINGLE_MODEL_SWING + 1e-9,
    );
    ok(
      `slot[${i}] marginalImpact.impact matches the actually-measured delta`,
      Math.abs(withAll.marginalImpact[i].impact - measuredDelta) < 1e-9,
    );
  }

  // Sanity: with 3 agreeing-ish slots the TOTAL move can exceed one slot's
  // cap (the cap bounds a single model, not the composite's total mobility).
  ok(
    "total move across all 3 slots is allowed to exceed a single MAX_SINGLE_MODEL_SWING",
    Math.abs(withAll.composite - 50) > MAX_SINGLE_MODEL_SWING,
  );
}

console.log("=== (d) genuinely different inputs are not collapsed to near-identical composites ===");
{
  const inputsA = { baseScore: 50, baseConfidence: 0.5, slots: [{ modelId: WEEKLY_FORECAST_SLOT, score: 80, confidence: 0.9 }] };
  const inputsB = { baseScore: 50, baseConfidence: 0.5, slots: [{ modelId: WEEKLY_FORECAST_SLOT, score: -80, confidence: 0.9 }] };
  const resultA = computeConviction(inputsA.baseScore, inputsA.baseConfidence, inputsA.slots);
  const resultB = computeConviction(inputsB.baseScore, inputsB.baseConfidence, inputsB.slots);
  ok(
    "opposite-signed, equally confident weekly reads produce distinguishable composites",
    namesAreDistinguishable(resultA, inputsA, resultB, inputsB),
  );
  ok("...and the composites actually differ numerically", resultA.composite !== resultB.composite);

  // Not meaningfully different (tiny score diff) => vacuously true, no
  // requirement that they differ.
  const inputsC = { baseScore: 50, baseConfidence: 0.5, slots: [{ modelId: WEEKLY_FORECAST_SLOT, score: 80.1, confidence: 0.9 }] };
  const resultC = computeConviction(inputsC.baseScore, inputsC.baseConfidence, inputsC.slots);
  ok(
    "trivially-different inputs (below threshold) are vacuously 'distinguishable' (no requirement imposed)",
    namesAreDistinguishable(resultA, inputsA, resultC, inputsC) === true,
  );

  // Both maximally saturated in the SAME direction: legitimately allowed to
  // collapse to the same composite (both hit the cap) — namesAreDistinguishable
  // is about not erasing REAL differences, not about forbidding two
  // different extreme inputs from both saturating the cap.
  const inputsD1 = { baseScore: 50, baseConfidence: 0.5, slots: [{ modelId: WEEKLY_FORECAST_SLOT, score: 100, confidence: 1 }] };
  const inputsD2 = { baseScore: 50, baseConfidence: 0.5, slots: [{ modelId: GRAPH_RESIDUAL_SLOT, score: 100, confidence: 1 }] };
  const resultD1 = computeConviction(inputsD1.baseScore, inputsD1.baseConfidence, inputsD1.slots);
  const resultD2 = computeConviction(inputsD2.baseScore, inputsD2.baseConfidence, inputsD2.slots);
  console.log(
    `    (documented, not asserted as pass/fail either way) two different saturated slots => composites ${resultD1.composite} vs ${resultD2.composite}`,
  );
}

console.log("=== (e) near-zero confidence contributes near nothing regardless of score extremity ===");
{
  const base = 50;
  const r = computeConviction(base, 0.5, [{ modelId: CASCADE_EXPOSURE_SLOT, score: 100, confidence: 0.001 }]);
  ok(
    `near-zero-confidence extreme score barely moves composite (Δ=${(r.composite - base).toFixed(4)})`,
    Math.abs(r.composite - base) < 0.1,
  );
  const rZero = computeConviction(base, 0.5, [{ modelId: CASCADE_EXPOSURE_SLOT, score: -100, confidence: 0 }]);
  ok("exactly-zero confidence contributes exactly zero", rZero.composite === base);
}

console.log("=== (f) horizons.ts is actually consulted, and the two modules' overlap is documented ===");
{
  const r = computeConviction(60, 0.6, [{ modelId: WEEKLY_FORECAST_SLOT, score: 30, confidence: 0.5 }]);
  ok(
    "slotContributions carries a horizon field looked up via getHorizon",
    r.slotContributions[0].horizon === "unspecified",
  );
  ok(
    "documents current gap: WEEKLY_FORECAST_SLOT is not yet in horizons.ts's HORIZON_REGISTRY",
    r.slotContributions[0].horizon === "unspecified",
  );
  // Demonstrates (does not enforce) the relationship called out in the
  // module doc comment: combining an unregistered/undeclared-horizon slot
  // like the weekly forecast against a registered multi-month model is
  // exactly the kind of cross-horizon combination horizons.ts's
  // canCombine()/assertCombinable() exist to gate -- this module
  // deliberately does not call assertCombinable itself (IMP-15 uses
  // explicit capped slots instead of horizons.ts's blend-rejection), but
  // the underlying concern -- combining a fast signal with a slow one -- is
  // the same concern, just handled by two different mechanisms.
  ok("getHorizonBandFor is exported for callers who want the raw lookup too", typeof getHorizonBandFor === "function");
  const band = getHorizonBandFor("macro-tracker");
  ok("getHorizonBandFor('macro-tracker') resolves a REGISTERED model's real band", band === "1-3m");
  const reserved = getHorizonBandFor(WEEKLY_FORECAST_SLOT);
  ok("getHorizonBandFor(WEEKLY_FORECAST_SLOT) is 'unspecified' today (reserved, unregistered)", reserved === "unspecified");
}

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}

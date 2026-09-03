#!/usr/bin/env node
// Plain-node verification for src/lib/models/regime-vector.ts (IMP-09).
//
// Same rationale as scripts/verify-macro-contract.mjs and the pre-existing
// scripts/verify-roles-audit.mjs: no jest/vitest, no network to install one,
// so this runs the real .ts module directly via Node 22's built-in
// TypeScript stripping instead of hand-maintaining a plain-JS mirror.
//
// Run with:
//   node --experimental-strip-types \
//        --experimental-loader ./scripts/ts-extensionless-loader.mjs \
//        scripts/verify-regime-vector.mjs

import {
  REGIME_VECTOR_VERSION,
  REGIME_VECTOR_FIELDS,
  REGIME_VECTOR_LAYERS,
  REGIME_VECTOR_STALE_THRESHOLD_MINUTES,
  toRegimeVector,
  assertRegimeVectorCompatible,
} from "../src/lib/models/regime-vector.ts";

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

function throws(label, fn) {
  try {
    fn();
    failed++;
    console.log(`  FAIL: ${label} (did not throw)`);
  } catch (e) {
    passed++;
    console.log(`  PASS: ${label} (threw: ${e.message})`);
  }
}

function doesNotThrow(label, fn) {
  try {
    fn();
    passed++;
    console.log(`  PASS: ${label}`);
  } catch (e) {
    failed++;
    console.log(`  FAIL: ${label} (threw unexpectedly: ${e.message})`);
  }
}

// ---------------------------------------------------------------------------
// (a) field list shape
// ---------------------------------------------------------------------------
console.log("--- (a) REGIME_VECTOR_FIELDS shape ---");
ok(
  "field count == 2 scalars + one slot per REGIME_VECTOR_LAYERS entry",
  REGIME_VECTOR_FIELDS.length === 2 + REGIME_VECTOR_LAYERS.length,
);
ok("first field is filter_probability", REGIME_VECTOR_FIELDS[0] === "filter_probability");
ok("second field is tone_score", REGIME_VECTOR_FIELDS[1] === "tone_score");
ok(
  "remaining fields are layer_weight:<layer> in REGIME_VECTOR_LAYERS order",
  REGIME_VECTOR_LAYERS.every((layer, i) => REGIME_VECTOR_FIELDS[2 + i] === `layer_weight:${layer}`),
);

// ---------------------------------------------------------------------------
// (b) toRegimeVector — a fully-populated, fresh regime block
// ---------------------------------------------------------------------------
console.log("--- (b) toRegimeVector: fresh, fully-populated regime block ---");
const freshRegime = {
  structural_regime_label: "Expansion",
  filter_probability: 0.41,
  tone_score: 0.22,
  layer_weights: [
    { layer: "structural_filter", weight: 0.5 },
    { layer: "nowcaster", weight: 0.3 },
    { layer: "tilt_engine", weight: 0.2 },
  ],
  as_of: "2026-09-03T12:00:00Z",
  source_time: "2026-09-03T12:05:00Z",
};
const freshAsOf = "2026-09-03T12:10:00Z"; // 10 minutes after regime.as_of
const freshVector = toRegimeVector(freshRegime, freshAsOf);

ok("version stamped correctly", freshVector.version === REGIME_VECTOR_VERSION);
ok(
  "field_order matches REGIME_VECTOR_FIELDS exactly",
  JSON.stringify(freshVector.field_order) === JSON.stringify(REGIME_VECTOR_FIELDS),
);
ok("values length matches field_order length", freshVector.values.length === freshVector.field_order.length);
ok("values[0] (filter_probability) is 0.41", freshVector.values[0] === 0.41);
ok("values[1] (tone_score) is 0.22", freshVector.values[1] === 0.22);
ok(
  "layer weights land in the declared REGIME_VECTOR_LAYERS order",
  REGIME_VECTOR_LAYERS.every((layer, i) => {
    const expected = freshRegime.layer_weights.find((lw) => lw.layer === layer).weight;
    return freshVector.values[2 + i] === expected;
  }),
);
ok(
  "10 minutes of forward-fill, under the 60-minute threshold, is NOT stale",
  freshVector.stale === false && freshVector.staleness_minutes === 10,
);
ok(
  "source_as_of / published_at are passed through from the RegimeBlock unchanged",
  freshVector.source_as_of === freshRegime.as_of && freshVector.published_at === freshRegime.source_time,
);

// ---------------------------------------------------------------------------
// (c) toRegimeVector — staleness thresholding
// ---------------------------------------------------------------------------
console.log("--- (c) toRegimeVector: staleness thresholding ---");
const staleAsOf = "2026-09-03T14:00:00Z"; // 2 hours after regime.as_of — past the 60-min threshold
const staleVector = toRegimeVector(freshRegime, staleAsOf);
ok(
  `staleness past ${REGIME_VECTOR_STALE_THRESHOLD_MINUTES} minutes is marked stale, never silently repeated`,
  staleVector.stale === true && staleVector.staleness_minutes === 120,
);

const negativeAsOf = "2026-09-03T11:00:00Z"; // BEFORE regime.as_of — should never happen, flagged stale
const negativeVector = toRegimeVector(freshRegime, negativeAsOf);
ok(
  "asOf before the regime's own as_of (a should-never-happen case) is flagged stale, not silently fresh",
  negativeVector.stale === true && negativeVector.staleness_minutes === -60,
);

const unparseableRegime = { ...freshRegime, as_of: "not-a-timestamp" };
const unparseableVector = toRegimeVector(unparseableRegime, freshAsOf);
ok(
  "unparseable source as_of yields staleness_minutes: null but stale: true (fail-safe, never silently fresh)",
  unparseableVector.stale === true && unparseableVector.staleness_minutes === null,
);

// ---------------------------------------------------------------------------
// (d) toRegimeVector — nulls pass through honestly (no invented numbers)
// ---------------------------------------------------------------------------
console.log("--- (d) toRegimeVector: null fields pass through as null, never 0 ---");
const emptyRegime = {
  structural_regime_label: null,
  filter_probability: null,
  tone_score: null,
  layer_weights: null,
  as_of: "2026-09-03T12:00:00Z",
  source_time: "2026-09-03T12:05:00Z",
};
const emptyVector = toRegimeVector(emptyRegime, freshAsOf);
ok(
  "every value is null (not 0, not omitted) when the source RegimeBlock has nothing",
  emptyVector.values.every((v) => v === null),
);
ok("values length is still the full fixed length", emptyVector.values.length === REGIME_VECTOR_FIELDS.length);

// A regime block naming a layer NOT in REGIME_VECTOR_LAYERS: that layer's
// weight is simply not represented (no slot for it) — the known layers'
// slots stay independently correct.
const partialLayersRegime = {
  ...freshRegime,
  layer_weights: [{ layer: "structural_filter", weight: 0.9 }], // only one of three known layers present
};
const partialVector = toRegimeVector(partialLayersRegime, freshAsOf);
ok(
  "a present known layer's weight is captured",
  partialVector.values[REGIME_VECTOR_FIELDS.indexOf("layer_weight:structural_filter")] === 0.9,
);
ok(
  "an absent known layer's weight is null, not 0 or omitted",
  partialVector.values[REGIME_VECTOR_FIELDS.indexOf("layer_weight:nowcaster")] === null &&
    partialVector.values[REGIME_VECTOR_FIELDS.indexOf("layer_weight:tilt_engine")] === null,
);

// ---------------------------------------------------------------------------
// (e) assertRegimeVectorCompatible — the "fails loudly" contract
// ---------------------------------------------------------------------------
console.log("--- (e) assertRegimeVectorCompatible ---");
doesNotThrow("a genuinely current vector passes", () => assertRegimeVectorCompatible(freshVector));

throws("wrong version throws", () =>
  assertRegimeVectorCompatible({ ...freshVector, version: "0.9.0" }),
);

throws("shorter field_order (simulating a removed field) throws", () =>
  assertRegimeVectorCompatible({
    ...freshVector,
    field_order: freshVector.field_order.slice(0, -1),
    values: freshVector.values.slice(0, -1),
  }),
);

throws("longer field_order (simulating an added, unversioned field) throws", () =>
  assertRegimeVectorCompatible({
    ...freshVector,
    field_order: [...freshVector.field_order, "extra_field"],
    values: [...freshVector.values, 0],
  }),
);

throws("reordered field_order (same fields, different order) throws", () => {
  const reordered = [...freshVector.field_order].reverse();
  assertRegimeVectorCompatible({
    ...freshVector,
    field_order: reordered,
    values: [...freshVector.values].reverse(),
  });
});

throws("values/field_order length mismatch (even with a correct version/order) throws", () =>
  assertRegimeVectorCompatible({
    ...freshVector,
    values: freshVector.values.slice(0, -1),
  }),
);

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}

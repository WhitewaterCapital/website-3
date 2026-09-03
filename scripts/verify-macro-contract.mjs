#!/usr/bin/env node
// Plain-node verification for src/lib/models/macro-contract-v2.ts (IMP-06).
//
// Why this exists instead of a real test runner: this repo has no jest/
// vitest config and no network access in this sandbox to install one (see
// scripts/verify-roles-audit.mjs's header for the same situation with
// src/lib/roles.ts/audit.ts). Node 22's built-in TypeScript stripping lets
// this script import the .ts module directly with plain `node`, reusing
// this repo's existing convention rather than introducing a new framework
// or a hand-maintained plain-JS mirror of the logic under test.
//
// What this does NOT prove: it does not exercise the actual Next.js route
// handlers (src/app/api/macro/latest/route.ts,
// src/app/api/macro/point-in-time/route.ts) end-to-end — there is no
// Next.js server available in this sandbox (no node_modules/next). Instead
// it exercises the real, shared, pure logic those routes call
// (`fromAuroraExport`, `selectPointInTimeSnapshot`) directly, plus the
// actual committed fixture files under public/data/macro-history/ and the
// real public/data/aurora/latest.json — the same inputs the routes would
// see — so a genuine break in the mapping or lookup logic shows up here.
//
// Run with:
//   node --experimental-strip-types \
//        --experimental-loader ./scripts/ts-extensionless-loader.mjs \
//        scripts/verify-macro-contract.mjs

import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  SCHEMA_VERSION,
  SCHEMA_MAJOR_VERSION,
  isCompatibleSchemaVersion,
  fromAuroraExport,
  selectPointInTimeSnapshot,
} from "../src/lib/models/macro-contract-v2.ts";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

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

// ---------------------------------------------------------------------------
// (a) fromAuroraExport against the REAL committed Aurora export
// ---------------------------------------------------------------------------
console.log("--- (a) fromAuroraExport(real public/data/aurora/latest.json) ---");

const auroraRaw = await readFile(
  path.join(REPO_ROOT, "public", "data", "aurora", "latest.json"),
  "utf8",
);
const aurora = JSON.parse(auroraRaw);
const contract = fromAuroraExport(aurora);

ok("schema_version is the current SCHEMA_VERSION", contract.schema_version === SCHEMA_VERSION);
ok("contract_kind is 'macro_v2'", contract.contract_kind === "macro_v2");
ok(
  "as_of_time and source_time are separate, non-identical fields (as expected for this fixture)",
  contract.as_of_time === aurora.as_of &&
    contract.source_time === aurora.generated_at &&
    contract.as_of_time !== contract.source_time,
);
ok(
  "regime.structural_regime_label carries the real label through",
  contract.regime.structural_regime_label === aurora.regime.label,
);
ok(
  "regime.filter_probability is honestly derived from scenario_affinity[label], not invented",
  typeof aurora.regime.scenario_affinity === "object" &&
    aurora.regime.label in aurora.regime.scenario_affinity &&
    contract.regime.filter_probability === aurora.regime.scenario_affinity[aurora.regime.label],
);
ok(
  "regime.tone_score is null (no tone/sentiment layer exists in the real export)",
  contract.regime.tone_score === null,
);
ok(
  "regime.layer_weights is null (no per-layer stack weighting exists in the real export)",
  contract.regime.layer_weights === null,
);
ok(
  "regime.as_of / regime.source_time are both populated and distinct from each other's role",
  typeof contract.regime.as_of === "string" && typeof contract.regime.source_time === "string",
);
ok(
  "fromAuroraExport is deterministic: calling it twice on the same input gives identical JSON",
  JSON.stringify(fromAuroraExport(aurora)) === JSON.stringify(contract),
);

// ---------------------------------------------------------------------------
// (b) fromAuroraExport with a null regime — must not throw, must null out cleanly
// ---------------------------------------------------------------------------
console.log("--- (b) fromAuroraExport with regime: null ---");
const auroraNoRegime = { ...aurora, regime: null };
const contractNoRegime = fromAuroraExport(auroraNoRegime);
ok(
  "regime block is present with all-null fields, not thrown/omitted",
  contractNoRegime.regime.structural_regime_label === null &&
    contractNoRegime.regime.filter_probability === null &&
    contractNoRegime.regime.tone_score === null &&
    contractNoRegime.regime.layer_weights === null,
);
ok(
  "regime.as_of/source_time still fall back to the top-level timestamps",
  contractNoRegime.regime.as_of === auroraNoRegime.as_of &&
    contractNoRegime.regime.source_time === auroraNoRegime.generated_at,
);

// ---------------------------------------------------------------------------
// (c) schema version compatibility check
// ---------------------------------------------------------------------------
console.log("--- (c) isCompatibleSchemaVersion ---");
ok(`SCHEMA_MAJOR_VERSION is a number (${SCHEMA_MAJOR_VERSION})`, Number.isFinite(SCHEMA_MAJOR_VERSION));
ok("same major, different minor/patch is compatible", isCompatibleSchemaVersion(`${SCHEMA_MAJOR_VERSION}.9.9`));
ok("different major is NOT compatible", isCompatibleSchemaVersion(`${SCHEMA_MAJOR_VERSION + 1}.0.0`) === false);

// ---------------------------------------------------------------------------
// (d) selectPointInTimeSnapshot — pure lookup logic, no fs/Next.js needed
// ---------------------------------------------------------------------------
console.log("--- (d) selectPointInTimeSnapshot (pure) ---");
const entries = [
  { as_of_time: "2026-05-01", file: "2026-05-01.json" },
  { as_of_time: "2026-06-01", file: "2026-06-01.json" },
  { as_of_time: "2026-07-01", file: "2026-07-01.json" },
  { as_of_time: "2026-08-01", file: "2026-08-01.json" },
];

ok(
  "exact match on a snapshot's own as_of_time returns that snapshot",
  selectPointInTimeSnapshot(entries, "2026-07-01")?.file === "2026-07-01.json",
);
ok(
  "a timestamp between two snapshots returns the earlier (nearest-before), never the later",
  selectPointInTimeSnapshot(entries, "2026-07-15")?.file === "2026-07-01.json",
);
ok(
  "a timestamp before the earliest snapshot returns null (honest 'no data'), never a fallback",
  selectPointInTimeSnapshot(entries, "2026-01-01") === null,
);
ok(
  "a timestamp after the latest snapshot returns the latest (still never look-ahead)",
  selectPointInTimeSnapshot(entries, "2026-12-31")?.file === "2026-08-01.json",
);
ok(
  "an unparseable timestamp returns null rather than throwing or guessing",
  selectPointInTimeSnapshot(entries, "not-a-date") === null,
);
ok(
  "repeat calls with identical input return an identical result (determinism)",
  JSON.stringify(selectPointInTimeSnapshot(entries, "2026-07-15")) ===
    JSON.stringify(selectPointInTimeSnapshot(entries, "2026-07-15")),
);

// ---------------------------------------------------------------------------
// (e) the same lookup against the REAL committed fixture directory
// ---------------------------------------------------------------------------
console.log("--- (e) selectPointInTimeSnapshot against the real public/data/macro-history/ files ---");
const historyDir = path.join(REPO_ROOT, "public", "data", "macro-history");
const historyFiles = (await readdir(historyDir)).filter((f) => f.endsWith(".json"));
ok("at least 3 synthetic fixture files exist", historyFiles.length >= 3);
ok("at most 5 synthetic fixture files exist (kept small, per DATA-honesty scope)", historyFiles.length <= 5);

const historyEntries = [];
for (const file of historyFiles) {
  const raw = JSON.parse(await readFile(path.join(historyDir, file), "utf8"));
  ok(
    `${file}: is marked as a synthetic test fixture`,
    raw.__synthetic_test_fixture__ === true && typeof raw.__source_note__ === "string",
  );
  ok(`${file}: schema_version matches the current contract version`, raw.schema_version === SCHEMA_VERSION);
  historyEntries.push({ as_of_time: raw.as_of_time, file });
}

const midQuery = "2026-06-15"; // between the 06-01 and 07-01 fixtures
const picked = selectPointInTimeSnapshot(historyEntries, midQuery);
ok(
  `a query for ${midQuery} picks the 2026-06-01 fixture (nearest at-or-before), not 07-01`,
  picked?.file === "2026-06-01.json",
);

const tooEarly = selectPointInTimeSnapshot(historyEntries, "2020-01-01");
ok("a query before every fixture returns null (route must 404, never fall back to latest)", tooEarly === null);

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}

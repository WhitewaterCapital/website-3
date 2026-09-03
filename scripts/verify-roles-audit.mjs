#!/usr/bin/env node
// Plain-node verification for src/lib/roles.ts and src/lib/audit.ts (IMP-03).
//
// This repo has no TS unit test runner (no jest/vitest config, no __tests__
// dir, no *.test.ts files) and there is no network access in this sandbox to
// install one. Node 22's built-in TypeScript stripping lets this script
// import the .ts modules directly with plain `node`, mirroring the existing
// scripts/ convention (plain, dependency-free, run with `node`) rather than
// introducing a new test framework/dependency.
//
// Run with:
//   node --experimental-strip-types --experimental-loader ./scripts/ts-extensionless-loader.mjs scripts/verify-roles-audit.mjs
//
// (the loader only teaches Node's resolver to try ".ts" for the bare
// "./roles" import inside audit.ts — see ts-extensionless-loader.mjs.)

import {
  assertCanPerform,
  canPerform,
  isValidPromotionApproval,
  PROMOTION_REQUIRES_APPROVERS,
} from "../src/lib/roles.ts";
import { AuditLog } from "../src/lib/audit.ts";

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

console.log("--- (a) research_operator cannot promote ---");
throws("assertCanPerform(research_operator, promote_model) throws", () =>
  assertCanPerform(["research_operator"], "promote_model"),
);
ok(
  "canPerform(research_operator, promote_model) === false",
  canPerform(["research_operator"], "promote_model") === false,
);

console.log("--- (b) research_operator cannot touch allocator caps/floors ---");
throws("assertCanPerform(research_operator, change_allocator_cap) throws", () =>
  assertCanPerform(["research_operator"], "change_allocator_cap"),
);
throws("assertCanPerform(research_operator, change_allocator_floor) throws", () =>
  assertCanPerform(["research_operator"], "change_allocator_floor"),
);
throws("assertCanPerform(research_operator, demote_model) throws", () =>
  assertCanPerform(["research_operator"], "demote_model"),
);
throws("assertCanPerform(research_operator, trip_kill_switch) throws", () =>
  assertCanPerform(["research_operator"], "trip_kill_switch"),
);

console.log("--- research_operator CAN do its own allowed actions ---");
doesNotThrow("assertCanPerform(research_operator, retrain_model)", () =>
  assertCanPerform(["research_operator"], "retrain_model"),
);
doesNotThrow("assertCanPerform(research_operator, start_shadow_run)", () =>
  assertCanPerform(["research_operator"], "start_shadow_run"),
);
doesNotThrow("assertCanPerform(research_operator, read_model_card)", () =>
  assertCanPerform(["research_operator"], "read_model_card"),
);

console.log("--- (c) risk_approver CAN promote/demote/trip kill switch ---");
doesNotThrow("assertCanPerform(risk_approver, promote_model)", () =>
  assertCanPerform(["risk_approver"], "promote_model"),
);
doesNotThrow("assertCanPerform(risk_approver, demote_model)", () =>
  assertCanPerform(["risk_approver"], "demote_model"),
);
doesNotThrow("assertCanPerform(risk_approver, trip_kill_switch)", () =>
  assertCanPerform(["risk_approver"], "trip_kill_switch"),
);
doesNotThrow("assertCanPerform(risk_approver, change_allocator_cap)", () =>
  assertCanPerform(["risk_approver"], "change_allocator_cap"),
);
doesNotThrow("assertCanPerform(risk_approver, change_allocator_floor)", () =>
  assertCanPerform(["risk_approver"], "change_allocator_floor"),
);
console.log("--- risk_approver cannot do research_operator-only actions ---");
throws("assertCanPerform(risk_approver, retrain_model) throws", () =>
  assertCanPerform(["risk_approver"], "retrain_model"),
);

console.log("--- (d) isValidPromotionApproval ---");
const roles = {
  alice: ["risk_approver"],
  bob: ["risk_approver"],
  carol: ["research_operator"],
};

ok("PROMOTION_REQUIRES_APPROVERS === 2", PROMOTION_REQUIRES_APPROVERS === 2);

{
  const r = isValidPromotionApproval(["alice"], roles);
  ok("fails with 1 approver", r.valid === false && !!r.reason);
  console.log(`    reason: ${r.reason}`);
}
{
  const r = isValidPromotionApproval(["alice", "carol"], roles);
  ok("fails when one of two lacks risk_approver role", r.valid === false && !!r.reason);
  console.log(`    reason: ${r.reason}`);
}
{
  const r = isValidPromotionApproval(["alice", "alice"], roles);
  ok("fails with a duplicated id", r.valid === false && !!r.reason);
  console.log(`    reason: ${r.reason}`);
}
{
  const r = isValidPromotionApproval(["alice", "bob"], roles);
  ok("succeeds with 2 distinct valid risk_approvers", r.valid === true && r.reason === undefined);
}

console.log("--- (e) AuditLog.record ---");
const log = new AuditLog();

throws("record throws on empty reason", () =>
  log.record({
    action: "retrain_model",
    performedBy: "carol",
    before: { status: "idle" },
    after: { status: "retraining" },
    reason: "",
  }),
);

throws("record throws on single-person promote_model entry", () =>
  log.record(
    {
      action: "promote_model",
      performedBy: "alice",
      before: { stage: "shadow" },
      after: { stage: "live" },
      reason: "Backtest and shadow metrics clear thresholds.",
    },
    roles,
  ),
);

throws("record throws on promote_model with one approver lacking role", () =>
  log.record(
    {
      action: "promote_model",
      performedBy: ["alice", "carol"],
      before: { stage: "shadow" },
      after: { stage: "live" },
      reason: "Backtest and shadow metrics clear thresholds.",
    },
    roles,
  ),
);

let recorded;
doesNotThrow("record succeeds with 2 distinct valid approvers + reason", () => {
  recorded = log.record(
    {
      action: "promote_model",
      performedBy: ["alice", "bob"],
      before: { stage: "shadow", modelId: "m-42" },
      after: { stage: "live", modelId: "m-42" },
      reason: "Backtest and shadow metrics clear thresholds; sign-off from both approvers.",
    },
    roles,
  );
});

ok("recorded entry has generated id", typeof recorded?.id === "string" && recorded.id.length > 0);
ok("recorded entry has ISO timestamp", typeof recorded?.timestamp === "string" && !Number.isNaN(Date.parse(recorded.timestamp)));
ok(
  "recorded entry stored performedBy as the 2 approvers",
  Array.isArray(recorded?.performedBy) &&
    recorded.performedBy.length === 2 &&
    recorded.performedBy.includes("alice") &&
    recorded.performedBy.includes("bob"),
);
ok("log.list() contains the entry", log.list().some((e) => e.id === recorded?.id));
ok("log.getById(id) returns the entry", log.getById(recorded?.id)?.id === recorded?.id);

console.log("--- (f) AuditLog has no update/delete-shaped method ---");
ok("typeof log.update === 'undefined'", typeof log.update === "undefined");
ok("typeof log.delete === 'undefined'", typeof log.delete === "undefined");
ok("typeof log.remove === 'undefined'", typeof log.remove === "undefined");
ok("typeof log.edit === 'undefined'", typeof log.edit === "undefined");
ok("typeof log.clear === 'undefined'", typeof log.clear === "undefined");
ok("typeof log.set === 'undefined'", typeof log.set === "undefined");
{
  const proto = Object.getOwnPropertyNames(Object.getPrototypeOf(log));
  ok(
    "AuditLog prototype methods are exactly [constructor, record, list, getById]",
    JSON.stringify(proto.sort()) === JSON.stringify(["constructor", "getById", "list", "record"].sort()),
  );
}

console.log("");
console.log(`${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}

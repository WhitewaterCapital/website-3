// IMP-06 — the machine-readable macro contract.
//
// `public/data/aurora/latest.json` (typed by src/lib/models/aurora-export.ts,
// read-only reference for this file — not edited here) is the Aurora macro
// engine's real output. It was built for a dashboard reader
// (src/components/MacroReader.tsx): every field can be `null`, but there is
// no explicit schema *version contract*, no separated "as of" vs "source"
// timestamp pair, and — most relevant to IMP-06 — no first-class regime
// block. `regime` on the raw export mixes a label, a per-indicator list, and
// a `scenario_affinity` map that a training job would have to know to parse
// by hand.
//
// This file defines `MacroContractV2`: a versioned wrapper a training job
// can consume without any dashboard-specific knowledge, plus the new
// `RegimeBlock` IMP-06 asks for, and `fromAuroraExport()`, the (pure,
// deterministic) function that builds one from a real Aurora export.
//
// SCHEMA DRIFT, DOCUMENTED: aurora-export.ts's `RegimeRead` interface
// declares `probabilities: Record<string, number> | null`. The actual
// engine output does not have that field — it emits `scenario_affinity`
// instead (verified directly against public/data/aurora/latest.json as of
// 2026-08-11; the raw JSON's `regime` object has `label`, `scenario_affinity`,
// `key_indicators`, `confidence`, `flags` — no `probabilities` key at all).
// `buildRegimeBlock` below reads the field that is ACTUALLY present, and
// says so in a comment, rather than trusting the stale type declaration.
// Fixing aurora-export.ts itself is out of scope for this pass (read-only
// per this task's file ownership) — flagged here so the drift is not lost.
//
// VERSIONING CONTRACT (the IMP-06 rule, stated once, applied everywhere in
// this file): adding a field to `MacroContractV2` inside major version 2 is
// always safe for an existing consumer (unknown fields are ignorable).
// Changing what an EXISTING field means (unit, range, semantics) is a
// breaking change and requires bumping the major version and adding an
// entry to `MIGRATION_NOTES` below — never a silent redefinition.

// No "server-only" guard here (unlike src/lib/aurora.ts): this module does
// no filesystem/secret access of its own, is pure data shapes + pure
// functions, and needs to be importable both from Next.js server code and
// directly by the plain-node verification script (scripts/verify-macro-
// contract.mjs) — matching this repo's existing convention in
// src/lib/roles.ts / src/lib/audit.ts, which are also import-anywhere pure
// modules with their own plain-node verification script.
import type { MacroExport } from "./aurora-export";

export const SCHEMA_VERSION = "2.0.0";

/** Major-version part of `SCHEMA_VERSION`, e.g. 2 for "2.0.0". Two contracts
 * are compatible (same field meanings) iff their major versions match. */
export const SCHEMA_MAJOR_VERSION = Number(SCHEMA_VERSION.split(".")[0]);

/** One entry per released major version: what changed and why. Required by
 * IMP-06's "changing what a field means needs a version bump and a
 * migration note" rule — this is that note, kept next to the version it
 * documents rather than in a separate changelog that can drift away from
 * the code. */
export const MIGRATION_NOTES: Readonly<Record<string, string>> = Object.freeze({
  "2.0.0":
    "Initial machine-readable macro contract (IMP-06). Wraps the existing " +
    "Aurora dashboard export (schema_version 0.x) rather than replacing it: " +
    "`as_of_time`/`source_time` are pulled apart into two always-separate " +
    "required timestamps (never merged into one 'as of' string), and a new " +
    "`regime` block (`RegimeBlock`) makes the structural regime label, the " +
    "real-time filter probability, a tone score, and per-layer stack " +
    "weights independently machine-readable — each nullable on its own " +
    "when the underlying engine does not (yet) produce it, rather than the " +
    "whole regime read being all-or-nothing null. `filter_probability` is " +
    "honestly derived (see buildRegimeBlock) from the source's " +
    "`scenario_affinity` map, not invented; `tone_score` and `layer_weights` " +
    "are null in this version because nothing in the current Aurora export " +
    "supports them yet — see IMP-09 (regime-vector.ts) for the vector " +
    "export that `layer_weights` will eventually come from.",
});

// ---------------------------------------------------------------------------
// Regime block (the IMP-06 headline addition)
// ---------------------------------------------------------------------------

/** One layer's contribution weight inside the regime stack. Order in the
 * array is meaningful and stable — see IMP-09 / regime-vector.ts, which
 * turns this same data into a fixed-order numeric vector for WW-STATE. */
export interface LayerWeight {
  layer: string; // stable layer id, e.g. "structural_filter", "nowcaster", "tilt"
  weight: number; // unitless; layer weights are expected (not enforced here) to sum to ~1
}

export interface RegimeBlock {
  /** e.g. "Mixed / transitional" — the engine's own regime label. Null
   * until the engine has enough data to call a regime at all. */
  structural_regime_label: string | null;

  /** 0-1. The "real time filter probability" IMP-06 asks for: how much
   * probability mass the engine's own regime-affinity distribution places
   * on the regime it actually labeled. Derived, not invented — see
   * `buildRegimeBlock`'s comment for exactly how, and when it is null. */
  filter_probability: number | null;

  /** Unitless sentiment/tone score, conventionally in roughly [-1, 1] when
   * populated (negative = risk-off / bearish tone, positive = risk-on /
   * bullish tone). Null in this schema version: no tone/sentiment layer
   * exists anywhere in the current Aurora export (no news/NLP input feeds
   * `regime`, `tilt`, or `nowcast` today). Set this only when a real tone
   * signal is wired in — never a placeholder or a proxy dressed up as tone. */
  tone_score: number | null;

  /** Fixed-order list of {layer, weight}. Null in this schema version: the
   * current engine has no notion of a weighted stack of layers producing
   * the regime read — `scenario_affinity` is a distribution over regime
   * LABELS, not a weighting of the layers that produce the read, so it is
   * not reused here under a misleading name. */
  layer_weights: LayerWeight[] | null;

  /** ISO date/timestamp: the regime read's own data currency (mirrors the
   * raw export's `regime.as_of`, which can lag the top-level contract's
   * `as_of_time` — ragged-edge macro data). */
  as_of: string;

  /** ISO timestamp: when the source snapshot this regime block was
   * extracted from was generated (mirrors the top-level `source_time`).
   * Kept on the block too so a regime block handed around on its own still
   * carries its own provenance. */
  source_time: string;
}

// ---------------------------------------------------------------------------
// Top-level contract
// ---------------------------------------------------------------------------

export interface MacroContractV2 {
  schema_version: string; // e.g. "2.0.0" — see SCHEMA_VERSION / isCompatibleSchemaVersion
  contract_kind: "macro_v2";
  engine_version: string; // Aurora engine package version, carried through as-is

  /** ISO timestamp/date: the timestamp this contract's macro state is
   * CURRENT TO (mirrors the raw export's `as_of`). Never merged with
   * `source_time` — the two answer different questions ("what does the
   * world look like as of when" vs. "when was this file produced"). */
  as_of_time: string;

  /** ISO timestamp: when the underlying source snapshot was generated
   * (mirrors the raw export's `generated_at`). A training job asking "what
   * did I actually know at time T" must compare against `source_time`, not
   * `as_of_time` — a file generated later can describe an earlier as-of
   * date, and code that is not careful about that distinction is exactly
   * how look-ahead bias creeps into a backtest. */
  source_time: string;

  model_variant: MacroExport["model_variant"];
  disclaimer: string;

  regime: RegimeBlock;

  // Carried through from the underlying Aurora export unchanged (typed via
  // aurora-export.ts, which is not modified by this file) — MacroContractV2
  // wraps and versions the contract, it does not throw away the rest of the
  // real payload a training job may still want.
  steady_state: MacroExport["steady_state"];
  scenarios: MacroExport["scenarios"];
  tilt: MacroExport["tilt"];
  nowcast: MacroExport["nowcast"];
}

/** True iff `version`'s major component matches this module's
 * `SCHEMA_MAJOR_VERSION` — the "backward compatible inside a major version"
 * check a consumer should run before trusting a contract's field meanings. */
export function isCompatibleSchemaVersion(version: string): boolean {
  const major = Number(String(version).split(".")[0]);
  return Number.isFinite(major) && major === SCHEMA_MAJOR_VERSION;
}

function buildRegimeBlock(aurora: MacroExport): RegimeBlock {
  const regime = aurora.regime;
  if (!regime) {
    return {
      structural_regime_label: null,
      filter_probability: null,
      tone_score: null,
      layer_weights: null,
      as_of: aurora.as_of,
      source_time: aurora.generated_at,
    };
  }

  // `regime.scenario_affinity` is not declared on the `RegimeRead` type in
  // aurora-export.ts (which declares `probabilities` instead — see the
  // schema-drift note at the top of this file), so it is read off the raw
  // object rather than through the (currently inaccurate) type.
  const raw = regime as unknown as {
    label: string | null;
    scenario_affinity?: Record<string, number> | null;
    as_of: string;
  };
  const affinity = raw.scenario_affinity ?? null;

  // Honest derivation, not an invented number: the probability mass the
  // engine's own affinity distribution assigns to the regime it labeled.
  // Only meaningful when the label is actually one of the distribution's
  // keys — otherwise there is nothing real to report.
  const filterProbability =
    affinity && raw.label != null && Object.prototype.hasOwnProperty.call(affinity, raw.label)
      ? affinity[raw.label]
      : null;

  return {
    structural_regime_label: raw.label ?? null,
    filter_probability: filterProbability,
    tone_score: null, // no tone/sentiment layer in the current engine — see MIGRATION_NOTES
    layer_weights: null, // no per-layer stack weighting in the current engine — see MIGRATION_NOTES
    as_of: raw.as_of,
    source_time: aurora.generated_at,
  };
}

/**
 * Build a `MacroContractV2` from a real Aurora export. Pure and
 * deterministic: every field is derived from `aurora` alone — no
 * `Date.now()`, no randomness, no ambient state — so the same input
 * always produces the same output. This is what makes the point-in-time
 * endpoint honestly reproducible: replaying it against the same stored
 * snapshot must always yield the same contract.
 */
export function fromAuroraExport(aurora: MacroExport): MacroContractV2 {
  return {
    schema_version: SCHEMA_VERSION,
    contract_kind: "macro_v2",
    engine_version: aurora.engine_version,
    as_of_time: aurora.as_of,
    source_time: aurora.generated_at,
    model_variant: aurora.model_variant,
    disclaimer: aurora.disclaimer,
    regime: buildRegimeBlock(aurora),
    steady_state: aurora.steady_state,
    scenarios: aurora.scenarios,
    tilt: aurora.tilt,
    nowcast: aurora.nowcast,
  };
}

// ---------------------------------------------------------------------------
// Point-in-time snapshot selection (shared, pure — used by both
// src/app/api/macro/point-in-time/route.ts and its plain-node verification
// script, exactly so the lookup logic can be exercised without any Next.js
// request/response machinery).
// ---------------------------------------------------------------------------

export interface HistorySnapshotIndexEntry {
  /** The snapshot's own `as_of_time` (from its MacroContractV2 JSON). */
  as_of_time: string;
  /** Filename within public/data/macro-history/, for the caller to re-read. */
  file: string;
}

/**
 * Pick the correct snapshot for a point-in-time query: the entry with the
 * LATEST `as_of_time` that is still `<= requestedTimestamp`. Never picks a
 * snapshot from after the requested time — that would be look-ahead, the
 * one thing PIT discipline exists to prevent. Returns `null` when no
 * snapshot qualifies (nothing was published yet as of that timestamp) —
 * the caller's job is to turn that into an honest "no data" response, never
 * a silent fall-through to the latest live snapshot.
 *
 * Pure and deterministic: no `Date.now()`, no I/O, no randomness. Given the
 * same `entries` and `requestedTimestamp`, always returns the same result.
 */
export function selectPointInTimeSnapshot(
  entries: readonly HistorySnapshotIndexEntry[],
  requestedTimestamp: string,
): HistorySnapshotIndexEntry | null {
  const requested = Date.parse(requestedTimestamp);
  if (Number.isNaN(requested)) return null;

  let best: HistorySnapshotIndexEntry | null = null;
  let bestTime = -Infinity;
  for (const entry of entries) {
    const t = Date.parse(entry.as_of_time);
    if (Number.isNaN(t)) continue;
    if (t <= requested && t > bestTime) {
      best = entry;
      bestTime = t;
    }
  }
  return best;
}

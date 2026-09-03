// IMP-09 — the regime stack as numbers, not just a picture.
//
// `RegimeBlock` (src/lib/models/macro-contract-v2.ts, IMP-06) already makes
// the regime stack's fields individually machine-readable. This module adds
// the one thing IMP-09 specifically asks for on top of that: a FIXED-LENGTH
// numeric vector, in a STABLE field order, that a downstream consumer
// (WW-STATE) can read with zero bespoke parsing — index `i` of `.values`
// always means the same thing as long as `.version` matches
// `REGIME_VECTOR_VERSION`.
//
// Two things this module deliberately does NOT do, both intentional and
// both left as follow-up work — noted in this pass's report:
//   1. It does not wire into `src/lib/state.ts` (WW-STATE's own code) —
//      that file is out of this task's file ownership. `toRegimeVector` and
//      `assertRegimeVectorCompatible` are built and tested standalone; a
//      later pass can have WW-STATE call them with a one-line integration.
//   2. `structural_regime_label` (a string) is intentionally excluded from
//      the numeric vector — a vector of numbers cannot carry a category
//      without an encoding scheme (one-hot against a versioned label set,
//      say), and inventing one was out of scope here. The label is still
//      available out-of-band on the `RegimeBlock` itself; a future version
//      bump can add a one-hot block to the vector if a consumer needs it.
//
// VERSIONING (the literal "fails loudly rather than quietly shifting model
// inputs" requirement): `REGIME_VECTOR_VERSION` and `REGIME_VECTOR_FIELDS`
// are frozen together. ANY change to the field list's length or order is a
// breaking change and MUST bump `REGIME_VECTOR_VERSION` — never edit the
// array's contents without also bumping the version. Every exported vector
// carries its own `version` and `field_order`; `assertRegimeVectorCompatible`
// is what a consumer runs before trusting `.values`' positions at all.

import type { RegimeBlock } from "./macro-contract-v2";

export const REGIME_VECTOR_VERSION = "1.0.0";

/**
 * Canonical, fixed-order layer names this vector definition knows about.
 * One `layer_weight:<name>` slot exists in `REGIME_VECTOR_FIELDS` for each
 * name here, in this order. Adding, removing, or reordering a layer here
 * changes the vector's length/order and is a `REGIME_VECTOR_VERSION` bump,
 * exactly like changing `REGIME_VECTOR_FIELDS` directly.
 */
export const REGIME_VECTOR_LAYERS = [
  "structural_filter",
  "nowcaster",
  "tilt_engine",
] as const;

export type RegimeVectorLayer = (typeof REGIME_VECTOR_LAYERS)[number];

/**
 * The stable field order. Derived directly from `RegimeBlock`
 * (macro-contract-v2.ts) so the two stay consistent by construction:
 * every numeric field on `RegimeBlock` gets exactly one slot here
 * (`structural_regime_label` excluded — see the module doc comment above).
 */
export const REGIME_VECTOR_FIELDS = [
  "filter_probability",
  "tone_score",
  ...REGIME_VECTOR_LAYERS.map((layer) => `layer_weight:${layer}` as const),
] as const;

export type RegimeVectorField = (typeof REGIME_VECTOR_FIELDS)[number];

/** Past this many minutes of forward-fill (asOf vs. the regime data's own
 * `as_of`), an hourly consumer's vector is marked `stale`. The macro clock
 * publishes far less often than hourly, so this is deliberately tight
 * enough to mark essentially every hourly tick as a forward fill of the
 * last real publish — the point is the marking, not the exact cutoff. */
export const REGIME_VECTOR_STALE_THRESHOLD_MINUTES = 60;

export interface RegimeVectorExport {
  /** Must equal `REGIME_VECTOR_VERSION` at the time this was produced. */
  version: string;
  /** Must equal `REGIME_VECTOR_FIELDS` at the time this was produced —
   * embedded on every export so a consumer can self-check without also
   * importing this module (still recommended: use
   * `assertRegimeVectorCompatible`, which does import it). */
  field_order: readonly string[];
  /** One entry per `field_order` slot, same order. `null` means "this
   * field's value is genuinely unknown", never a stand-in 0. */
  values: (number | null)[];
  /** ISO timestamp this export is being reported AS OF — typically the
   * hourly consumer's own clock tick, which is why it can differ from
   * `source_as_of` below (that's exactly what forward-filling means). */
  as_of: string;
  /** ISO timestamp the underlying `RegimeBlock` was actually last current
   * to (`RegimeBlock.as_of`, passed through unchanged). When this is older
   * than `as_of`, the values above are a forward fill of that reading, not
   * a fresh one — `stale`/`staleness_minutes` quantify exactly how much. */
  source_as_of: string;
  /** ISO timestamp the source `RegimeBlock` snapshot was generated
   * (`RegimeBlock.source_time`, passed through unchanged). */
  published_at: string;
  /** True whenever this export is a forward fill rather than a fresh
   * regime-clock publish (per `REGIME_VECTOR_STALE_THRESHOLD_MINUTES`), OR
   * whenever staleness cannot even be computed (unparseable timestamps) —
   * unknown timing is treated as stale, never silently treated as fresh.
   * Never repeat a value without this flag saying so. */
  stale: boolean;
  /** Minutes between `as_of` and `source_as_of` (>= 0 for a normal forward
   * fill). `null` when either timestamp could not be parsed — `stale` is
   * still `true` in that case, this field just can't quantify it. */
  staleness_minutes: number | null;
}

/**
 * Serialize a `RegimeBlock` into the fixed-length, fixed-order numeric
 * vector `REGIME_VECTOR_FIELDS` declares, for the hourly clock tick
 * `asOf`. Pure: no `Date.now()` is read internally — `asOf` is always the
 * caller's explicit clock, so the same `(regime, asOf)` pair always
 * produces the same export.
 */
export function toRegimeVector(regime: RegimeBlock, asOf: string): RegimeVectorExport {
  const layerWeightByName = new Map<string, number>(
    (regime.layer_weights ?? []).map((lw) => [lw.layer, lw.weight]),
  );

  const values: (number | null)[] = REGIME_VECTOR_FIELDS.map((field) => {
    if (field === "filter_probability") return regime.filter_probability;
    if (field === "tone_score") return regime.tone_score;
    if (field.startsWith("layer_weight:")) {
      const layerName = field.slice("layer_weight:".length);
      return layerWeightByName.has(layerName) ? layerWeightByName.get(layerName)! : null;
    }
    // Exhaustiveness guard: every entry in REGIME_VECTOR_FIELDS must be
    // handled by one of the branches above. Reaching here means a field
    // was added to REGIME_VECTOR_FIELDS without teaching this function
    // about it — fail loudly instead of silently emitting a wrong vector.
    throw new Error(`toRegimeVector: no mapping implemented for declared field "${field}"`);
  });

  const requestedMs = Date.parse(asOf);
  const sourceMs = Date.parse(regime.as_of);

  let stalenessMinutes: number | null = null;
  let stale = true; // fail-safe default: unknown timing is stale, never silently fresh
  if (!Number.isNaN(requestedMs) && !Number.isNaN(sourceMs)) {
    stalenessMinutes = Math.round((requestedMs - sourceMs) / 60_000);
    // Negative staleness would mean the regime data is timestamped AFTER
    // the consumer's own clock tick — that should never happen for a
    // genuine forward fill, and is flagged stale (something is wrong)
    // rather than silently accepted as "fresh".
    stale = stalenessMinutes < 0 || stalenessMinutes > REGIME_VECTOR_STALE_THRESHOLD_MINUTES;
  }

  return {
    version: REGIME_VECTOR_VERSION,
    field_order: REGIME_VECTOR_FIELDS,
    values,
    as_of: asOf,
    source_as_of: regime.as_of,
    published_at: regime.source_time,
    stale,
    staleness_minutes: stalenessMinutes,
  };
}

/**
 * Throws if `vector`'s declared version, field-order length, field-order
 * contents, or values length doesn't match this module's current
 * `REGIME_VECTOR_VERSION`/`REGIME_VECTOR_FIELDS` — the literal IMP-09
 * requirement that "a definition change fails loudly at the consumer
 * rather than quietly shifting model inputs". A consumer (e.g. WW-STATE)
 * should call this on every vector it reads before touching `.values` by
 * index. Never returns a boolean — a definition mismatch is not a
 * recoverable condition a caller should be able to shrug off.
 */
export function assertRegimeVectorCompatible(vector: RegimeVectorExport): void {
  if (vector.version !== REGIME_VECTOR_VERSION) {
    throw new Error(
      `Regime vector version mismatch: consumer expects ${REGIME_VECTOR_VERSION}, ` +
        `got ${vector.version}. A version change means field meaning/length/order ` +
        `may differ — refusing to interpret .values against the wrong definition.`,
    );
  }

  if (vector.field_order.length !== REGIME_VECTOR_FIELDS.length) {
    throw new Error(
      `Regime vector length mismatch: expected ${REGIME_VECTOR_FIELDS.length} fields ` +
        `(${REGIME_VECTOR_FIELDS.join(", ")}), got ${vector.field_order.length} ` +
        `(${vector.field_order.join(", ")}).`,
    );
  }

  for (let i = 0; i < REGIME_VECTOR_FIELDS.length; i++) {
    if (vector.field_order[i] !== REGIME_VECTOR_FIELDS[i]) {
      throw new Error(
        `Regime vector field-order mismatch at index ${i}: expected ` +
          `"${REGIME_VECTOR_FIELDS[i]}", got "${vector.field_order[i]}". Field order is ` +
          `part of this vector's definition — a reordering is breaking exactly like a ` +
          `length change and requires a REGIME_VECTOR_VERSION bump.`,
      );
    }
  }

  if (vector.values.length !== vector.field_order.length) {
    throw new Error(
      `Regime vector values/field_order length mismatch: ${vector.values.length} values ` +
        `for ${vector.field_order.length} declared fields.`,
    );
  }
}

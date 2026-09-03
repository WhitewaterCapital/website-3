// ═══════════════════════════════════════════════════════════════════════════
// IMP-20 — Horizon registry.
//
// Every model on the desk operates over a declared time horizon: Intra /
// Exitus swings intraday-to-multiday levels, Macro Tracker reads a slower
// regime, an equity quality read moves on a quarterly reporting cadence.
// Combining two models' outputs (blending scores, netting directional calls,
// averaging conviction) is only sound when their horizons actually overlap
// or there is a documented rule bridging them — otherwise you're averaging a
// day-trade signal with a multi-quarter one and calling the result a number.
//
// "Done when" (IMP-20's acceptance criterion): combining across horizons
// without a documented rule is REJECTED AT THE INTERFACE as an error, not a
// warning — a caller cannot silently blend incompatible horizons. It either
// finds (or adds) an explicit rule here, or the combine call throws.
//
// This module is a small, self-contained pure registry + check. It is not
// wired into any call site yet (no code today combines model outputs) — it
// exists so future code that wants to has a correct, honest gate to call
// before doing so: `assertCombinable(idA, idB)`.
// ═══════════════════════════════════════════════════════════════════════════

// A horizon band, expressed as a label rather than a numeric range so it can
// be read and reasoned about directly. HORIZON_ORDER below gives these bands
// a sequence, used only to compute "adjacent" for the default combine rule.
export type HorizonBand =
  | "1min-4h" // intraday
  | "1-10d" // short tactical (Intra / Exitus's stated planning window)
  | "1w" // weekly
  | "1-3m" // tactical-to-quarterly (regime reads, fundamentals cadence)
  | "1-3y" // structural / secular
  | "unspecified"; // not yet declared — see getHorizon()

const HORIZON_ORDER: HorizonBand[] = ["1min-4h", "1-10d", "1w", "1-3m", "1-3y"];

export interface HorizonEntry {
  modelId: string; // must match a ModelMeta.id in registry.ts's MODELS
  band: HorizonBand;
  note: string; // why this band, in one line
}

// One entry per registered model. Deliberately NOT derived automatically from
// MODELS — a model with no entry here is a visible gap (getHorizon returns
// undefined, canCombine returns false), not a silent "everything combines"
// default. Add a line whenever you register a new model in registry.ts.
export const HORIZON_REGISTRY: HorizonEntry[] = [
  {
    modelId: "macro-tracker",
    band: "1-3m",
    note: "Daily regime/sector read; the read itself is fast but the regime it describes moves on a monthly-to-quarterly cadence.",
  },
  {
    modelId: "distresse",
    band: "unspecified",
    note: "A point-in-time verdict on an idea, not itself horizon-bound — it inherits whatever horizon the idea states.",
  },
  {
    modelId: "intra-exitus",
    band: "1-10d",
    note: "Entry/exit levels sized for a tactical swing — its own time-stops run days to a couple of weeks.",
  },
  {
    modelId: "equity",
    band: "1-3m",
    note: "Cross-sectional quality/valuation read — the underlying fundamentals move on a quarterly reporting cadence.",
  },
  {
    modelId: "your-macro-algo",
    band: "unspecified",
    note: "Reserved slot — declare its real horizon here once it's built; until then it combines with nothing.",
  },
];

// Pairs of bands documented as combinable even though they are not the same
// band and not adjacent in HORIZON_ORDER. Keep this list short, and comment
// each entry — this is the ONE place a cross-horizon blend is allowed at all.
const DOCUMENTED_CROSS_HORIZON_RULES: [HorizonBand, HorizonBand][] = [
  // The desk always reads Macro's regime backdrop before sizing an Intra
  // plan — that hand-off is documented practice, so this pairing is allowed
  // even though "1-3m" and "1-10d" aren't adjacent bands.
  ["1-3m", "1-10d"],
];

function isAdjacent(a: HorizonBand, b: HorizonBand): boolean {
  const ia = HORIZON_ORDER.indexOf(a);
  const ib = HORIZON_ORDER.indexOf(b);
  if (ia === -1 || ib === -1) return false; // "unspecified" is never adjacent to anything
  return Math.abs(ia - ib) === 1;
}

function isDocumentedCrossHorizon(a: HorizonBand, b: HorizonBand): boolean {
  return DOCUMENTED_CROSS_HORIZON_RULES.some(([x, y]) => (x === a && y === b) || (x === b && y === a));
}

export function getHorizon(modelId: string): HorizonEntry | undefined {
  return HORIZON_REGISTRY.find((h) => h.modelId === modelId);
}

// Pure check: can two models' outputs be combined on horizon grounds alone?
// An unregistered model, or a model whose horizon is "unspecified", never
// combines with anything (including another "unspecified" model, unless it's
// literally the same model) — an undeclared horizon is a gap to fill in
// HORIZON_REGISTRY, not a green light to blend.
export function canCombine(idA: string, idB: string): boolean {
  if (idA === idB) return true; // a model always "combines" with itself
  const a = getHorizon(idA);
  const b = getHorizon(idB);
  if (!a || !b) return false;
  if (a.band === "unspecified" || b.band === "unspecified") return false;
  return a.band === b.band || isAdjacent(a.band, b.band) || isDocumentedCrossHorizon(a.band, b.band);
}

// Throws with a clear, specific message — the enforcement point IMP-20 asks
// for: combining across undocumented horizons is a hard interface error,
// never a console warning that's easy to miss or silence.
export function assertCombinable(idA: string, idB: string): void {
  if (canCombine(idA, idB)) return;
  const describe = (id: string) => {
    const e = getHorizon(id);
    return e ? `${id} (${e.band})` : `${id} (unregistered — add it to HORIZON_REGISTRY)`;
  };
  throw new Error(
    `Cannot combine ${describe(idA)} with ${describe(idB)}: no documented horizon-combination rule ` +
      `covers this pair. Add an explicit entry to DOCUMENTED_CROSS_HORIZON_RULES in horizons.ts if this ` +
      `combination is actually sound — never blend across horizons silently.`,
  );
}

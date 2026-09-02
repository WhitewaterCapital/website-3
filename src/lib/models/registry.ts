import type {
  ModelMeta,
  EvaluatorModel,
  LevelsModel,
  MacroModel,
  EquityModel,
} from "./types";
import { macroTracker } from "./impl/macro-tracker";
import { distresse } from "./impl/distresse";
import { intraExitus } from "./impl/intra-exitus";
import { yourMacroAlgo } from "./impl/_template";

// ═══════════════════════════════════════════════════════════════════════════
// THE REGISTRY — the hub where every model is wired in.
//
// To add one of your algos:
//   1. Build it in impl/<name>.ts (copy impl/_template.ts).
//   2. Import it here.
//   3. Add it to `models` below, and to the matching typed array if it's live.
// That's it — the pages and API routes read from here, so nothing else changes.
// ═══════════════════════════════════════════════════════════════════════════

// Named handles for the models the app calls directly.
export const models = {
  macroTracker,
  distresse,
  intraExitus,
};

// Typed rosters — live models, grouped by what they do. Generic UI (and any
// future "run every macro model" logic) iterates these.
export const macroModels: MacroModel[] = [macroTracker];
export const equityModels: EquityModel[] = []; // add your equity model here
export const evaluators: EvaluatorModel[] = [distresse];
export const levelsModels: LevelsModel[] = [intraExitus];

// Everything shown on the Models hub — live models plus planned/reserved slots.
export const MODELS: ModelMeta[] = [
  macroTracker.meta,
  distresse.meta,
  intraExitus.meta,
  yourMacroAlgo.meta, // planned — the reserved slot for your macro algo
];

// The macro model the daily tracker + consensus chat read from.
export const primaryMacro = (): MacroModel => macroModels[0];

export function getModel(id: string): ModelMeta | undefined {
  return MODELS.find((m) => m.id === id);
}

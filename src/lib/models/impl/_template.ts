import type { MacroModel, MacroReading } from "../types";
// import { aiEnabled } from "../shared";

// ═══════════════════════════════════════════════════════════════════════════
// TEMPLATE — copy this file to add one of your own models.
//
// Steps:
//   1. Copy this file to  src/lib/models/impl/<your-model>.ts
//   2. Pick the interface that matches what your model outputs:
//        EvaluatorModel  → judges a trade idea      (like Distresse)
//        LevelsModel     → entry/exit levels         (like Intra / Exitus)
//        MacroModel      → a dated macro reading      (like Macro Tracker)
//   3. Fill in `meta`, implement the one method, return the typed shape.
//   4. Register it in registry.ts (add to `models` and, if live, the arrays).
//
// This example is a MacroModel. Swap the interface + method for another kind.
// It is exported but NOT registered as live — safe to leave here as reference.
// ═══════════════════════════════════════════════════════════════════════════

export const yourMacroAlgo: MacroModel = {
  meta: {
    id: "your-macro-algo",
    name: "Your Macro Algo",
    kind: "custom",
    status: "planned", // "live" once implemented, "beta" while testing
    tagline: "Reserved — plug your proprietary macro model in here.",
    description:
      "A slot for one of the macro algorithms you're building. Implement read() and register it; it sits alongside the others, same interface, no rewrite.",
  },

  async read(dateISO: string): Promise<MacroReading> {
    // TODO: replace with your model. Pull your inputs, optionally branch on
    //       aiEnabled(), and return a MacroReading (see types.ts for the shape).
    throw new Error("your-macro-algo: not implemented yet");

    // Example of the shape you must return:
    // return {
    //   date: dateISO,
    //   regime: "…",
    //   sentiment: 0,          // -100 .. +100
    //   sectors: [],           // SectorRead[]
    //   catalysts: [],         // Catalyst[]
    //   summary: "…",
    //   generatedBy: "Your Macro Algo",
    // };
  },
};

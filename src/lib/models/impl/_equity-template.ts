import type { EquityModel, EquityReading } from "../types";
// import { aiEnabled } from "../shared";

// ═══════════════════════════════════════════════════════════════════════════
// TEMPLATE — copy this to build the Equity model (Sentimentum · Equity).
//
// Steps:
//   1. Copy to  src/lib/models/impl/equity.ts  (or your own name)
//   2. Fill in `meta`, implement read(), return an EquityReading.
//   3. Register in registry.ts: import it and add to `equityModels`.
//   4. Render its output in the Equity sub-tab of Sentimentum.
//
// This is fully isolated — it shares no state with the macro model or any
// other model, so building it can't interfere with them.
// ═══════════════════════════════════════════════════════════════════════════

export const equityModel: EquityModel = {
  meta: {
    id: "equity",
    name: "Equity",
    kind: "equity",
    status: "planned", // "live" once implemented, "beta" while testing
    tagline: "Bottom-up, single-name and equity-market read.",
    description:
      "The equity lens inside Sentimentum — what's moving and why, from the bottom up.",
  },

  async read(dateISO: string): Promise<EquityReading> {
    // TODO: replace with your model. Pull your inputs, optionally branch on
    //       aiEnabled(), and return an EquityReading (see types.ts).
    throw new Error("equity model: not implemented yet");

    // Example of the shape to return:
    // return {
    //   date: dateISO,
    //   breadth: 0,          // -100 .. +100
    //   signals: [],         // EquitySignal[]
    //   summary: "…",
    //   generatedBy: "Equity",
    // };
  },
};

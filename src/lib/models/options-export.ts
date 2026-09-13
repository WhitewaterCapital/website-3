// WW-OPTIONS — website handoff contract for the Tradier sandbox options/IV
// read. Mirrors the shape src/lib/whitewatch-data/{tradier-sandbox,options-
// summary}.js actually produce; the site types its read against this, same
// role graph-export.ts plays for WW-Graph.
//
// `dataProvenance` is fixed to "tradier-sandbox-delayed-15min" whenever
// `status` is "ok" or "no_data" (a real fetch happened, even if the IV read
// itself had to abstain) — there is no "synthetic-demo" mode for this
// integration (unlike graph-export.ts's GraphDataProvenance): this module
// either calls the real Tradier sandbox or it doesn't run at all. The
// closest thing to a "not live" state is `status: "not_configured"`, which
// carries no market data whatsoever, real or fake.
//
// NOT A CONVICTION SLOT — see conviction.ts and OptionsPanel's own comment
// for the full reasoning. In short: `atmIv` / `expectedMovePct` are magnitude
// -only (unsigned by construction — a straddle price can't be negative),
// while conviction.ts's ConvictionSlotInput.score is explicitly documented as
// a SIGNED directional/quality read. There is no honest sign to give this
// data, so it is not wired into computeConviction anywhere in this codebase.

export type OptionsStatus =
  | "not_configured" // TRADIER_API_KEY isn't set — no attempt was made
  | "not_applicable" // Tradier lists no options at all for this ticker (normal — most tickers have none)
  | "no_data" // options exist but no usable chain/IV came back this pull
  | "error" // a genuine fetch/auth/network failure
  | "ok"; // a full, usable summary

export type OptionsDataProvenance = "tradier-sandbox-delayed-15min";

export interface OptionsSummary {
  status: OptionsStatus;
  ticker: string;
  asOf: string; // ISO timestamp this summary was generated
  dataProvenance?: OptionsDataProvenance;

  // Present when status is "no_data" or "ok" (a chain was actually fetched).
  expiration?: string; // ISO date, the expiration this summary is based on
  expirationBasis?: "standard-monthly" | "nearest-available";
  contractsCount?: number;

  // Present when status is "ok".
  spot?: number;
  atmStrike?: number;
  atmIv?: number; // decimal, e.g. 0.32 = 32% annualized
  daysToExpiration?: number;
  expectedMovePct?: number; // decimal, 1-SD implied move to expiration
  expectedMoveDollars?: number;
  expectedMoveLow?: number;
  expectedMoveHigh?: number;

  // Present whenever a chain was fetched (status "no_data" or "ok"), since
  // open interest doesn't depend on IV being resolvable.
  putCallOi?: number | null; // null when call OI is 0 (ratio undefined)
  callOi?: number;
  putOi?: number;

  // Human-readable explanation, present on every non-"ok" status.
  reason?: string;

  generatedBy: string; // e.g. "Tradier sandbox (options)"
}

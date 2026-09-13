// WW-OPTIONS — website handoff contract for the Alpha Vantage options/IV
// read. Mirrors the shape src/lib/whitewatch-data/{alphavantage-options,
// options-summary}.js actually produce; the site types its read against
// this, same role graph-export.ts plays for WW-Graph.
//
// FORMERLY Tradier sandbox (see git history for tradier-sandbox.js): the
// fund's owner discovered mid-signup that Tradier's sandbox now requires
// full identity verification (tax ID, government ID) to even get a token —
// a much higher bar than the stale 2014 blog post this platform's earlier
// research had relied on ("no brokerage account required"). Switched to
// Alpha Vantage's free tier instead: no identity verification, at the cost
// of a much tighter request budget (~25/day) AND a genuinely unresolved
// question about whether the options endpoint even works on that free tier
// at all — see alphavantage-options.js's header for the full research
// writeup. `plan_gated` and `rate_limited` below exist specifically because
// that question could not be settled with certainty and this platform's
// honesty convention requires telling a member the TRUTH about which of
// those two very different situations is happening, not a generic "error".
//
// `dataProvenance` is fixed to "alphavantage-historical-options" whenever
// `status` is "ok" or "no_data" (a real fetch happened, even if the IV read
// itself had to abstain) — there is no "synthetic-demo" mode for this
// integration (unlike graph-export.ts's GraphDataProvenance): this module
// either calls the real Alpha Vantage HISTORICAL_OPTIONS endpoint or it
// doesn't run at all. The closest thing to a "not live" state is
// `status: "not_configured"`, which carries no market data whatsoever, real
// or fake.
//
// NOT A CONVICTION SLOT — see conviction.ts and OptionsPanel's own comment
// for the full reasoning. In short: `atmIv` / `expectedMovePct` are magnitude
// -only (unsigned by construction — a straddle price can't be negative),
// while conviction.ts's ConvictionSlotInput.score is explicitly documented as
// a SIGNED directional/quality read. There is no honest sign to give this
// data, so it is not wired into computeConviction anywhere in this codebase.
// This reasoning is about what the NUMBER MEANS, not about which vendor
// supplied it, so it holds unchanged across the Tradier -> Alpha Vantage
// switch.

export type OptionsStatus =
  | "not_configured" // ALPHA_VANTAGE_API_KEY isn't set — no attempt was made
  | "not_applicable" // Alpha Vantage returned a real "success" response with zero contracts for this ticker — the normal case for most tickers (most stocks, nearly all commodities/FX symbols this platform also covers, have no listed equity options)
  | "no_data" // options exist but no usable chain/spot came back this pull
  | "plan_gated" // Alpha Vantage says HISTORICAL_OPTIONS isn't available on this key's plan — retrying will NOT help without upgrading; a genuinely-possible outcome per this integration's own research (see alphavantage-options.js's header) — never shown as a generic "error"
  | "rate_limited" // Alpha Vantage says the free tier's request budget (per-minute and/or the ~25/day cap) is exhausted right now — retrying later may work; DIFFERENT from plan_gated and never collapsed into it
  | "error" // a genuine fetch/timeout/malformed-response failure
  | "ok"; // a full, usable summary

export type OptionsDataProvenance = "alphavantage-historical-options";

export interface OptionsSummary {
  status: OptionsStatus;
  ticker: string;
  asOf: string; // ISO timestamp this summary was generated
  dataProvenance?: OptionsDataProvenance;

  // The trading day Alpha Vantage's own `date` field says this chain
  // reflects — present whenever a chain was actually fetched ("no_data" or
  // "ok"). Deliberately NOT a claimed "X minutes delayed" figure the way
  // the old Tradier integration could quote — see alphavantage-options.js's
  // header for why no equivalently explicit freshness figure could be
  // confirmed for Alpha Vantage's HISTORICAL_OPTIONS endpoint.
  quoteDate?: string;

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

  // Human-readable explanation, present on every non-"ok" status. For
  // "plan_gated"/"rate_limited" this is Alpha Vantage's OWN response text
  // (its "Information"/"Note" field), quoted rather than paraphrased, so a
  // member reading this sees exactly what Alpha Vantage said.
  reason?: string;

  generatedBy: string; // e.g. "Alpha Vantage (options)"
}

// WW-INSIDER — website handoff contract for the SEC EDGAR Form 4 insider-
// activity read. Mirrors the shape src/lib/whitewatch-data/edgar-sources.js
// actually produces; the site types its read against this, same role
// options-export.ts plays for the Tradier options integration and
// weekly-export.ts plays for WW-Weekly.
//
// THREE-WAY DISTINGUISHABLE STATUS (this task's core honesty requirement):
// "no recent insider activity", "ticker not found", and "couldn't reach
// EDGAR" are three different, real answers and must never collapse into one
// generic error. `status` carries that distinction; `transactions` can be a
// real, valid EMPTY array under "ok" (SEC was reached, the ticker resolved,
// there just weren't any Form 4s in the window) — that is NOT the same as
// "unreachable" or "not_found" below, and callers must not treat them alike.
export type InsiderStatus =
  | "not_found" // SEC's own ticker directory has no CIK for this ticker
  | "unreachable" // a real network/HTTP failure talking to SEC — says nothing about the ticker itself
  | "ok"; // SEC was reached and the ticker resolved; transactions may still be []

// SEC's own documented Form 4 transaction codes (Table I/II column 3).
export type InsiderTransactionCode =
  | "P" | "S" | "A" | "D" | "F" | "M" | "G" | "C" | "X" | "W" | "I" | "J" | "K" | "U" | "Z" | string;

export interface InsiderTransaction {
  insiderName: string | null;
  insiderCik: string | null;
  insiderRoles: string[]; // e.g. ["Director"], ["10% owner"], ["Chief Financial Officer"]
  securityTitle: string | null;
  transactionDate: string | null; // YYYY-MM-DD
  transactionCode: InsiderTransactionCode | null;
  transactionCodeLabel: string; // human label, e.g. "Open-market sale"
  shares: number | null;
  pricePerShare: number | null;
  acquiredDisposedCode: "A" | "D" | null;
  sharesOwnedAfter: number | null;
  ownershipType: "D" | "I" | null; // direct / indirect
  derivative: boolean; // true = from the derivativeTable (options, RSUs, etc.), not a plain share transaction
  issuerCik: string | null;
  issuerName: string | null;
  issuerTicker: string | null;
  filingDate: string | null;
  reportDate: string | null;
  accessionNumber: string;
  isAmendment: boolean; // filed as a Form 4/A
  sourceUrl: string; // the real EDGAR Archives directory for this filing — every transaction traces to one
}

// Net insider buy/sell direction over the trailing window. Built ONLY from
// open-market purchases (P) and sales (S) in the non-derivative table — see
// edgar-sources.js's SIGNAL_CODES comment for why grants/awards/exercises/
// gifts/tax-withholding are excluded from the score even though they appear,
// correctly labeled, in `transactions` above.
export interface InsiderSummary {
  windowDays: number;
  signalTransactionCount: number; // how many P/S transactions this read is based on
  buyCount: number;
  sellCount: number;
  buyDollars: number;
  sellDollars: number;
  netDirection: number; // -1 (all selling) .. +1 (all buying), dollar-weighted
  score: number | null; // -100..100, = netDirection * 100; NULL (not 0) when signalTransactionCount is 0
  confidence: number; // 0..1, saturates at CONFIDENCE_SATURATION_COUNT signal transactions
  distinctInsiders: number; // how many different reporting-owner CIKs contributed a signal transaction
}

// Documents the researched 13F institutional-ownership gap directly in the
// API response (not just in code comments) so a member sees the honest
// reason it's absent rather than an unexplained missing feature. See
// edgar-sources.js's header comment for the full research writeup.
export interface ThirteenFGap {
  supported: false;
  reason: string;
}

// Single source of truth for the 13F gap explanation, shared by the route
// (server) and any client fallback that needs to render the same honest
// note when the route itself couldn't be reached at all — see
// edgar-sources.js's header comment for the full research writeup this
// summarizes.
export const THIRTEEN_F_GAP_REASON =
  "SEC does not offer a free, keyless, real-time API to look up '13F institutional ownership by ticker'. " +
  "13F filings are made BY institutions (which securities they hold), not indexed by target ticker: SEC's " +
  "only free structured 13F data is the quarterly bulk 'Form 13F Data Sets' (large ZIP files of flattened " +
  "XML, updated once a quarter, months behind), and would require downloading/parsing that entire dataset " +
  "and cross-referencing every institution's holdings against this ticker's CUSIP -- a batch/offline research " +
  "job, not something a per-request route can honestly do live. Every product that answers '13F by ticker' " +
  "in real time is a paid or scraped aggregation of that same bulk dataset, not a free SEC endpoint. This is " +
  "a stated gap, not a silently-dropped feature.";

export interface InsiderReading {
  status: InsiderStatus;
  ticker: string;
  cik?: string;
  companyName?: string | null;

  windowDays?: number;
  sinceDate?: string; // ISO date, start of the lookback window

  filingsFound?: number; // Form 4/4-A filings SEC listed in the window
  filingsFetched?: number; // how many of those this read actually fetched+parsed
  filingFetchFailures?: number; // individual filing fetches that failed (network-level, not full abstention)
  filingsCappedAt?: number | null; // set when filingsFound exceeded the per-request fetch cap
  windowMayBeIncomplete?: boolean; // true only in the (very unlikely) case documented in edgar-sources.js

  transactions?: InsiderTransaction[];
  summary?: InsiderSummary;

  message?: string; // human-readable explanation — always present on not_found/unreachable

  thirteenF: ThirteenFGap;

  generatedBy: string;
}

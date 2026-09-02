// Core domain types for the club.
// This is the shared vocabulary the whole app is built on.

export type Member = {
  id: string;
  name: string;
  email: string;
  role: "admin" | "member";
  joinedAt: string; // ISO date
};

// Money a member puts in (or takes out, if negative).
// Each contribution buys "units" at the unit value on that date.
export type Contribution = {
  id: string;
  memberId: string;
  date: string; // ISO date
  amountUsd: number; // positive = deposit, negative = withdrawal
  unitsIssued: number; // units bought/redeemed at that day's unit value
  note?: string;
};

// A daily (or intraday) snapshot of the whole account.
// The equity curve and every metric is derived from the history of these.
export type Snapshot = {
  date: string; // ISO date
  totalValueUsd: number; // full account value (positions + cash), incl. contributions
  cashUsd: number; // uninvested cash
  investedUsd: number; // market value of open positions
  unitValueUsd: number; // $/unit — the contribution-neutral performance measure
  spyPrice: number; // SPY close that day, for the benchmark line
};

// An open position. Members-only — never exposed on the public page.
export type Position = {
  symbol: string;
  quantity: number;
  avgCostUsd: number;
  lastPriceUsd: number;
  marketValueUsd: number;
  unrealizedPnlUsd: number;
  openedAt: string; // ISO date
};

// The thesis + status of a trade idea, and the votes on it.
export type ProposalStatus = "open" | "approved" | "rejected" | "executed";

export type Vote = {
  memberId: string;
  value: "yes" | "no";
  at: string; // ISO datetime
};

export type Proposal = {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  targetUsd: number; // how much capital to commit
  thesis: string;
  proposedBy: string; // memberId
  createdAt: string; // ISO datetime
  status: ProposalStatus;
  votes: Vote[];
};

// An executed trade — the audit trail and the raw material for tax lots.
export type Trade = {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  quantity: number;
  priceUsd: number;
  executedAt: string; // ISO datetime
  proposalId?: string; // links back to the idea, if it came from one
};

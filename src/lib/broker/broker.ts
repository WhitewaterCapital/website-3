import type { Position, Snapshot, Trade } from "../types";

// ---------------------------------------------------------------------------
// Broker adapter interface.
//
// The rest of the app only ever talks to a `BrokerAdapter` — never directly to
// Interactive Brokers, Alpaca, or anything else. Swapping brokers = writing one
// new adapter and changing one line in `getBroker()`. That keeps the UI and the
// unit/metrics math totally decoupled from whichever broker you actually use.
// ---------------------------------------------------------------------------

export interface AccountState {
  totalValueUsd: number;
  cashUsd: number;
  investedUsd: number;
  positions: Position[];
}

export interface BrokerAdapter {
  readonly name: string;

  // Live account snapshot: value, cash, and open positions.
  getAccount(): Promise<AccountState>;

  // Recent fills, for the activity feed and tax lots.
  getTrades(): Promise<Trade[]>;

  // Historical account-value points, for the equity curve. Some brokers expose
  // this directly; otherwise the app builds it from stored snapshots instead.
  getHistory?(): Promise<Snapshot[]>;
}

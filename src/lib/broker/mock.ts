import type { AccountState, BrokerAdapter } from "./broker";
import { positions, snapshots, trades } from "../sample-data";
import type { Snapshot, Trade } from "../types";

// A no-network adapter backed by the sample data. This is what runs until
// real IBKR credentials are configured, so the whole app is usable today.
export class MockBroker implements BrokerAdapter {
  readonly name = "Mock (sample data)";

  async getAccount(): Promise<AccountState> {
    const latest = snapshots[snapshots.length - 1];
    return {
      totalValueUsd: latest.totalValueUsd,
      cashUsd: latest.cashUsd,
      investedUsd: latest.investedUsd,
      positions,
    };
  }

  async getTrades(): Promise<Trade[]> {
    return trades;
  }

  async getHistory(): Promise<Snapshot[]> {
    return snapshots;
  }
}

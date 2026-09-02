import type { BrokerAdapter } from "./broker";
import { MockBroker } from "./mock";
import { IbkrBroker } from "./ibkr";

// Single place the whole app gets its broker from.
// Set BROKER=ibkr in the environment once the IBKR adapter is implemented;
// anything else falls back to the sample-data mock.
let cached: BrokerAdapter | null = null;

export function getBroker(): BrokerAdapter {
  if (cached) return cached;
  cached = process.env.BROKER === "ibkr" ? new IbkrBroker() : new MockBroker();
  return cached;
}

export type { BrokerAdapter } from "./broker";

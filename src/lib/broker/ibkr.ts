import type { AccountState, BrokerAdapter } from "./broker";
import type { Snapshot, Trade } from "../types";

// ---------------------------------------------------------------------------
// Interactive Brokers adapter — stub.
//
// IBKR has two main integration paths:
//
//   1. Client Portal Web API (recommended here): a local/remote gateway
//      exposes a REST API at https://localhost:5000/v1/api. You authenticate
//      once via the gateway, then call endpoints like:
//        GET /portfolio/{accountId}/summary   -> value, cash
//        GET /portfolio/{accountId}/positions -> open positions
//        GET /iserver/account/trades          -> recent fills
//      Docs: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
//
//   2. TWS API (ibapi) via a running Trader Workstation / IB Gateway — more
//      powerful, but a socket API that's awkward to call from a web server.
//
// For a Vercel-hosted site, the usual pattern is: run the IBKR Client Portal
// Gateway on a small always-on host (or the machine that has the account),
// expose it privately, and have this adapter call it server-side. Fill in the
// three methods below and set the env vars, then flip getBroker() to use it.
// ---------------------------------------------------------------------------

export class IbkrBroker implements BrokerAdapter {
  readonly name = "Interactive Brokers";

  private baseUrl: string;
  private accountId: string;

  constructor() {
    this.baseUrl = process.env.IBKR_GATEWAY_URL ?? "";
    this.accountId = process.env.IBKR_ACCOUNT_ID ?? "";
  }

  private ensureConfigured() {
    if (!this.baseUrl || !this.accountId) {
      throw new Error(
        "IBKR not configured. Set IBKR_GATEWAY_URL and IBKR_ACCOUNT_ID, run the " +
          "IBKR Client Portal Gateway, and implement the methods in src/lib/broker/ibkr.ts.",
      );
    }
  }

  async getAccount(): Promise<AccountState> {
    this.ensureConfigured();
    // TODO: fetch `${this.baseUrl}/portfolio/${this.accountId}/summary`
    //       and `.../positions`, map into AccountState.
    throw new Error("IbkrBroker.getAccount not implemented yet.");
  }

  async getTrades(): Promise<Trade[]> {
    this.ensureConfigured();
    // TODO: fetch `${this.baseUrl}/iserver/account/trades`, map into Trade[].
    throw new Error("IbkrBroker.getTrades not implemented yet.");
  }

  async getHistory(): Promise<Snapshot[]> {
    // IBKR doesn't hand you a clean equity curve; the app builds one from the
    // snapshots table instead (see the /api/cron/snapshot route).
    return [];
  }
}

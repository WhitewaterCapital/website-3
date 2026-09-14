import type { AccountState, BrokerAdapter } from "./broker";
import type { Position, Snapshot, Trade } from "../types";

// ---------------------------------------------------------------------------
// Interactive Brokers adapter — Client Portal Web API, READ-ONLY.
//
// This talks to a locally-run IBKR Client Portal Gateway, which is the only
// piece of this integration that actually authenticates as you:
//   1. Download & run the gateway: https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/
//      (`bin/run.sh root/conf.yaml` on Mac/Linux). It listens on
//      https://localhost:5000 by default.
//   2. Open https://localhost:5000 in a browser and log in (this is IBKR's own
//      2FA-backed login page — nothing in this codebase touches your IBKR
//      username/password, and nothing here ever will: nothing in this repo
//      should ever collect or transmit your IBKR credentials directly).
//   3. While that browser session (or the gateway process) stays alive, set
//      IBKR_GATEWAY_URL=https://localhost:5000/v1/api and IBKR_ACCOUNT_ID=<your
//      account id, e.g. U1234567> in .env, then set BROKER=ibkr.
//
// The gateway's session expires after ~90 seconds of inactivity unless
// something calls /tickle periodically — IBKR's own docs recommend a
// keep-alive poll (e.g. a small cron hitting /tickle every ~60s) running
// alongside the gateway process. That keep-alive is NOT implemented here
// (it belongs next to the gateway, not inside this Next.js app) — without
// it, calls below will start failing with 401s after the session times out.
//
// Self-signed cert: the gateway ships with a self-signed TLS cert on
// localhost. Node's fetch will reject it by default. For local use against
// your own gateway on your own machine, either install a real cert in the
// gateway's conf.yaml, or run the Next.js process itself with
// NODE_TLS_REJECT_UNAUTHORIZED=0 (acceptable only because the target is your
// own localhost gateway, never appropriate for a public deployment).
//
// SCOPE: this adapter is intentionally read-only — it only ever calls GET
// endpoints (account summary, positions, trade history). It does not place,
// modify, or cancel orders, and no order-entry endpoint is called or should
// be added here.
//
// UNTESTED: none of the sandboxes available while building this had a
// running IBKR Gateway to call, so the requests below are implemented
// against IBKR's documented Client Portal Web API response shapes
// (https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/) but
// have not been exercised against a live gateway. The most likely first
// failure is the self-signed-cert issue above, followed by an
// unauthenticated-session 401 — the error messages below try to say which.
// ---------------------------------------------------------------------------

// --- raw Client Portal Web API response shapes (subset actually used) ------

type CpSummaryField = { amount?: number; currency?: string } | undefined;

type CpSummaryResponse = Record<string, CpSummaryField>;

type CpPosition = {
  conid: number;
  contractDesc?: string;
  ticker?: string;
  position: number;
  mktPrice?: number;
  mktValue?: number;
  avgCost?: number;
  avgPrice?: number;
  unrealizedPnl?: number;
  currency?: string;
};

type CpTrade = {
  execution_id: string;
  symbol?: string;
  side?: string; // "B" | "S" (also seen: "BOT" | "SLD")
  size?: string | number;
  price?: string | number;
  trade_time?: string; // "YYYYMMDD-HH:mm:ss"
  trade_time_r?: number; // epoch millis
  order_ref?: string;
};

type CpAuthStatus = { authenticated?: boolean; connected?: boolean };

export class IbkrBroker implements BrokerAdapter {
  readonly name = "Interactive Brokers";

  private baseUrl: string;
  private accountId: string;

  constructor() {
    // Trim trailing slashes so `${baseUrl}/portfolio/...` never double-slashes.
    this.baseUrl = (process.env.IBKR_GATEWAY_URL ?? "").replace(/\/+$/, "");
    this.accountId = process.env.IBKR_ACCOUNT_ID ?? "";
  }

  private ensureConfigured() {
    if (!this.baseUrl || !this.accountId) {
      throw new Error(
        "IBKR not configured. Set IBKR_GATEWAY_URL (e.g. https://localhost:5000/v1/api) and " +
          "IBKR_ACCOUNT_ID (e.g. U1234567) in .env, and make sure the IBKR Client Portal Gateway " +
          "is running and you're logged in at its URL in a browser.",
      );
    }
  }

  // Thin fetch wrapper: turns network/HTTP failures into one consistent,
  // actionable error instead of a raw fetch exception, since the two most
  // likely failure modes here (self-signed cert rejected, session not
  // authenticated) are both easy to misdiagnose from a bare fetch error.
  private async request<T>(path: string, init?: RequestInit): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${this.baseUrl}${path}`, {
        ...init,
        headers: { Accept: "application/json", ...(init?.headers ?? {}) },
        cache: "no-store",
      });
    } catch (err) {
      throw new Error(
        `IBKR gateway request to ${path} failed before getting a response (is the gateway running at ` +
          `${this.baseUrl}? is its self-signed cert being rejected — see the note at the top of ibkr.ts?): ` +
          `${(err as Error).message}`,
      );
    }
    if (res.status === 401 || res.status === 403) {
      throw new Error(
        `IBKR gateway returned ${res.status} for ${path} — the gateway session likely isn't authenticated. ` +
          "Log in at the gateway's URL in a browser (and make sure something is keeping the session alive " +
          "with periodic /tickle calls — see the note at the top of ibkr.ts).",
      );
    }
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`IBKR gateway request to ${path} failed: ${res.status} ${res.statusText} ${body}`.trim());
    }
    return (await res.json()) as T;
  }

  private async checkAuthenticated(): Promise<void> {
    const status = await this.request<CpAuthStatus>("/iserver/auth/status", { method: "POST" });
    if (!status.authenticated) {
      throw new Error(
        "IBKR gateway session is not authenticated. Open the gateway's URL " +
          `(${this.baseUrl.replace(/\/v1\/api$/, "")}) in a browser and log in, then try again.`,
      );
    }
  }

  async getAccount(): Promise<AccountState> {
    this.ensureConfigured();
    await this.checkAuthenticated();

    const summary = await this.request<CpSummaryResponse>(`/portfolio/${this.accountId}/summary`);
    const totalValueUsd = summary.netliquidation?.amount ?? 0;
    const cashUsd = summary.totalcashvalue?.amount ?? 0;
    // grosspositionvalue is IBKR's own field for "market value of open
    // positions" — falls back to totalValue - cash if it's ever absent.
    const investedUsd = summary.grosspositionvalue?.amount ?? Math.max(0, totalValueUsd - cashUsd);

    // /portfolio/{accountId}/positions/{pageId} is paginated, ~100/page;
    // IBKR's docs say to keep requesting pageId+1 while a page comes back
    // full. Real accounts rarely exceed one page, but this doesn't assume that.
    const allPositions: CpPosition[] = [];
    for (let pageId = 0; ; pageId++) {
      const page = await this.request<CpPosition[]>(`/portfolio/${this.accountId}/positions/${pageId}`);
      allPositions.push(...page);
      if (page.length < 100) break;
    }

    // IBKR's positions/summary endpoints don't expose a position's original
    // open date at all — best-effort recovery: use the earliest trade this
    // adapter can see (getTrades()'s own window; IBKR's trade-history
    // endpoint only covers a recent window, commonly the last several days)
    // for that symbol as a stand-in. For a position opened before that
    // window, this will understate how long it's been held rather than
    // fabricate a precise date — see daysInTrade in src/lib/watch/checks.ts,
    // which is the one place this matters. The app's own daily snapshots
    // table (see MockBroker/getHistory's comment) is the more reliable
    // long-run source of truth once it has history to draw on.
    let earliestTradeBySymbol = new Map<string, string>();
    try {
      const trades = await this.getTrades();
      earliestTradeBySymbol = trades.reduce((acc, t) => {
        const existing = acc.get(t.symbol);
        if (!existing || t.executedAt < existing) acc.set(t.symbol, t.executedAt);
        return acc;
      }, new Map<string, string>());
    } catch {
      // Trade history is a best-effort enrichment for openedAt only — a
      // failure here shouldn't take down the whole account fetch.
    }

    const nowIso = new Date().toISOString().slice(0, 10);
    const positions: Position[] = allPositions
      .filter((p) => p.position !== 0)
      .map((p) => {
        const symbol = p.ticker ?? p.contractDesc ?? String(p.conid);
        const quantity = p.position;
        const avgCostUsd = p.avgCost ?? p.avgPrice ?? 0;
        const lastPriceUsd = p.mktPrice ?? 0;
        const marketValueUsd = p.mktValue ?? quantity * lastPriceUsd;
        const unrealizedPnlUsd = p.unrealizedPnl ?? marketValueUsd - quantity * avgCostUsd;
        return {
          symbol,
          quantity,
          avgCostUsd,
          lastPriceUsd,
          marketValueUsd,
          unrealizedPnlUsd,
          openedAt: earliestTradeBySymbol.get(symbol)?.slice(0, 10) ?? nowIso,
        };
      });

    return { totalValueUsd, cashUsd, investedUsd, positions };
  }

  async getTrades(): Promise<Trade[]> {
    this.ensureConfigured();
    await this.checkAuthenticated();

    const raw = await this.request<CpTrade[]>("/iserver/account/trades");
    return raw.map((t) => ({
      id: t.execution_id,
      symbol: t.symbol ?? "",
      side: normalizeSide(t.side),
      quantity: Math.abs(Number(t.size ?? 0)),
      priceUsd: Number(t.price ?? 0),
      executedAt: parseIbkrTradeTime(t.trade_time_r, t.trade_time),
      // [Added 2026-09-14] IBKR's own order_ref is the real, durable place to
      // record which strategy an order belongs to — set it yourself at
      // order-entry time (Client Portal / TWS both let you set a custom
      // order reference string) and it flows straight through here into the
      // Allocator Ribbon's strategy-level P&L (src/lib/strategy-pnl.ts).
      // Blank/absent order_ref becomes undefined, never a fabricated guess.
      strategyTag: t.order_ref?.trim() || undefined,
    }));
  }

  async getHistory(): Promise<Snapshot[]> {
    // IBKR doesn't hand you a clean equity curve; the app builds one from the
    // snapshots table instead (see the /api/cron/snapshot route).
    return [];
  }
}

function normalizeSide(raw: string | undefined): "buy" | "sell" {
  const s = (raw ?? "").toUpperCase();
  return s === "S" || s === "SLD" || s === "SELL" ? "sell" : "buy";
}

// IBKR gives either an epoch-millis field (trade_time_r, preferred when
// present) or a "YYYYMMDD-HH:mm:ss" string (trade_time, in the account's
// configured timezone — treated here as UTC since the gateway config
// controls that and this app has no reliable way to read it back).
function parseIbkrTradeTime(epochMs: number | undefined, raw: string | undefined): string {
  if (epochMs) return new Date(epochMs).toISOString();
  if (raw && /^\d{8}-\d{2}:\d{2}:\d{2}$/.test(raw)) {
    const y = raw.slice(0, 4);
    const mo = raw.slice(4, 6);
    const d = raw.slice(6, 8);
    const time = raw.slice(9);
    return new Date(`${y}-${mo}-${d}T${time}Z`).toISOString();
  }
  return new Date().toISOString();
}

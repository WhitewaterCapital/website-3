import type { Trade } from "./types";

// ═══════════════════════════════════════════════════════════════════════════
// Strategy-level realized P&L — the Allocator Ribbon's real data source.
//
// BACKGROUND: the plan's own Roadblocks log used to say "Allocator Ribbon
// needs a real data source I don't have — if Whitewater has actual
// strategy-level allocation/P&L history anywhere, tell me." The answer
// (2026-09-14): trading through IBKR, tag each order's own reference field
// with a strategy name at order-entry time (Client Portal / TWS both support
// a custom order reference string) — IBKR's own order records become the
// real, durable ledger, with no separate file for this app to keep in sync
// or risk drifting from reality. `IbkrBroker.getTrades()` already surfaces
// that field as `Trade.strategyTag` (src/lib/broker/ibkr.ts). This module
// turns a real trade list into real per-strategy P&L.
//
// WHAT THIS DOES: FIFO-matches buys against sells, PER (strategyTag, symbol)
// bucket, to compute REALIZED P&L only — profit/loss that has actually been
// locked in by closing part or all of a position. This is real, exact
// arithmetic over whatever real trades exist; nothing here is estimated or
// fitted.
//
// WHAT THIS DELIBERATELY DOES NOT DO: it does NOT compute unrealized P&L per
// strategy. Doing that correctly needs a live, tag-aware open-lot ledger
// (which lots, at which cost, are still open per strategy) cross-referenced
// against current market prices — a materially bigger build than this pass,
// and one this session has no live trading data to validate against anyway
// (no capital has traded through IBKR yet). Gross exposure by tag (net open
// quantity × trade cost, not marked to market) is shown instead, clearly
// labeled as cost-basis exposure, not current market value — never
// conflated with the real unrealized P&L on `AccountState.positions`, which
// still comes from the broker directly and is unaffected by any of this.
//
// UNTAGGED TRADES: a trade with no `strategyTag` (the honest default until
// orders are actually tagged) lands in an explicit "Untagged" bucket, never
// silently dropped or guessed into an existing strategy.
// ═══════════════════════════════════════════════════════════════════════════

export const UNTAGGED = "Untagged";

export type StrategyPnlRow = {
  strategyTag: string; // UNTAGGED for trades with no tag set
  tradeCount: number;
  realizedPnlUsd: number; // exact, FIFO-matched, real
  grossBoughtUsd: number;
  grossSoldUsd: number;
  openCostBasisUsd: number; // sum of (net open qty * avg remaining cost) across symbols — cost basis, NOT marked to market
  symbols: string[]; // symbols this tag has ever traded, for context
};

type Lot = { qty: number; costUsd: number }; // one FIFO lot: quantity and total cost (not per-share)

function fifoRealize(trades: Trade[]): { realizedPnlUsd: number; openCostBasisUsd: number } {
  // Chronological order matters for FIFO — never assume caller pre-sorted.
  const sorted = [...trades].sort((a, b) => a.executedAt.localeCompare(b.executedAt));
  const lots: Lot[] = [];
  let realizedPnlUsd = 0;

  for (const t of sorted) {
    if (t.side === "buy") {
      lots.push({ qty: t.quantity, costUsd: t.quantity * t.priceUsd });
      continue;
    }
    // sell: consume oldest lots first
    let remaining = t.quantity;
    const saleProceedsPerShare = t.priceUsd;
    while (remaining > 0 && lots.length > 0) {
      const lot = lots[0];
      const take = Math.min(remaining, lot.qty);
      const costPerShare = lot.costUsd / lot.qty;
      realizedPnlUsd += take * (saleProceedsPerShare - costPerShare);
      lot.qty -= take;
      lot.costUsd -= take * costPerShare;
      remaining -= take;
      if (lot.qty <= 1e-9) lots.shift();
    }
    // A sell exceeding all known lots (short, or a trade history that starts
    // mid-position) leaves `remaining` > 0 here — silently ignored rather
    // than guessed at, since this module only ever sees the trades it's
    // given; it doesn't claim P&L on a lot it never saw opened.
  }

  const openCostBasisUsd = lots.reduce((s, l) => s + l.costUsd, 0);
  return { realizedPnlUsd, openCostBasisUsd };
}

export function computeStrategyPnl(trades: Trade[]): StrategyPnlRow[] {
  const byTag = new Map<string, Trade[]>();
  for (const t of trades) {
    const tag = t.strategyTag?.trim() || UNTAGGED;
    if (!byTag.has(tag)) byTag.set(tag, []);
    byTag.get(tag)!.push(t);
  }

  const rows: StrategyPnlRow[] = [];
  for (const [tag, tagTrades] of byTag) {
    const bySymbol = new Map<string, Trade[]>();
    for (const t of tagTrades) {
      if (!bySymbol.has(t.symbol)) bySymbol.set(t.symbol, []);
      bySymbol.get(t.symbol)!.push(t);
    }

    let realizedPnlUsd = 0;
    let openCostBasisUsd = 0;
    for (const symbolTrades of bySymbol.values()) {
      const r = fifoRealize(symbolTrades);
      realizedPnlUsd += r.realizedPnlUsd;
      openCostBasisUsd += r.openCostBasisUsd;
    }

    const grossBoughtUsd = tagTrades.filter((t) => t.side === "buy").reduce((s, t) => s + t.quantity * t.priceUsd, 0);
    const grossSoldUsd = tagTrades.filter((t) => t.side === "sell").reduce((s, t) => s + t.quantity * t.priceUsd, 0);

    rows.push({
      strategyTag: tag,
      tradeCount: tagTrades.length,
      realizedPnlUsd,
      grossBoughtUsd,
      grossSoldUsd,
      openCostBasisUsd,
      symbols: [...bySymbol.keys()].sort(),
    });
  }

  // Untagged last regardless of size — it's a "needs attention" bucket, not
  // a strategy to rank alongside real ones.
  return rows.sort((a, b) => {
    if (a.strategyTag === UNTAGGED) return 1;
    if (b.strategyTag === UNTAGGED) return -1;
    return b.realizedPnlUsd - a.realizedPnlUsd;
  });
}

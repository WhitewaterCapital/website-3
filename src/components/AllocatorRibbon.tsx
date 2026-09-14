import { Card, Badge } from "@/components/ui";
import { computeStrategyPnl, UNTAGGED, type StrategyPnlRow } from "@/lib/strategy-pnl";
import type { Trade } from "@/lib/types";
import { usd } from "@/lib/format";

// ═══════════════════════════════════════════════════════════════════════════
// Allocator Ribbon — REBUILT FOR REAL, 2026-09-14 (see PLATFORM_REBUILD_PLAN.md).
//
// The previous AllocatorRibbon (removed 2026-09-13, then deleted by you) was
// 100% fabricated budgets and utility scores with no real seam behind it.
// This one is real, real-yet-currently-empty until live trading through IBKR
// starts: it computes exact, FIFO-matched realized P&L per strategy tag from
// `Trade.strategyTag` (see src/lib/strategy-pnl.ts's own header for the full
// method — sourced from IBKR's own order reference field, no separate ledger
// to maintain).
//
// DO NOT CONFUSE THIS WITH AllocatorPanel (also on /dashboard): AllocatorPanel
// shows WW-ALLOC's forward-looking budget RECOMMENDATION (how much capital
// SHOULD go where, and why, per the real quant-infra/alloc engine). This
// component shows the retrospective, realized RESULT of actual trades once
// they've happened — a completely different, complementary real number, not
// a restatement of the same one.
// ═══════════════════════════════════════════════════════════════════════════

export function AllocatorRibbon({ trades, brokerName }: { trades: Trade[]; brokerName: string }) {
  const rows = computeStrategyPnl(trades);
  const hasAnyTagged = rows.some((r) => r.strategyTag !== UNTAGGED);

  return (
    <Card
      title="Allocator Ribbon — realized P&L by strategy"
      action={<Badge tone={trades.length > 0 ? "up" : "neutral"}>{brokerName}</Badge>}
    >
      {trades.length === 0 ? (
        <div>
          <p className="eyebrow">No trade history yet</p>
          <p className="mt-2 text-sm text-foreground/80">
            Real, not broken — {brokerName} has no trades to read yet. This fills in the moment real
            fills exist.
          </p>
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="pb-2 font-medium">Strategy tag</th>
                  <th className="pb-2 text-right font-medium">Realized P&amp;L</th>
                  <th className="pb-2 text-right font-medium">Trades</th>
                  <th className="pb-2 text-right font-medium">Open cost basis</th>
                  <th className="pb-2 font-medium">Symbols</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <RibbonRow key={r.strategyTag} r={r} />
                ))}
              </tbody>
            </table>
          </div>
          {!hasAnyTagged && (
            <p className="mt-3 text-xs text-muted">
              Every trade above is Untagged — set a strategy name in the order reference field when
              you place each order in IBKR (Client Portal or TWS both support this) and it flows
              straight through here automatically. Nothing here is guessed into a strategy on your
              behalf.
            </p>
          )}
          <p className="mt-3 text-[11px] text-muted">
            Realized P&amp;L is exact FIFO-matched profit/loss on trades that have actually closed —
            not an estimate. Open cost basis is what&apos;s still committed at cost, not marked to
            market (see current unrealized P&amp;L on the Holdings table above for that). This is a
            retrospective read on actual results, not the Allocator&apos;s forward-looking budget
            recommendation above.
          </p>
        </>
      )}
    </Card>
  );
}

function RibbonRow({ r }: { r: StrategyPnlRow }) {
  const isUntagged = r.strategyTag === UNTAGGED;
  return (
    <tr className="border-t border-hairline">
      <td className="py-2 font-medium">
        {isUntagged ? <span className="text-muted">{UNTAGGED}</span> : r.strategyTag}
      </td>
      <td
        className={`py-2 text-right tabular-nums ${
          r.realizedPnlUsd > 0 ? "text-emerald-500" : r.realizedPnlUsd < 0 ? "text-rose-500" : "text-muted"
        }`}
      >
        {r.realizedPnlUsd !== 0 ? (r.realizedPnlUsd > 0 ? "+" : "") + usd(r.realizedPnlUsd) : usd(0)}
      </td>
      <td className="py-2 text-right tabular-nums">{r.tradeCount}</td>
      <td className="py-2 text-right tabular-nums text-muted">{usd(r.openCostBasisUsd)}</td>
      <td className="py-2 text-xs text-muted">{r.symbols.join(", ")}</td>
    </tr>
  );
}

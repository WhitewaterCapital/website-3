import { ModuleNav } from "@/components/ModuleNav";
import { Card, Badge } from "@/components/ui";
import { smartMoneyMomentum, SMART_MONEY_UNIVERSE } from "@/lib/models/impl/smart-money-momentum";
import type { EquityReading, EquitySignal } from "@/lib/models/types";

// Smart Money Momentum — PLATFORM_REBUILD_PLAN.md priority #11, the one new
// model this pass added. Server-renders smartMoneyMomentum.read() directly
// (same pattern WeeklyPage/IntraExitusPage use for their own real-data
// reads) rather than leaving this newly-registered EquityModel with no UI
// consumer at all, the way the pre-existing `equity.ts` model still has.
export const dynamic = "force-dynamic";

export default async function SmartMoneyPage() {
  const dateISO = new Date().toISOString().slice(0, 10);
  const data = await smartMoneyMomentum.read(dateISO);

  return (
    <div>
      <ModuleNav crumb="Smart Money Momentum" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Smart Money Momentum</p>
          <span className="font-mono text-xs text-muted">insider net-buying × momentum beta</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Who the insiders and the tape agree on.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          A cross-sectional screen over a fixed {SMART_MONEY_UNIVERSE.length}-name universe (
          {SMART_MONEY_UNIVERSE.join(", ")}), combining WW-Insider&apos;s real SEC EDGAR net
          buy/sell direction with WW-Factor&apos;s real momentum factor beta. A research read, not
          a verdict — never fed into any single-name composite conviction score.
        </p>

        <div className="mt-8">
          <SmartMoneyTable data={data} />
        </div>
      </main>
    </div>
  );
}

function SmartMoneyTable({ data }: { data: EquityReading }) {
  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Research read</Badge>
          <span className="text-xs text-muted">Cross-sectional rank signal · not investment advice</span>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">{data.summary}</p>
      </div>

      {data.signals.length === 0 ? (
        <Card>
          <p className="eyebrow">No names ranked this read</p>
          <p className="mt-2 text-sm text-foreground/80">
            Every name in the universe is missing at least one of the two real inputs this screen
            needs — see the coverage note above for exactly which. This is the expected state
            until WW-Factor&apos;s export covers real tickers (it&apos;s currently synthetic-demo
            only — see <code>PLATFORM_REBUILD_PLAN.md</code>&apos;s Roadblocks) — not a fabricated
            empty table.
          </p>
        </Card>
      ) : (
        <Card title="Ranked — highest combined tilt first">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="pb-2 font-medium">Symbol</th>
                  <th className="pb-2 text-right font-medium">Combined tilt</th>
                  <th className="pb-2 font-medium">Grounding</th>
                </tr>
              </thead>
              <tbody>
                {data.signals.map((s) => (
                  <SignalRow key={s.symbol} s={s} />
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[11px] text-muted">
            Combined tilt is a stated simple average of two already-scaled real reads (momentum
            beta × 40, insider net-direction score), not a fitted or backtested weighting — read
            it as an ordering, not a price target or a standalone buy/sell call.
          </p>
        </Card>
      )}

      <p className="text-[11px] text-muted">Overall breadth across ranked names: {data.breadth > 0 ? "+" : ""}{data.breadth}.</p>
    </div>
  );
}

function SignalRow({ s }: { s: EquitySignal }) {
  return (
    <tr className="border-t border-hairline">
      <td className="py-2 font-medium">{s.symbol}</td>
      <td className="py-2 text-right tabular-nums">
        {s.score > 0 ? "+" : ""}
        {s.score}
      </td>
      <td className="py-2 text-xs text-muted">{s.note}</td>
    </tr>
  );
}

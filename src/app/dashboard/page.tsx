import Link from "next/link";
import { ModuleNav } from "@/components/ModuleNav";
import { LineChart } from "@/components/LineChart";
import { ExposureGauge } from "@/components/ExposureGauge";
import { AllocatorPanel } from "@/components/AllocatorPanel";
import { DisagreementPanel } from "@/components/DisagreementPanel";
import { Stat, Card } from "@/components/ui";
import { getBroker } from "@/lib/broker";
import { getAllocExport } from "@/lib/alloc";
import { getStateExport } from "@/lib/state";
import { snapshots } from "@/lib/sample-data";
import { computeMetrics } from "@/lib/metrics";
import { usd, pct, shortDate, num } from "@/lib/format";

// THE DESK — the members launcher. Four modules up top (each a shell you fill
// with its own algo backend), portfolio/holdings below.
const MODULES = [
  {
    href: "/sentiment",
    name: "Sentimentum",
    latin: "the regime lens",
    blurb: "Top-down macro and cross-sector read.",
  },
  {
    href: "/stress-test",
    name: "Strictus Testum",
    latin: "the rigorous test",
    blurb: "Pressure-test a trade — the adversarial read.",
  },
  {
    href: "/nova",
    name: "Nova",
    latin: "new things",
    blurb: "Market news and catalysts that can move the book.",
  },
  {
    href: "/intra-exitus",
    name: "Intra / Exitus",
    latin: "enter · exit",
    blurb: "Entry and exit levels — where to get in, where to get out.",
  },
  {
    href: "/watch",
    name: "WW-Watch",
    latin: "keep vigil",
    blurb: "Daily position monitor — invalidations, urgency, and the audit trail.",
  },
  {
    href: "/weekly",
    name: "WW-Weekly",
    latin: "the weekly rank",
    blurb: "Ranked weekly cross-section — who's expected to lead, who's expected to lag.",
  },
  {
    href: "/war-map",
    name: "WHITEWATCH",
    latin: "watch abroad",
    blurb: "Geopolitical conflict monitoring — live threat map, intel feed, and macro indicators. Not a pricing model — external context for the book.",
  },
];

export default async function DeskPage() {
  const broker = getBroker();
  const account = await broker.getAccount();
  const m = computeMetrics(snapshots);
  const labels = snapshots.map((s) => shortDate(s.date));
  const alloc = await getAllocExport();
  const state = await getStateExport();

  return (
    <div>
      <ModuleNav />
      <main className="mx-auto max-w-5xl px-6 py-10">
        <p className="rise rise-1 font-mono text-sm text-accent">// The Desk</p>
        <h1 className="rise rise-2 display mt-2 text-4xl sm:text-5xl">
          Good to see you.
        </h1>

        {/* Module launcher */}
        <div className="mt-8 flex flex-wrap justify-end gap-x-6 gap-y-1">
          <Link
            href="/performance"
            className="text-xs uppercase tracking-[0.12em] text-muted hover:text-foreground"
          >
            Performance attribution →
          </Link>
          <Link
            href="/visuals"
            className="text-xs uppercase tracking-[0.12em] text-muted hover:text-foreground"
          >
            Visuals →
          </Link>
          <Link
            href="/models"
            className="text-xs uppercase tracking-[0.12em] text-muted hover:text-foreground"
          >
            Model registry →
          </Link>
        </div>
        <div className="mt-3 grid gap-px border border-hairline bg-hairline sm:grid-cols-2">
          {MODULES.map((mod, i) => (
            <Link
              key={mod.href}
              href={mod.href}
              className={`rise rise-${Math.min(i + 1, 4)} group relative bg-background p-7 transition hover:bg-paper`}
            >
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-xl font-semibold">{mod.name}</h2>
                  <p className="mt-0.5 font-mono text-xs text-muted">{mod.latin}</p>
                </div>
                <span className="text-lg text-muted transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5">
                  ↘
                </span>
              </div>
              <p className="mt-4 text-sm text-foreground/80">{mod.blurb}</p>
              <span className="mt-4 inline-block text-[11px] uppercase tracking-wide text-muted">
                Build in progress
              </span>
            </Link>
          ))}
        </div>

        {/* Portfolio — the specifics */}
        <section className="mt-14">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="eyebrow">Portfolio</h2>
            <span className="text-xs text-muted">
              Source: {broker.name} · synced just now
            </span>
          </div>

          <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
            <Stat label="Account Value" value={usd(account.totalValueUsd)} />
            <Stat
              label="Total Return"
              value={pct(m.portReturn)}
              tone={m.portReturn >= 0 ? "up" : "down"}
              sub={`vs SPY ${pct(m.alpha)}`}
            />
            <Stat
              label="Cash"
              value={usd(account.cashUsd)}
              sub={`${m.exposure.cashPct.toFixed(0)}% of pool`}
            />
            <Stat label="Sharpe" value={num(m.sharpe, 2)} sub={`vol ${(m.volatility * 100).toFixed(0)}%`} />
          </div>

          <div className="mt-6 grid gap-6 lg:grid-cols-3">
            <div className="lg:col-span-2">
              <Card title="Cumulative return — us vs SPY">
                <LineChart
                  labels={labels}
                  yFormat={(v) => `${v >= 0 ? "+" : ""}${v.toFixed(0)}%`}
                  yAxisLabel="Cumulative return since inception (%)"
                  asOf={m.latest.date}
                  series={[
                    { values: m.portIndexed.map((v) => v - 100), color: "currentColor", label: "Us" },
                    { values: m.spyIndexed.map((v) => v - 100), color: "#9ca3af", label: "SPY" },
                  ]}
                />
              </Card>
            </div>
            <Card title="Exposure">
              <div className="flex h-full items-center justify-center py-4">
                <ExposureGauge investedPct={m.exposure.investedPct} asOf={m.latest.date} />
              </div>
            </Card>
          </div>

          <div className="mt-6">
            <Card
              title="Holdings"
              action={
                <Link href="/proposals" className="text-xs text-accent hover:underline">
                  Proposals →
                </Link>
              }
            >
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="pb-2 font-medium">Symbol</th>
                    <th className="pb-2 text-right font-medium">Value</th>
                    <th className="pb-2 text-right font-medium">P&amp;L</th>
                  </tr>
                </thead>
                <tbody>
                  {account.positions.map((p) => (
                    <tr key={p.symbol} className="border-t border-hairline">
                      <td className="py-2 font-medium">
                        {p.symbol}
                        <span className="ml-2 text-xs text-muted">{p.quantity} sh</span>
                      </td>
                      <td className="py-2 text-right tabular-nums">{usd(p.marketValueUsd)}</td>
                      <td className={`py-2 text-right tabular-nums ${p.unrealizedPnlUsd >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                        {p.unrealizedPnlUsd >= 0 ? "+" : ""}
                        {usd(p.unrealizedPnlUsd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          </div>
        </section>

        {/* Capital allocator — IMP-05 — and model disagreement — IMP-16 */}
        <section className="mt-14">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="eyebrow">Allocator &amp; disagreement</h2>
            <span className="text-xs text-muted">Why capital moved this week, and where models split.</span>
          </div>
          <div className="space-y-6">
            <AllocatorPanel alloc={alloc} state={state} />
            <DisagreementPanel />
          </div>
        </section>
      </main>
    </div>
  );
}

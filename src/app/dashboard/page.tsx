import Link from "next/link";
import { ModuleNav } from "@/components/ModuleNav";
import { LineChart } from "@/components/LineChart";
import { ExposureGauge } from "@/components/ExposureGauge";
import { AllocatorPanel } from "@/components/AllocatorPanel";
import { AllocatorRibbon } from "@/components/AllocatorRibbon";
import { DisagreementPanel } from "@/components/DisagreementPanel";
import { TickerHubClient } from "@/components/TickerHubClient";
import { StressTestClient } from "@/components/StressTestClient";
import { Stat, Card, Tile, LiveDot } from "@/components/ui";
import { getBroker } from "@/lib/broker";
import { getAllocExport } from "@/lib/alloc";
import { getStateExport } from "@/lib/state";
import { getMacroExport } from "@/lib/aurora";
import { getFactorExport } from "@/lib/factor";
import { getEquityExport } from "@/lib/incepta";
import { getIntraExitusExport } from "@/lib/intra-exitus";
import { snapshots } from "@/lib/sample-data";
import { computeMetrics } from "@/lib/metrics";
import { usd, pct, shortDate, num, daysSince } from "@/lib/format";

// THE DESK — redesigned 2026-09-13 into ONE consolidated live dashboard, per
// direct user feedback that the previous version ("Search any ticker, then
// click into six separate pages") felt scattered and looked "ai and
// childish." This page now does three things in one place, top to bottom:
//   1. A "Live models" strip — every real data seam this app has
//      (Distresse, Intra/Exitus, Aurora macro, Incepta equity, WW-Factor),
//      fetched here server-side and shown with an honest live/stale/
//      synthetic-demo status, not just a link to go find out elsewhere.
//   2. "Run a check" — the Stress Test idea form (ticker, instrument,
//      TIMEFRAME, catalyst, thesis) embedded directly, so a live model run
//      doesn't require leaving the dashboard. Same component as /stress-test.
//   3. Portfolio, allocator, and disagreement — unchanged data, restyled.
// The other modules (Sentiment, News, Position Monitor, Weekly Ranking,
// WHITEWATCH) are still one click away via the compact nav strip below the
// hero — full pages for the deeper per-module work, not duplicated here.
const MODULE_LINKS = [
  { href: "/sentiment", name: "Sentiment", blurb: "Macro + equity read" },
  { href: "/nova", name: "News", blurb: "Catalysts & headlines" },
  { href: "/intra-exitus", name: "Entry & Exit", blurb: "Entry/exit levels" },
  { href: "/watch", name: "Position Monitor", blurb: "Invalidations & audit trail" },
  { href: "/weekly", name: "Weekly Ranking", blurb: "Cross-sectional rank" },
  { href: "/smart-money", name: "Smart Money Momentum", blurb: "Insider buying × momentum beta" },
  { href: "/earnings", name: "Earnings Move", blurb: "Upcoming prints × pre-print positioning" },
  { href: "/kalman", name: "Kalman Pairs", blurb: "Self-tuning cointegration / stat-arb" },
  { href: "/war-map", name: "WHITEWATCH", blurb: "Geopolitical conflict monitor" },
  { href: "/visuals", name: "Visuals", blurb: "Dislocation field & chaos ribbon" },
  { href: "/models", name: "Model registry", blurb: "Every model, one page" },
  { href: "/performance", name: "Performance", blurb: "Attribution" },
  { href: "/trade-ideas", name: "Trade Ideas", blurb: "Weekly + Smart Money + Earnings, unioned" },
];

export default async function DeskPage() {
  const broker = getBroker();
  const [account, trades, m_alloc, m_state, macro, factor, equity, intra] = await Promise.all([
    broker.getAccount(),
    broker.getTrades(),
    getAllocExport(),
    getStateExport(),
    getMacroExport(),
    getFactorExport(),
    getEquityExport(),
    getIntraExitusExport(),
  ]);
  const m = computeMetrics(snapshots);
  const labels = snapshots.map((s) => shortDate(s.date));

  return (
    <div>
      <ModuleNav />
      <main className="mx-auto max-w-6xl px-6 py-10">
        <p className="rise rise-1 font-mono text-sm text-accent">// The Desk</p>
        <h1 className="rise rise-2 display mt-2 text-4xl sm:text-5xl">
          One dashboard. Every model, live.
        </h1>
        <p className="rise rise-2 mt-3 max-w-2xl text-sm text-foreground/80 sm:text-base">
          Search any ticker below to run every model that applies to it, or scroll down to check
          what&apos;s live right now and run a fresh stress test without leaving this page.
        </p>

        <div className="rise rise-3 mt-8">
          <TickerHubClient />
        </div>

        {/* Live models strip — real data seams, fetched here, honestly labeled */}
        <section className="mt-14">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="eyebrow">Live models</h2>
            <span className="text-xs text-muted">What&apos;s actually live right now, not just what&apos;s built.</span>
          </div>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            <Tile
              eyebrow="Evaluator"
              title="Distresse"
              href="/stress-test"
              status={<LiveDot label="Live" />}
            >
              Adversarial stress test — 6 real dimensions, computed on demand for any ticker.
            </Tile>
            <Tile
              eyebrow="Levels"
              title="Intra / Exitus"
              href="/intra-exitus"
              status={
                intra ? (
                  <LiveDot stale={daysSince(intra.as_of) > 3} label={daysSince(intra.as_of) > 3 ? "Stale" : "Synced"} />
                ) : (
                  <LiveDot stale label="Not synced" />
                )
              }
            >
              {intra
                ? `${intra.plans.length} tickers, as of ${intra.as_of} (${intra.plans.filter((p) => p.confidence === "actionable").length} actionable)`
                : "No entry/exit export yet — run the engine's export step."}
            </Tile>
            <Tile
              eyebrow="Macro"
              title="Aurora"
              href="/sentiment"
              status={macro ? <LiveDot stale={daysSince(macro.as_of) > 7} label="Synced" /> : <LiveDot stale label="Not synced" />}
            >
              {macro
                ? `${macro.scenarios.length} scenarios modeled, as of ${macro.as_of}`
                : "No macro export yet."}
            </Tile>
            <Tile
              eyebrow="Equity"
              title="Incepta"
              href="/hub"
              status={equity ? <LiveDot stale={daysSince(equity.as_of) > 7} label="Synced" /> : <LiveDot stale label="Not synced" />}
            >
              {equity ? `${equity.universe.length} names covered, as of ${equity.as_of}` : "No equity export yet."}
            </Tile>
            <Tile
              eyebrow="Risk context"
              title="WW-Factor"
              href="/models"
              status={
                factor ? (
                  <LiveDot stale={factor.data_provenance !== "live"} label={factor.data_provenance === "live" ? "Live" : "Synthetic-demo"} />
                ) : (
                  <LiveDot stale label="Not synced" />
                )
              }
            >
              {factor
                ? `${factor.universe.length} names, ${factor.factors.length} factors, as of ${factor.as_of}`
                : "No factor export yet."}
            </Tile>
          </div>
        </section>

        {/* Run a check — the Stress Test engine, embedded directly */}
        <section className="mt-14">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="eyebrow">Run a check</h2>
            <span className="text-xs text-muted">
              Ticker, instrument, timeframe, and catalyst — same engine as{" "}
              <Link href="/stress-test" className="text-accent hover:underline">
                Stress Test
              </Link>
              .
            </span>
          </div>
          <StressTestClient />
        </section>

        {/* Compact module nav — one line per module, not a giant card grid */}
        <section className="mt-14">
          <h2 className="eyebrow mb-3">More modules</h2>
          <div className="grid grid-cols-1 gap-px border border-hairline bg-hairline sm:grid-cols-3">
            {MODULE_LINKS.map((mod) => (
              <Link
                key={mod.href}
                href={mod.href}
                className="group flex items-center justify-between gap-3 bg-background px-4 py-3 transition hover:bg-paper"
              >
                <span>
                  <span className="text-sm font-medium text-foreground">{mod.name}</span>
                  <span className="ml-2 text-xs text-muted">{mod.blurb}</span>
                </span>
                <span className="text-muted transition-transform group-hover:translate-x-0.5">→</span>
              </Link>
            ))}
          </div>
        </section>

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

        {/* Capital allocator — IMP-05 — real strategy P&L, and model disagreement — IMP-16 */}
        <section className="mt-14 mb-4">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="eyebrow">Allocator &amp; disagreement</h2>
            <span className="text-xs text-muted">Why capital moved this week, what&apos;s actually come back, and where models split.</span>
          </div>
          <div className="space-y-6">
            <AllocatorPanel alloc={m_alloc} state={m_state} />
            <AllocatorRibbon trades={trades} brokerName={broker.name} />
            <DisagreementPanel />
          </div>
        </section>
      </main>
    </div>
  );
}

import { ModuleNav } from "@/components/ModuleNav";
import { LineChart } from "@/components/LineChart";
import { Card, Badge } from "@/components/ui";
import {
  snapshots,
  strategies,
  strategyAttribution,
  performanceDisclosures,
  type StrategyKind,
} from "@/lib/sample-data";
import { computeMetrics } from "@/lib/metrics";
import { pctValue, shortDate } from "@/lib/format";

// PERFORMANCE ATTRIBUTION — IMP-01. An equity curve, a per-strategy
// attribution table, a weight-history stacked area on the same time axis,
// and discretionary / model-driven / paper kept as three SEPARATE lines,
// never blended into one number. Every v1.0 disclosure (inception,
// benchmark, gross/net, cash flows, valuation timing, data source) is shown.
//
// SAMPLE DATA: there is no real multi-strategy attribution ledger in this
// codebase — only one blended account/snapshot series. The per-strategy
// split below is an illustrative synthetic extension of that real series
// (see src/lib/sample-data.ts's `strategyAttribution` — additive, clearly
// commented). The blended equity curve itself (account value, unit value,
// SPY) is the same real sample data used on the Desk and the public page.
export const dynamic = "force-dynamic";

const KIND_LABEL: Record<StrategyKind, string> = {
  discretionary: "Discretionary",
  "model-driven": "Model-driven",
  paper: "Paper (no real capital)",
};

const STRAT_COLORS: Record<string, string> = {
  core: "var(--viz-cat-1)",
  signals: "var(--viz-cat-2)",
  "paper-weekly": "var(--viz-cat-4)",
};

export default function PerformancePage() {
  const m = computeMetrics(snapshots);
  const labels = snapshots.map((s) => shortDate(s.date));
  const usPct = m.portIndexed.map((v) => v - 100);
  const spyPct = m.spyIndexed.map((v) => v - 100);

  // Per-strategy cumulative index, starting at 100, compounding each week's
  // ATTRIBUTED contribution as if it were a standalone series. Illustrative:
  // these are portions of one blended book, not independently-traded P&L.
  const cumulative: Record<string, number[]> = {};
  for (const s of strategies) {
    const series: number[] = [100];
    for (let i = 1; i < strategyAttribution.length; i++) {
      const c = strategyAttribution[i].contributionPct[s.id] ?? 0;
      series.push(series[series.length - 1] * (1 + c / 100));
    }
    cumulative[s.id] = series;
  }

  const avgWeight = (id: string) => {
    const ws = strategyAttribution.map((p) => p.weight[id] ?? 0);
    return ws.reduce((a, b) => a + b, 0) / ws.length;
  };
  const totalContribution = (id: string) =>
    strategyAttribution.reduce((a, p) => a + (p.contributionPct[id] ?? 0), 0);

  return (
    <div>
      <ModuleNav crumb="Performance attribution" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Performance attribution</p>
          <span className="font-mono text-xs text-muted">IMP-01</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Where the return came from.</h1>

        <div className="mt-4 border border-amber-500/50 bg-amber-500/10 px-4 py-3 text-sm text-amber-700 dark:text-amber-400">
          ⚠ <strong>SAMPLE DATA — no live multi-strategy ledger exists yet.</strong>{" "}
          The equity curve below is the desk&apos;s real (simulated) blended
          account. The per-strategy split is an illustrative synthetic
          decomposition of that same series — see{" "}
          <code>src/lib/sample-data.ts</code>&apos;s <code>strategyAttribution</code>.
        </div>

        {/* v1.0 disclosures */}
        <div className="mt-8">
          <Card title="Disclosures">
            <dl className="grid gap-x-8 gap-y-4 sm:grid-cols-2">
              <Disclosure label="Inception date" value={performanceDisclosures.inceptionDate} />
              <Disclosure label="Benchmark" value={performanceDisclosures.benchmark} />
              <Disclosure label="Fee treatment" value={performanceDisclosures.feeTreatment} />
              <Disclosure label="Cash-flow treatment" value={performanceDisclosures.cashFlowTreatment} />
              <Disclosure label="Valuation timing" value={performanceDisclosures.valuationTiming} />
              <Disclosure label="Data source" value={performanceDisclosures.dataSource} />
            </dl>
          </Card>
        </div>

        {/* Equity curve — the real (sample) blended account */}
        <div className="mt-6">
          <Card title="Equity curve — us vs SPY (blended account)">
            <LineChart
              labels={labels}
              yFormat={(v) => `${v >= 0 ? "+" : ""}${v.toFixed(0)}%`}
              yAxisLabel="Cumulative return since inception (%)"
              asOf={m.latest.date}
              series={[
                { values: usPct, color: "currentColor", label: "Whitewater (blended)" },
                { values: spyPct, color: "#9ca3af", label: "SPY" },
              ]}
            />
          </Card>
        </div>

        {/* Attribution table */}
        <div className="mt-6">
          <Card title="Attribution — contribution vs. weight carried, this period">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="pb-2 font-medium">Strategy</th>
                    <th className="pb-2 font-medium">Kind</th>
                    <th className="pb-2 text-right font-medium">Avg weight carried</th>
                    <th className="pb-2 text-right font-medium">Contribution, period (pts)</th>
                  </tr>
                </thead>
                <tbody>
                  {strategies.map((s) => {
                    const contrib = totalContribution(s.id);
                    return (
                      <tr key={s.id} className="border-t border-hairline align-top">
                        <td className="py-2 font-medium">
                          <span className="inline-flex items-center gap-1.5">
                            <span
                              className="inline-block h-2 w-3 rounded-sm"
                              style={{ backgroundColor: STRAT_COLORS[s.id] }}
                            />
                            {s.name}
                          </span>
                          <div className="mt-0.5 text-xs font-normal text-muted">{s.description}</div>
                        </td>
                        <td className="py-2">
                          <Badge tone="neutral">{KIND_LABEL[s.kind]}</Badge>
                        </td>
                        <td className="py-2 text-right tabular-nums">{pctValue(avgWeight(s.id) * 100, 0)}</td>
                        <td
                          className={`py-2 text-right tabular-nums ${
                            contrib >= 0 ? "text-emerald-500" : "text-rose-500"
                          }`}
                        >
                          {contrib >= 0 ? "+" : ""}
                          {contrib.toFixed(2)} pts
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className="mt-3 text-[11px] text-muted">
              Contribution is a simple sum of each week&apos;s attributed
              percentage-point contribution — an additive approximation, not
              a geometric (compounded) return.
            </p>
          </Card>
        </div>

        {/* Weight-history stacked area, same time axis as the equity curve above */}
        <div className="mt-6">
          <Card title="Weight carried over time (capital-bearing strategies)">
            <WeightStack />
            <p className="mt-3 text-[11px] text-muted">
              {strategies.find((s) => s.kind === "paper")?.name} is omitted from
              the stack — it trades no real capital and always carries 0 book
              weight by definition.
            </p>
          </Card>
        </div>

        {/* Three separate lines — never blended */}
        <div className="mt-6">
          <Card title="Discretionary vs. model-driven vs. paper — kept separate">
            <p className="mb-3 text-xs text-muted">
              Cumulative index (start = 100) of each strategy&apos;s attributed
              weekly contribution, compounded as its own standalone series —
              illustrative, since these are portions of one blended book, not
              independently-traded P&amp;L. The three lines are never summed
              into a single blended number here.
            </p>
            <LineChart
              labels={labels}
              yFormat={(v) => v.toFixed(0)}
              yAxisLabel="Cumulative attributed contribution (indexed, start = 100)"
              asOf={m.latest.date}
              series={strategies.map((s, i) => ({
                values: cumulative[s.id],
                color: STRAT_COLORS[s.id],
                label: `${s.name} (${KIND_LABEL[s.kind]})`,
                // Distinct dash per line (not just color) for all 3 series —
                // LineChart's own default only varies index 0 vs. the rest.
                dash: ([undefined, "6,3", "2,3"] as (string | undefined)[])[i],
              }))}
            />
          </Card>
        </div>
      </main>
    </div>
  );
}

function Disclosure({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div className="mt-1 text-sm text-foreground/80">{value}</div>
    </div>
  );
}

// Small, page-local stacked area for the two capital-bearing strategies'
// weight history — same time axis (snapshot dates) as the equity curve above.
function WeightStack() {
  const width = 720;
  const height = 200;
  const padL = 48;
  const padR = 12;
  const padT = 12;
  const padB = 24;
  const ids = ["core", "signals"];
  const n = strategyAttribution.length;
  const x = (i: number) => padL + (i / Math.max(1, n - 1)) * (width - padL - padR);
  const y = (v: number) => padT + (1 - v) * (height - padT - padB);

  const areas = ids.map((id, si) => {
    const top = strategyAttribution.map((p) => ids.slice(0, si + 1).reduce((a, k) => a + (p.weight[k] ?? 0), 0));
    const bottom = strategyAttribution.map((p) => ids.slice(0, si).reduce((a, k) => a + (p.weight[k] ?? 0), 0));
    const topPath = top.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
    const bottomPath = bottom.map((v, i) => `L ${x(n - 1 - i).toFixed(1)} ${y(bottom[n - 1 - i]).toFixed(1)}`).join(" ");
    return `${topPath} ${bottomPath} Z`;
  });

  const xTickIdx = Array.from({ length: Math.min(6, n) }, (_, i) =>
    Math.round((i / Math.max(1, Math.min(6, n) - 1)) * (n - 1)),
  );

  return (
    <div className="w-full overflow-x-auto">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[520px]" role="img" aria-label="Weight carried by strategy, over time">
        {[0, 0.25, 0.5, 0.75, 1].map((f) => (
          <g key={f}>
            <line x1={padL} x2={width - padR} y1={y(f)} y2={y(f)} className="stroke-foreground/10" strokeWidth={1} />
            <text x={padL - 8} y={y(f) + 3} textAnchor="end" fontSize={10} className="fill-foreground/40">
              {(f * 100).toFixed(0)}%
            </text>
          </g>
        ))}
        {areas.map((d, i) => (
          <path key={i} d={d} fill={STRAT_COLORS[ids[i]]} fillOpacity={0.75} />
        ))}
        {xTickIdx.map((idx) => (
          <text key={idx} x={x(idx)} y={height - 6} textAnchor="middle" fontSize={10} className="fill-foreground/40">
            {shortDate(strategyAttribution[idx].date)}
          </text>
        ))}
      </svg>
      <div className="mt-2 flex flex-wrap gap-4 pl-12 text-xs text-foreground/60">
        {ids.map((id) => (
          <span key={id} className="inline-flex items-center gap-1.5">
            <span className="inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: STRAT_COLORS[id] }} />
            {strategies.find((s) => s.id === id)?.name}
          </span>
        ))}
      </div>
    </div>
  );
}

// ALLOCATOR RIBBON — VIS-01. A stacked area of budget-by-strategy over time,
// plus a utility-component bar breakdown for the current moment — the visual
// surface for WW-ALLOC (quant-infra/alloc/solve.py): "expected edge, minus an
// uncertainty penalty, minus a cost penalty, gives a score per strategy,"
// optimised into budgets under a risk term and a turnover charge.
//
// NO live allocator run or strategy P&L history exists anywhere in this repo
// (quant-infra/alloc/solve.py is a pure function over caller-supplied
// StrategyInput — there's no persisted history, no export, no
// `getAllocatorExport()`). Everything below is a clearly-labeled SAMPLE
// fixture built from that module's own vocabulary (shrunk edge, uncertainty
// penalty, cost penalty, score, budget) so it will look right the moment a
// real export exists, but it is illustrative, not a real allocation.

const dash = "—";
const pct = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;

export type StrategyBudgetWeek = {
  weekOf: string; // ISO date
  budgets: Record<string, number>; // strategy name -> budget fraction of gross, sums to <= 1
};

export type StrategyUtility = {
  strategy: string;
  shrunkEdge: number; // expected edge after track-record shrinkage (annualized, decimal)
  uncertaintyPenaltyTerm: number; // uncertainty_penalty * uncertainty (decimal, subtracted)
  costPenaltyTerm: number; // cost_penalty * cost_at_size (decimal, subtracted)
  score: number; // shrunkEdge - the two penalty terms
  budget: number; // resulting budget fraction this period
};

const STRATEGY_COLORS = [
  "var(--viz-cat-1)",
  "var(--viz-cat-2)",
  "var(--viz-cat-3)",
  "var(--viz-cat-4)",
];

const SAMPLE_STRATEGIES = [
  "Equity L/S (Incepta)",
  "Macro overlay (Aurora)",
  "Intra/Exitus tactical",
  "Weekly rank (WW-WEEKLY)",
];

function buildSampleHistory(): StrategyBudgetWeek[] {
  // Deterministic (no RNG): a slow rotation of budget across four strategies
  // over 20 weeks, each a smooth function of week index — illustrative only.
  const weeks = 20;
  const start = new Date("2026-04-13T00:00:00Z");
  return Array.from({ length: weeks }, (_, w) => {
    const t = w / (weeks - 1);
    const raw = [
      0.32 + 0.1 * Math.sin(t * Math.PI),
      0.22 + 0.08 * Math.cos(t * Math.PI * 1.3),
      0.18 + 0.12 * t,
      0.16 + 0.06 * Math.sin(t * Math.PI * 2),
    ];
    const total = raw.reduce((a, b) => a + b, 0);
    const budgets: Record<string, number> = {};
    SAMPLE_STRATEGIES.forEach((s, i) => (budgets[s] = raw[i] / total / 1.15)); // leave headroom (cash / unallocated)
    return {
      weekOf: new Date(start.getTime() + w * 7 * 24 * 3600 * 1000).toISOString().slice(0, 10),
      budgets,
    };
  });
}

const SAMPLE_UTILITY_NOW: StrategyUtility[] = [
  { strategy: SAMPLE_STRATEGIES[0], shrunkEdge: 0.041, uncertaintyPenaltyTerm: 0.012, costPenaltyTerm: 0.006, score: 0.023, budget: 0.29 },
  { strategy: SAMPLE_STRATEGIES[1], shrunkEdge: 0.028, uncertaintyPenaltyTerm: 0.015, costPenaltyTerm: 0.004, score: 0.009, budget: 0.19 },
  { strategy: SAMPLE_STRATEGIES[2], shrunkEdge: 0.052, uncertaintyPenaltyTerm: 0.022, costPenaltyTerm: 0.011, score: 0.019, budget: 0.24 },
  { strategy: SAMPLE_STRATEGIES[3], shrunkEdge: 0.019, uncertaintyPenaltyTerm: 0.009, costPenaltyTerm: 0.003, score: 0.007, budget: 0.14 },
];

const GENERATED_BY = "sample-fixture v1 — illustrative, no live WW-ALLOC run";

export function AllocatorRibbon({
  history = buildSampleHistory(),
  utilityNow = SAMPLE_UTILITY_NOW,
  generatedBy = GENERATED_BY,
  height = 220,
}: {
  history?: StrategyBudgetWeek[];
  utilityNow?: StrategyUtility[];
  generatedBy?: string;
  height?: number;
}) {
  const isSample = generatedBy.includes("sample");
  const strategies = utilityNow.map((u) => u.strategy);

  if (history.length === 0) {
    return (
      <div className="border border-hairline bg-paper p-6">
        <p className="eyebrow">Not synced yet</p>
        <p className="mt-2 text-sm text-foreground/80">
          No allocator budget history available.
        </p>
      </div>
    );
  }

  const width = 760;
  const padL = 48;
  const padR = 12;
  const padT = 12;
  const padB = 24;
  const n = history.length;
  const x = (i: number) => padL + (i / Math.max(1, n - 1)) * (width - padL - padR);
  const yMax = 1; // budgets are fractions of gross
  const y = (v: number) => padT + (1 - v / yMax) * (height - padT - padB);

  // Build stacked area paths
  const areas = strategies.map((s, si) => {
    const top = history.map((w) => strategies.slice(0, si + 1).reduce((acc, k) => acc + (w.budgets[k] ?? 0), 0));
    const bottom = history.map((w) => strategies.slice(0, si).reduce((acc, k) => acc + (w.budgets[k] ?? 0), 0));
    const topPath = top.map((v, i) => `${i === 0 ? "M" : "L"} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(" ");
    const bottomPath = bottom
      .map((v, i) => `L ${x(n - 1 - i).toFixed(1)} ${y(bottom[n - 1 - i]).toFixed(1)}`)
      .join(" ");
    return `${topPath} ${bottomPath} Z`;
  });

  const xTickIdx = Array.from({ length: Math.min(5, n) }, (_, i) =>
    Math.round((i / Math.max(1, Math.min(5, n) - 1)) * (n - 1)),
  );

  const maxUtilMag = Math.max(
    0.01,
    ...utilityNow.flatMap((u) => [u.shrunkEdge, u.uncertaintyPenaltyTerm, u.costPenaltyTerm, Math.abs(u.score)]),
  ) * 1.15;

  return (
    <div className="space-y-8">
      {isSample && (
        <div className="border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          ⚠ <strong>SAMPLE DATA — no live WW-ALLOC run exists yet.</strong> Budgets
          and utility terms below are an illustrative fixture built from
          quant-infra/alloc/solve.py&apos;s own scoring formula, not a real
          allocation.
        </div>
      )}

      <div>
        <p className="eyebrow mb-1">Budget by strategy, over time</p>
        <p className="mb-3 text-xs text-muted">
          Share of gross capital budget (%) allocated to each strategy, stacked. The
          gap to 100% is unallocated / cash headroom.
        </p>
        <div className="w-full overflow-x-auto">
          <svg viewBox={`0 0 ${width} ${height}`} className="w-full min-w-[560px]" role="img" aria-label="Budget by strategy, stacked over time">
            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <g key={f}>
                <line x1={padL} x2={width - padR} y1={y(f)} y2={y(f)} className="stroke-foreground/10" strokeWidth={1} />
                <text x={padL - 8} y={y(f) + 3} textAnchor="end" fontSize={9} className="fill-foreground/40">
                  {pct(f, 0)}
                </text>
              </g>
            ))}
            {areas.map((d, i) => (
              <path key={i} d={d} fill={STRATEGY_COLORS[i % STRATEGY_COLORS.length]} fillOpacity={0.75} />
            ))}
            {xTickIdx.map((idx) => (
              <text key={idx} x={x(idx)} y={height - 6} textAnchor="middle" fontSize={9} className="fill-foreground/40">
                {history[idx].weekOf}
              </text>
            ))}
          </svg>
        </div>
        <div className="mt-2 flex flex-wrap gap-4 pl-12 text-xs text-foreground/60">
          {strategies.map((s, i) => (
            <span key={s} className="inline-flex items-center gap-1.5">
              <span className="inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: STRATEGY_COLORS[i % STRATEGY_COLORS.length] }} />
              {s}
            </span>
          ))}
        </div>
        <p className="mt-2 pl-12 text-[11px] text-muted">
          Data as of {history[history.length - 1].weekOf}
        </p>
      </div>

      <div>
        <p className="eyebrow mb-1">Utility components — this moment</p>
        <p className="mb-3 text-xs text-muted">
          Score = shrunk expected edge − uncertainty penalty − cost penalty
          (annualized, decimal). This is what the optimiser maximises, before
          the risk and turnover terms.
        </p>
        <div className="space-y-4">
          {utilityNow.map((u, i) => (
            <div key={u.strategy}>
              <div className="flex items-center justify-between text-xs">
                <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
                  <span className="inline-block h-2 w-3 rounded-sm" style={{ backgroundColor: STRATEGY_COLORS[i % STRATEGY_COLORS.length] }} />
                  {u.strategy}
                </span>
                <span className="tabular-nums text-muted">
                  budget {pct(u.budget, 0)} · score{" "}
                  <span className={u.score >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}>
                    {u.score >= 0 ? "+" : ""}
                    {pct(u.score, 1)}
                  </span>
                </span>
              </div>
              <div className="mt-1.5 flex h-3 w-full overflow-hidden rounded-full bg-foreground/5">
                <div
                  className="h-full bg-emerald-500"
                  style={{ width: `${(u.shrunkEdge / maxUtilMag) * 100}%` }}
                  title={`+expected edge ${pct(u.shrunkEdge)}`}
                />
                <div
                  className="h-full bg-amber-500"
                  style={{ width: `${(u.uncertaintyPenaltyTerm / maxUtilMag) * 100}%` }}
                  title={`-uncertainty penalty ${pct(u.uncertaintyPenaltyTerm)}`}
                />
                <div
                  className="h-full bg-rose-500"
                  style={{ width: `${(u.costPenaltyTerm / maxUtilMag) * 100}%` }}
                  title={`-cost penalty ${pct(u.costPenaltyTerm)}`}
                />
              </div>
              <div className="mt-1 flex gap-4 text-[10px] text-muted">
                <span>
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" /> edge {pct(u.shrunkEdge)}
                </span>
                <span>
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" /> uncertainty −{pct(u.uncertaintyPenaltyTerm)}
                </span>
                <span>
                  <span className="inline-block h-1.5 w-1.5 rounded-full bg-rose-500" /> cost −{pct(u.costPenaltyTerm)}
                </span>
              </div>
            </div>
          ))}
        </div>
        <p className="mt-4 text-[11px] text-muted">{generatedBy || dash}</p>
      </div>
    </div>
  );
}

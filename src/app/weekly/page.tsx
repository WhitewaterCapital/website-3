import { ModuleNav } from "@/components/ModuleNav";
import { Card, Badge } from "@/components/ui";
import { getWeeklyExport } from "@/lib/weekly";
import type { WeeklyExport, WeeklyForecast } from "@/lib/models/weekly-export";
import { pct } from "@/lib/format";

// WW-WEEKLY — the ranked weekly cross-sectional forecast. Previously read
// only internally (WATCH-02's quantile-band check, and as a reserved
// conviction slot in src/lib/models/conviction.ts) with no page of its own
// showing the ranked list to a member. Renders the REAL engine export
// (getWeeklyExport() / public/data/weekly/latest.json); honest "not synced"
// state when it hasn't exported, matching the pattern IntraExitusPage /
// EquityReader / MacroReader use for their own real-data reads — never a
// fabricated table.
export const dynamic = "force-dynamic";

const dash = "—";
const scoreFmt = (x: number | null | undefined, d = 2) =>
  x == null ? dash : `${x > 0 ? "+" : ""}${x.toFixed(d)}`;

export default async function WeeklyPage() {
  const data = await getWeeklyExport();

  return (
    <div>
      <ModuleNav crumb="Weekly" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// WW-Weekly</p>
          <span className="font-mono text-xs text-muted">the weekly rank</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">
          This week&apos;s cross-sectional read.
        </h1>
        <p className="mt-3 max-w-2xl text-muted">
          A ranked read across the universe — who&apos;s expected to lead, who&apos;s
          expected to lag, and how confident the engine is in that ordering.
          The ranking is the point; no single number here is a price target.
        </p>

        <div className="mt-8">
          {data ? (
            <WeeklyTable data={data} />
          ) : (
            <Card>
              <p className="eyebrow">Not synced yet</p>
              <p className="mt-2 text-sm text-foreground/80">
                The engine hasn&apos;t exported. Run{" "}
                <code>python -m wf.export</code> in{" "}
                <code>weekly-engine/</code> to populate{" "}
                <code>public/data/weekly/latest.json</code>.
              </p>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}

function WeeklyTable({ data }: { data: WeeklyExport }) {
  const sorted = [...data.forecasts].sort((a, b) => {
    const d = (b.decile ?? -1) - (a.decile ?? -1);
    if (d !== 0) return d;
    return (b.expected_relative_return ?? -Infinity) - (a.expected_relative_return ?? -Infinity);
  });

  return (
    <div className="space-y-6">
      {/* Framing — a research read, not advice, same honesty layer as the other real-data readers */}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Research read</Badge>
          <span className="text-xs text-muted">
            Cross-sectional rank signal · not price targets · not investment advice
          </span>
          <Badge tone={data.provenance.kind === "live" ? "up" : "warn"}>
            {data.provenance.kind === "live" ? "Live data" : "Synthetic demo data"}
          </Badge>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">{data.disclaimer}</p>
        {/* Two distinct timestamps, never merged: data as-of vs. when this run was computed. */}
        <p className="mt-2 font-mono text-[11px] text-muted">
          WW-WEEKLY {data.schema_version} · engine {data.engine_version} · data
          as of {data.as_of} · computed {data.generated_at} · {data.forecasts.length}/
          {data.universe.length} names ranked
        </p>
      </div>

      {data.forecasts.length === 0 ? (
        <Card>
          <p className="eyebrow">No forecasts this run</p>
          <p className="mt-2 text-sm text-foreground/80">
            The engine ran but produced no forecasts for the current universe —
            an honest empty result, not a sync failure.
          </p>
        </Card>
      ) : (
        <Card title="Ranked forecast — sorted by decile">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="pb-2 font-medium">Symbol</th>
                  <th className="pb-2 text-right font-medium">Expected relative return</th>
                  <th className="pb-2 text-right font-medium">Quantile band (p10 – p90)</th>
                  <th className="pb-2 text-right font-medium">Decile</th>
                  <th className="pb-2 font-medium">Confidence</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((f) => (
                  <ForecastRow key={f.ticker} f={f} />
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[11px] text-muted">
            Expected relative return is a standardized, sector-neutral ranking
            score — not a percentage return. Read magnitude off the quantile
            band, ordering off decile (10 = most bullish that week, 1 = most
            bearish). Sorted highest decile first.
          </p>
        </Card>
      )}

      <p className="text-[11px] text-muted">
        Validated on {data.validation.n_folds} walk-forward folds · published
        model {data.validation.model_version_published}
        {data.validation.gbm_beats_baseline_reason
          ? ` — ${data.validation.gbm_beats_baseline_reason}`
          : ""}
        .
      </p>
    </div>
  );
}

function ForecastRow({ f }: { f: WeeklyForecast }) {
  const band =
    f.quantile_p10 == null || f.quantile_p90 == null
      ? dash
      : `${pct(f.quantile_p10)} – ${pct(f.quantile_p90)}`;
  return (
    <tr className="border-t border-hairline">
      <td className="py-2 font-medium">
        {f.ticker}
        {f.provisional && (
          <span className="ml-2 align-middle text-[10px] font-normal uppercase tracking-wide text-amber-600 dark:text-amber-400">
            provisional
          </span>
        )}
      </td>
      <td className="py-2 text-right tabular-nums">{scoreFmt(f.expected_relative_return)}</td>
      <td className="py-2 text-right tabular-nums text-muted">{band}</td>
      <td className="py-2 text-right tabular-nums">{f.decile ?? dash}</td>
      <td className="py-2">
        <Badge tone="neutral">{f.confidence}</Badge>
      </td>
    </tr>
  );
}

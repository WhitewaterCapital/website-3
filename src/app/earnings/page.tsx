import { ModuleNav } from "@/components/ModuleNav";
import { Card, Badge } from "@/components/ui";
import { earningsMove, EARNINGS_MOVE_UNIVERSE } from "@/lib/models/impl/earnings-move";
import { getEarningsExport } from "@/lib/earnings";
import type { EquityReading, EquitySignal } from "@/lib/models/types";

// Earnings Move — PLATFORM_REBUILD_PLAN.md priority #13/#14. Server-renders
// earningsMove.read() directly, same pattern smart-money/page.tsx set for
// its own EquityModel. This is deliberately NOT a surprise-direction or
// price-move predictor (see earnings-move.ts's own header and the research
// dossier's "Medium confidence, needs paid estimate data" verdict on that
// harder problem) — it's a calendar + the two real positioning signals this
// app already has, attached honestly, with abstention where an input is
// missing. Distresse's own earnings-catalyst devil's-advocate note points
// here rather than duplicating this reasoning inline.
export const dynamic = "force-dynamic";

export default async function EarningsPage() {
  const dateISO = new Date().toISOString().slice(0, 10);
  const [data, calendarExport] = await Promise.all([
    earningsMove.read(dateISO),
    getEarningsExport(),
  ]);

  return (
    <div>
      <ModuleNav crumb="Earnings Move" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Earnings Move</p>
          <span className="font-mono text-xs text-muted">upcoming prints × pre-print positioning</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Who reports next, and what the real signals say going in.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          A fixed {EARNINGS_MOVE_UNIVERSE.length}-name universe ({EARNINGS_MOVE_UNIVERSE.join(", ")}), checked against
          WW-EARNINGS&apos; calendar export. Not a surprise-direction or price-move prediction — this app has no
          analyst-estimate data to base one on (see <code>earnings-engine/README.md</code>). Where a print is coming up,
          this shows WW-Insider&apos;s real pre-print Form 4 positioning and WW-Factor&apos;s real momentum context, and
          nothing else.
        </p>

        {calendarExport?.data_provenance === "synthetic-demo" ? (
          <div className="mt-6 border border-hairline bg-paper px-5 py-4">
            <Badge tone="warn">Synthetic-demo calendar</Badge>
            <p className="mt-2 text-xs leading-relaxed text-muted">
              No <code>FMP_API_KEY</code> is configured, so every date below comes from{" "}
              <code>earnings-engine/ee/synthetic.py</code>&apos;s deterministic fixture generator, not a real
              earnings calendar. Set the key and re-run <code>python -m ee.export</code> in{" "}
              <code>earnings-engine/</code> to switch this to real print dates.
            </p>
          </div>
        ) : null}

        <div className="mt-8">
          <EarningsTable data={data} />
        </div>
      </main>
    </div>
  );
}

function EarningsTable({ data }: { data: EquityReading }) {
  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Research read</Badge>
          <span className="text-xs text-muted">Calendar + real pre-print positioning · not investment advice</span>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">{data.summary}</p>
      </div>

      {data.signals.length === 0 ? (
        <Card>
          <p className="eyebrow">No prints in the lookahead window</p>
          <p className="mt-2 text-sm text-foreground/80">
            Either WW-EARNINGS hasn&apos;t exported yet, or none of the {EARNINGS_MOVE_UNIVERSE.length} tracked names
            have a confirmed print inside its lookahead window right now — this is the expected state between
            earnings seasons, not a fabricated empty table.
          </p>
        </Card>
      ) : (
        <Card title="Upcoming prints — soonest first">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="pb-2 font-medium">Symbol</th>
                  <th className="pb-2 text-right font-medium">Insider lean</th>
                  <th className="pb-2 font-medium">Detail</th>
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
            &quot;Insider lean&quot; is built from ONE real directional ingredient — WW-Insider&apos;s trailing
            30-day pre-print Form 4 net buy/sell — stated plainly as that, never blended with factor momentum or
            presented as a forecast of which way the print itself will move the stock.
          </p>
        </Card>
      )}

      <p className="text-[11px] text-muted">Overall breadth across flagged names: {data.breadth > 0 ? "+" : ""}{data.breadth}.</p>
    </div>
  );
}

function SignalRow({ s }: { s: EquitySignal }) {
  return (
    <tr className="border-t border-hairline">
      <td className="py-2 font-medium">{s.symbol}</td>
      <td className="py-2 text-right tabular-nums">
        {s.score !== 0 ? (s.score > 0 ? "+" : "") : ""}
        {s.score !== 0 ? s.score : "—"}
      </td>
      <td className="py-2 text-xs text-muted">{s.note}</td>
    </tr>
  );
}

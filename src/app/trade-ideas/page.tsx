import Link from "next/link";
import { ModuleNav } from "@/components/ModuleNav";
import { Card, Badge } from "@/components/ui";
import { getWeeklyExport } from "@/lib/weekly";
import type { WeeklyExport } from "@/lib/models/weekly-export";
import { smartMoneyMomentum } from "@/lib/models/impl/smart-money-momentum";
import { earningsMove } from "@/lib/models/impl/earnings-move";
import { getEarningsExport } from "@/lib/earnings";
import type { EarningsExport } from "@/lib/models/earnings-export";
import type { EquityReading } from "@/lib/models/types";
import { shortDate } from "@/lib/format";

// TRADE IDEAS — the direct answer to the platform's founding request, "i
// want a proper bot which can suggest trades" (read exactly as written:
// SUGGEST, never place an order — the desk still executes every trade
// manually through IBKR; nothing on this page, or anywhere in this app,
// is wired to a broker's order entry). Until this page existed the site
// was purely reactive: a member had to already have a ticker in mind and
// manually run it through Stress Test. Nothing proactively surfaced a
// candidate idea for them to look at in the first place.
//
// This page does exactly one honest thing, and nothing more: it takes the
// three models this codebase has ALREADY built and already proven real —
//   - WW-Weekly (weekly.ts / weekly-export.ts) — a ranked cross-sectional
//     forecast; top/bottom deciles are candidate longs/shorts.
//   - Smart Money Momentum (impl/smart-money-momentum.ts) — a real,
//     live insider-buying x momentum-beta screen.
//   - Earnings Move (impl/earnings-move.ts) — real upcoming prints with
//     real WW-Insider pre-print positioning attached.
// — and unions their outputs by ticker. Every ticker any ONE of the three
// flags becomes one card below, badged by exactly which source(s) flagged
// it and why, in that source's own words (each detail line is pulled
// straight from the underlying model's own note/summary text, never a
// reason invented here).
//
// DELIBERATELY NOT DONE: a single blended "conviction score" across the
// three. They do not share confidence semantics — WW-Weekly's decile is a
// cross-sectional RANK from a research-grade model that is, as of this
// writing, running on synthetic-demo data (see the banner below); Smart
// Money's tilt is a real but explicitly unbacktested simple average of two
// already-scaled real reads; Earnings' lean is built from exactly ONE real
// directional ingredient and is explicitly not a forecast of which way the
// print itself will move the stock. Averaging three differently-uncertain
// numbers into one score would launder that into a false sense of
// agreement — see conviction.ts's own capping mechanism for why this
// codebase already refuses to do that even for a single name's own
// composite verdict. Sources stay separate, badged, and in their own
// words here. The only ordering rule is honest and needs no invented
// weighting: more sources agreeing on a name places it higher.
//
// Framed exactly like smart-money/page.tsx and earnings/page.tsx already
// frame their own output: a research read, not a verdict. The verdict, if
// there is one, happens one click away in Stress Test, where Distresse
// runs its full adversarial six-dimension read on the specific idea a
// member actually chooses to pursue.
export const dynamic = "force-dynamic";

type SourceName = "Weekly" | "Smart Money" | "Earnings";
type Tone = "up" | "down" | "warn" | "neutral";

type SourceFlag = {
  source: SourceName;
  label: string; // badge text, e.g. "Weekly: decile 9 (bullish)"
  tone: Tone;
  detail: string; // one-line grounded reason, pulled from the source's own read
};

type IdeaRow = {
  ticker: string;
  flags: SourceFlag[];
};

const fmtSigned = (n: number | null | undefined, digits = 2) =>
  n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(digits)}`;

// Top/bottom 3 of WW-Weekly's 1..10 decile scale read as candidate
// longs/shorts here — a stated, round cutoff (roughly the top/bottom 30%
// of the ranked universe), not a fitted or backtested threshold. Deciles
// 4-7 are "no strong lean" and are left out of this feed entirely — the
// same abstention instinct as everywhere else in this codebase: no
// fabricated middle-of-the-road flag standing in for a real signal.
const LONG_DECILE_FLOOR = 8;
const SHORT_DECILE_CEIL = 3;

function weeklyFlags(weekly: WeeklyExport | null): Map<string, SourceFlag> {
  const out = new Map<string, SourceFlag>();
  if (!weekly) return out;
  const synthetic = weekly.provenance.kind !== "live";
  for (const f of weekly.forecasts) {
    if (f.decile == null) continue;
    let direction: string;
    if (f.decile >= LONG_DECILE_FLOOR) {
      direction = "bullish";
    } else if (f.decile <= SHORT_DECILE_CEIL) {
      direction = "bearish";
    } else {
      continue; // middle of the ranked pack this week — no lean shown here
    }
    const label = synthetic
      ? `Weekly (synthetic-demo): decile ${f.decile}`
      : `Weekly: decile ${f.decile} (${direction})`;
    const detail = synthetic
      ? `SYNTHETIC-DEMO reading, not a real forecast — WW-Weekly has no real point-in-time feed wired in yet ` +
        `(${weekly.provenance.note}). It ranked ${f.ticker} decile ${f.decile}/10 on fabricated data; read this as ` +
        `scaffolding, never as real signal, until the engine runs against a real feed.`
      : `WW-Weekly ranks it decile ${f.decile}/10 this week — expected relative return ${fmtSigned(f.expected_relative_return)} ` +
        `(a standardized sector-neutral score, not a % return; ${f.confidence}${f.provisional ? ", provisional" : ""}).`;
    out.set(f.ticker, { source: "Weekly", label, tone: synthetic ? "warn" : direction === "bullish" ? "up" : "down", detail });
  }
  return out;
}

function smartMoneyFlags(data: EquityReading): Map<string, SourceFlag> {
  const out = new Map<string, SourceFlag>();
  for (const s of data.signals) {
    const tone: Tone = s.score > 0 ? "up" : s.score < 0 ? "down" : "neutral";
    out.set(s.symbol, {
      source: "Smart Money",
      label: `Smart Money: ${s.score > 0 ? "+" : ""}${s.score}`,
      tone,
      detail: s.note,
    });
  }
  return out;
}

function earningsFlags(data: EquityReading, calendar: EarningsExport | null): Map<string, SourceFlag> {
  const out = new Map<string, SourceFlag>();
  for (const s of data.signals) {
    const event = calendar?.events.find((e) => e.ticker.toUpperCase() === s.symbol.toUpperCase());
    // Pull the lean word straight out of earnings-move.ts's own note text
    // rather than re-deriving it from the score sign here, so the badge
    // can never say something the model itself didn't already say.
    const leanMatch = s.note.match(/(bullish-lean|bearish-lean|no lean)/);
    const lean = leanMatch ? leanMatch[1] : "no lean";
    const tone: Tone = lean === "bullish-lean" ? "up" : lean === "bearish-lean" ? "down" : "neutral";
    const dateLabel = event ? shortDate(event.report_date) : "date tbd";
    out.set(s.symbol, {
      source: "Earnings",
      label: `Earnings: print ${dateLabel}, ${lean}`,
      tone,
      detail: s.note,
    });
  }
  return out;
}

export default async function TradeIdeasPage() {
  const dateISO = new Date().toISOString().slice(0, 10);
  const [weekly, smartMoney, earnings, calendar] = await Promise.all([
    getWeeklyExport(),
    smartMoneyMomentum.read(dateISO),
    earningsMove.read(dateISO),
    getEarningsExport(),
  ]);

  const wFlags = weeklyFlags(weekly);
  const sFlags = smartMoneyFlags(smartMoney);
  const eFlags = earningsFlags(earnings, calendar);

  const tickers = new Set<string>([...wFlags.keys(), ...sFlags.keys(), ...eFlags.keys()]);
  const rows: IdeaRow[] = [...tickers]
    .map((ticker) => ({
      ticker,
      flags: [wFlags.get(ticker), sFlags.get(ticker), eFlags.get(ticker)].filter(
        (f): f is SourceFlag => f != null,
      ),
    }))
    // More sources agreeing = higher in the feed. Honest, requires no
    // invented weighting. Alphabetical tiebreak for determinism only.
    .sort((a, b) => b.flags.length - a.flags.length || a.ticker.localeCompare(b.ticker));

  const weeklySynthetic = weekly ? weekly.provenance.kind !== "live" : false;
  const calendarSynthetic = calendar?.data_provenance === "synthetic-demo";

  return (
    <div>
      <ModuleNav crumb="Trade Ideas" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Trade Ideas</p>
          <span className="font-mono text-xs text-muted">Weekly × Smart Money × Earnings, unioned by ticker</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Where the real signals overlap.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          Every name any of this app&apos;s three cross-sectional screens flags, in one feed — WW-Weekly&apos;s
          ranked decile, Smart Money Momentum&apos;s insider × factor tilt, and Earnings Move&apos;s pre-print
          positioning. This is where a member starts, not where they finish: open Stress Test on any name to run
          Distresse&apos;s full adversarial read before deciding anything. Nothing here places an order — the desk
          still executes every trade manually through IBKR.
        </p>

        <div className="mt-6 flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Research read</Badge>
          <span className="text-xs text-muted">Discovery/screening layer · not a verdict · not investment advice</span>
        </div>

        {weeklySynthetic && (
          <div className="mt-4 border border-hairline bg-paper px-5 py-4">
            <Badge tone="warn">WW-Weekly is synthetic-demo</Badge>
            <p className="mt-2 text-xs leading-relaxed text-muted">
              WW-Weekly&apos;s ranked decile has no real point-in-time price/volume feed wired in yet (see{" "}
              <code>public/data/weekly/latest.json</code>&apos;s own <code>provenance</code> block) — every Weekly
              badge below is marked and colored accordingly. Read those rows as scaffolding, never as real signal,
              until the engine runs against a real feed.
            </p>
          </div>
        )}
        {calendarSynthetic && (
          <div className="mt-4 border border-hairline bg-paper px-5 py-4">
            <Badge tone="warn">Earnings calendar is synthetic-demo</Badge>
            <p className="mt-2 text-xs leading-relaxed text-muted">
              No <code>FMP_API_KEY</code> is configured, so every print date behind an Earnings badge below comes
              from <code>earnings-engine/ee/synthetic.py</code>&apos;s deterministic fixture generator, not a real
              earnings calendar (see <code>earnings-engine/README.md</code>).
            </p>
          </div>
        )}

        <div className="mt-8">
          {rows.length === 0 ? (
            <Card>
              <p className="eyebrow">Nothing flagged right now</p>
              <p className="mt-2 text-sm text-foreground/80">
                None of the three underlying screens has a name to surface this run:{" "}
                {weekly
                  ? "WW-Weekly has no name in its top or bottom three deciles this week"
                  : "WW-Weekly hasn't exported yet"}
                ; Smart Money Momentum has {smartMoney.signals.length} names ranked ({smartMoney.summary}); Earnings
                Move has {earnings.signals.length} prints flagged ({earnings.summary}). This is an honest empty
                feed, not a fabricated placeholder — check back after the next sync, or open each module directly
                for its own coverage notes.
              </p>
            </Card>
          ) : (
            <div className="space-y-4">
              {rows.map((row) => (
                <IdeaCard key={row.ticker} row={row} />
              ))}
            </div>
          )}
        </div>

        <p className="mt-6 text-[11px] text-muted">
          Ordered by how many of the three sources flag a name — more agreement, higher in the list. That is the
          only ranking rule: there is deliberately no single blended conviction number across sources, because each
          one measures something different (a cross-sectional rank, an unbacktested screen, a single positioning
          lean) — see <code>conviction.ts</code>&apos;s own capping logic for why this app already refuses to
          collapse independent reads into one score even for a single name, let alone three different models.
        </p>
      </main>
    </div>
  );
}

function IdeaCard({ row }: { row: IdeaRow }) {
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-semibold">{row.ticker}</h3>
          {row.flags.map((f) => (
            <Badge key={f.source} tone={f.tone}>
              {f.label}
            </Badge>
          ))}
        </div>
        <Link
          href={`/stress-test?ticker=${row.ticker}`}
          className="whitespace-nowrap text-xs font-medium text-accent hover:underline"
        >
          Run Stress Test →
        </Link>
      </div>
      <ul className="mt-3 space-y-1.5">
        {row.flags.map((f) => (
          <li key={f.source} className="text-xs leading-relaxed text-muted">
            <span className="font-medium text-foreground/80">{f.source}:</span> {f.detail}
          </li>
        ))}
      </ul>
    </Card>
  );
}

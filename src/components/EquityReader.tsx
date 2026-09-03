"use client";

import { useState } from "react";
import type {
  EquityExport,
  SecurityAnalysis,
  RankingEntry,
} from "@/lib/models/incepta-export";
import type { StressVerdict } from "@/lib/models/types";
import { Badge } from "@/components/ui";
import { ScoreBar } from "@/components/ScoreBar";

// ── Formatters. null → "—" ALWAYS (never 0, never a guess). ─────────────────
const dash = "—";
const pct = (x: number | null | undefined, signed = false) =>
  x == null ? dash : `${signed && x > 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
const ratio = (x: number | null | undefined, d = 2) =>
  x == null ? dash : x.toFixed(d);
const price = (x: number | null | undefined) =>
  x == null ? dash : `$${x.toFixed(2)}`;
const bps = (x: number | null | undefined) =>
  x == null ? dash : `${x.toFixed(0)} bps`;
const money = (x: number | null | undefined) => {
  if (x == null) return dash;
  const a = Math.abs(x);
  if (a >= 1e12) return `$${(x / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(x / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(x / 1e6).toFixed(1)}M`;
  return `$${x.toFixed(0)}`;
};

const confTone = {
  high: "neutral",
  medium: "warn",
  low: "warn",
  insufficient: "down",
} as const;

export function EquityReader({ data }: { data: EquityExport }) {
  return (
    <div className="space-y-10">
      {/* Framing — this is a risk-and-evidence display, not advice */}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Risk &amp; evidence display</Badge>
          <span className="text-xs text-muted">
            Not investment advice · not a buy/sell signal
          </span>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">
          {data.disclaimer}
        </p>
        {/* Two distinct timestamps, never merged: data as-of vs. when this run
            was computed. */}
        <p className="mt-2 font-mono text-[11px] text-muted">
          Incepta {data.schema_version} · engine {data.engine_version} · data as
          of {data.as_of} · computed {data.generated_at} · {data.universe.length}{" "}
          names
        </p>
      </div>

      <AnalyzeTicker universe={data.universe} />

      {data.rankings.quality.length > 0 && (
        <RankingsTable rankings={data.rankings.quality} asOf={data.as_of} />
      )}

      <div>
        <h3 className="eyebrow mb-3">Securities · {data.securities.length}</h3>
        {data.securities.length === 0 ? (
          <p className="text-sm text-muted">
            No securities in this run&apos;s universe yet.
          </p>
        ) : (
          <div className="space-y-4">
            {data.securities.map((s) => (
              <SecurityCard key={s.ticker} s={s} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// Enter any ticker → the engine pulls its real SEC + price data on demand.
// Never fabricates: on-demand result is real engine output, or an honest error.
function AnalyzeTicker({ universe }: { universe: string[] }) {
  const [ticker, setTicker] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [result, setResult] = useState<SecurityAnalysis | null>(null);
  const [source, setSource] = useState("");
  const [message, setMessage] = useState("");

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setState("loading");
    setResult(null);
    setMessage("");
    try {
      const res = await fetch("/api/models/equity/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: t }),
      });
      const data = await res.json();
      if (data.status === "ok") {
        setResult(data.security);
        setSource(data.source);
        setState("done");
      } else {
        setMessage(data.message ?? "Not available.");
        setState("error");
      }
    } catch {
      setMessage("Couldn't reach the engine.");
      setState("error");
    }
  }

  return (
    <div className="border border-hairline bg-paper p-5">
      <p className="eyebrow">Analyze any ticker</p>
      <p className="mt-1 text-xs text-muted">
        Not in the {universe.length}-name set? Enter a ticker and the engine pulls
        its real SEC filings + prices on demand. A first-time name can take
        20–40s.
      </p>
      <form onSubmit={submit} className="mt-3 flex gap-2">
        <input
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          placeholder="e.g. GOOGL"
          className="w-40 border border-hairline bg-background px-3 py-2 text-sm uppercase outline-none focus:border-foreground/40"
        />
        <button
          disabled={state === "loading"}
          className="bg-foreground px-5 py-2 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
        >
          {state === "loading" ? "Running engine…" : "Analyze"}
        </button>
      </form>

      {state === "loading" && (
        <p className="mt-3 text-xs text-muted">
          Running the engine on {ticker} — pulling SEC filings + prices. This is a
          live computation, not a lookup.
        </p>
      )}
      {state === "error" && <p className="mt-3 text-sm text-rose-500">{message}</p>}
      {state === "done" && result && (
        <div className="mt-4">
          <p className="mb-2 text-xs text-muted">
            {source === "universe"
              ? "From the current universe."
              : "Computed live by the engine — real SEC + price data."}
          </p>
          <SecurityCard s={result} />
        </div>
      )}
    </div>
  );
}

function RankingsTable({ rankings, asOf }: { rankings: RankingEntry[]; asOf: string }) {
  return (
    <div>
      <h3 className="eyebrow mb-1">Quality ranking</h3>
      <p className="mb-3 text-xs text-muted">
        <strong className="text-foreground/70">Relative to the {rankings.length}-name universe below</strong>,
        not the whole market. Percentile (0–100) and z-score of a composite of
        fundamental-quality metrics (ROA, margins, leverage, revenue growth,
        Piotroski F) at each name&apos;s latest filing. Cross-sectional, this
        run only — not an absolute or time-series rating. As of {asOf}.
      </p>
      <div className="border border-hairline bg-paper">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="px-4 py-2 font-medium">Ticker</th>
              <th className="px-4 py-2 text-right font-medium">Percentile</th>
              <th className="px-4 py-2 text-right font-medium">Z-score</th>
              <th className="px-4 py-2">Relative quality</th>
            </tr>
          </thead>
          <tbody>
            {rankings.map((r) => (
              <tr key={r.ticker} className="border-t border-hairline">
                <td className="px-4 py-2 font-medium">{r.ticker}</td>
                <td className="px-4 py-2 text-right tabular-nums">{r.rank}</td>
                <td
                  className={`px-4 py-2 text-right tabular-nums ${
                    r.score >= 0 ? "text-emerald-500" : "text-rose-500"
                  }`}
                >
                  {r.score >= 0 ? "+" : ""}
                  {r.score.toFixed(2)}
                </td>
                <td className="px-4 py-2">
                  <div className="max-w-[160px]">
                    <ScoreBar score={Math.max(-100, Math.min(100, r.score * 33))} />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SecurityCard({ s }: { s: SecurityAnalysis }) {
  const insufficient = s.confidence === "insufficient";
  const greyed = insufficient || s.confidence === "low";
  const allFlags = [
    ...(s.data_quality.flags ?? []),
    ...(s.valuation?.flags ?? []),
  ];

  return (
    <section
      className={`border border-hairline bg-paper p-5 ${greyed ? "opacity-60" : ""}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h4 className="text-lg font-semibold">{s.ticker}</h4>
            <Badge tone={confTone[s.confidence]}>{s.confidence}</Badge>
          </div>
          <p className="text-sm text-muted">
            {s.name ?? dash}
            {s.sector ? ` · ${s.sector}` : ""}
          </p>
        </div>
        <div className="text-right text-xs text-muted">
          <div className="tabular-nums text-foreground">
            {price(s.data_quality.price_last_close)}
          </div>
          <div>as of {s.as_of}</div>
        </div>
      </div>

      {/* Flags — the honesty layer */}
      {allFlags.length > 0 && (
        <ul className="mt-3 space-y-1">
          {allFlags.map((f, i) => (
            <li key={i} className="text-xs text-amber-600 dark:text-amber-400">
              ⚠ {f}
            </li>
          ))}
        </ul>
      )}

      {insufficient ? (
        <p className="mt-4 text-sm text-muted">
          Not enough data — the engine abstains rather than show unreliable
          numbers.
        </p>
      ) : (
        <>
          <div className="mt-5 grid gap-6 sm:grid-cols-3">
            <MetricGroup
              title="Risk"
              empty={!s.risk && "No price history."}
              rows={
                s.risk && [
                  ["12-1 momentum", pct(s.risk.mom_12_1, true)],
                  ["1m return", pct(s.risk.ret_1m, true)],
                  ["Realized vol", pct(s.risk.realized_vol)],
                  ["Downside vol", pct(s.risk.downside_vol)],
                  ["Max DD (1y)", pct(s.risk.max_dd_1y, true)],
                  ["52w-high ratio", ratio(s.risk.high_52w_ratio)],
                  ["Beta (mkt)", ratio(s.risk.beta_mkt)],
                  ["Idio vol", pct(s.risk.idio_vol)],
                  ["Est. spread", bps(s.risk.spread_bps)],
                ]
              }
            />
            <MetricGroup
              title="Quality"
              empty={!s.quality && "No fundamentals."}
              rows={
                s.quality && [
                  ["ROA", pct(s.quality.roa)],
                  ["ROE", pct(s.quality.roe)],
                  ["Gross margin", pct(s.quality.gross_margin)],
                  ["Net margin", pct(s.quality.net_margin)],
                  ["FCF margin", pct(s.quality.fcf_margin)],
                  ["Rev growth", pct(s.quality.rev_growth, true)],
                  ["Leverage", ratio(s.quality.leverage)],
                  [
                    "Piotroski",
                    s.quality.piotroski_f == null
                      ? dash
                      : `${s.quality.piotroski_f} / ${s.quality.piotroski_max ?? 9}`,
                  ],
                ]
              }
            />
            <MetricGroup
              title="Valuation"
              empty={!s.valuation && "No valuation."}
              rows={
                s.valuation && [
                  ["Market cap", money(s.valuation.market_cap)],
                  ["P/E", ratio(s.valuation.pe, 1)],
                  ["Earnings yield", pct(s.valuation.earnings_yield)],
                  ["P/B", ratio(s.valuation.pb, 1)],
                  ["P/S", ratio(s.valuation.ps, 1)],
                  ["FCF yield", pct(s.valuation.fcf_yield)],
                  ["EV/Sales", ratio(s.valuation.ev_sales, 1)],
                ]
              }
            />
          </div>

          <StressAction ticker={s.ticker} />
        </>
      )}
    </section>
  );
}

function MetricGroup({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: [string, string][] | null | undefined | false;
  empty: string | false | undefined;
}) {
  return (
    <div>
      <div className="eyebrow mb-2">{title}</div>
      {rows ? (
        <dl className="space-y-1.5">
          {rows.map(([k, v]) => (
            <div key={k} className="flex items-center justify-between text-sm">
              <dt className="text-muted">{k}</dt>
              <dd className="tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-sm text-muted">{empty || dash}</p>
      )}
    </div>
  );
}

// Per-trade flow: feed this security into Distresse via /api/models/stress.
function StressAction({ ticker }: { ticker: string }) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [verdict, setVerdict] = useState<StressVerdict | null>(null);

  async function run() {
    setState("loading");
    try {
      const res = await fetch("/api/models/stress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, instrument: "long" }),
      });
      const data = await res.json();
      setVerdict(data.distresse);
      setState("done");
    } catch {
      setState("error");
    }
  }

  const ratingTone = { go: "up", conditional: "warn", "no-go": "down" } as const;

  return (
    <div className="mt-5 border-t border-hairline pt-4">
      {!verdict ? (
        <button
          onClick={run}
          disabled={state === "loading"}
          className="text-xs font-medium text-accent hover:underline disabled:opacity-50"
        >
          {state === "loading"
            ? "Running Distresse…"
            : "Stress-test this evidence in Distresse →"}
        </button>
      ) : (
        <div>
          {verdict.generatedBy.includes("sample") && (
            <p className="mb-2 text-[11px] text-amber-600 dark:text-amber-400">
              ⚠ SAMPLE — placeholder scoring, not a real model.
            </p>
          )}
          <div className="flex items-center gap-2">
            <span className="eyebrow">Distresse</span>
            <Badge tone={ratingTone[verdict.rating]}>{verdict.rating}</Badge>
            <span className="text-xs text-muted">
              conviction {verdict.conviction}/100
            </span>
          </div>
          <p className="mt-2 text-sm text-foreground/80">{verdict.bottomLine}</p>
          <p className="mt-2 text-[11px] text-muted">{verdict.generatedBy}</p>
        </div>
      )}
      {state === "error" && (
        <p className="text-xs text-rose-500">Couldn&apos;t reach Distresse.</p>
      )}
    </div>
  );
}

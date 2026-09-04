"use client";

import { useState } from "react";
import type {
  EquityExport,
  SecurityAnalysis,
  RankingEntry,
} from "@/lib/models/incepta-export";
import { Badge } from "@/components/ui";
import { ScoreBar } from "@/components/ScoreBar";
import { SecurityCard } from "@/components/panels/ModelPanels";

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

// SecurityCard (and its MetricGroup/StressAction helpers) now live in
// components/panels/ModelPanels.tsx — shared with StressTestClient and the
// Ticker Hub so every page renders a ticker's fundamentals identically.

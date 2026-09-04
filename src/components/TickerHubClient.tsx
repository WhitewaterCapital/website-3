"use client";

// TICKER HUB — one search bar, every model's read on the ticker in one place.
// Enter a commodity, equity, or FX ticker and this runs the real engines that
// apply to it (Distresse + Entry & Exit always; WW-Weekly's rank and Incepta's
// equity fundamentals when the ticker is actually covered by them) and lays
// the results out as one breakdown. A second ticker turns it into a
// side-by-side comparison. This is additive — the individual model pages
// (Stress Test, Entry & Exit, Weekly, Sentiment) are unchanged and still work
// on their own; this is the "give me everything on this name" front door.

import { useState } from "react";
import { Card, Badge } from "@/components/ui";
import { DistressePanel, IntraPanel, SecurityCard } from "@/components/panels/ModelPanels";
import type { Instrument, StressVerdict, EntryExitPlan } from "@/lib/models/types";
import type { WeeklyForecast } from "@/lib/models/weekly-export";
import type { SecurityAnalysis } from "@/lib/models/incepta-export";

type AssetClass = "equity" | "commodity" | "fx";

const ASSET_CLASSES: { value: AssetClass; label: string; placeholder: string }[] = [
  { value: "equity", label: "Equity", placeholder: "e.g. NVDA" },
  { value: "commodity", label: "Commodity", placeholder: "e.g. CL, GC" },
  { value: "fx", label: "FX", placeholder: "e.g. EURUSD" },
];

const INSTRUMENTS: { value: Instrument; label: string }[] = [
  { value: "long", label: "Long" },
  { value: "short", label: "Short" },
  { value: "call", label: "Call option" },
  { value: "put", label: "Put option" },
  { value: "future", label: "Future" },
];

type Breakdown = {
  ticker: string;
  assetClass: AssetClass;
  instrument: Instrument;
  status: "loading" | "done" | "error";
  error?: string;
  distresse?: StressVerdict;
  intra?: EntryExitPlan;
  weekly: { covered: boolean; universeSize: number; forecast: WeeklyForecast | null } | null;
  equity: { attempted: boolean; status: "loading" | "ok" | "unavailable"; security?: SecurityAnalysis | null; message?: string };
};

async function fetchWeekly(ticker: string): Promise<Breakdown["weekly"]> {
  try {
    const res = await fetch(`/api/models/weekly?ticker=${encodeURIComponent(ticker.trim().toUpperCase())}`, {
      cache: "no-store",
    });
    const data = await res.json();
    if (!data.synced) return null;
    return {
      covered: Boolean(data.covered),
      universeSize: Number(data.universeSize) || 0,
      forecast: data.forecast ?? null,
    };
  } catch {
    return null;
  }
}

async function runBreakdown(ticker: string, assetClass: AssetClass, instrument: Instrument): Promise<Breakdown> {
  const stressPromise = fetch("/api/models/stress", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticker, instrument, thesis: "" }),
  })
    .then((r) => r.json())
    .catch(() => null);

  const weeklyPromise = fetchWeekly(ticker);

  const equityPromise =
    assetClass === "equity"
      ? fetch("/api/models/equity/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ ticker }),
        })
          .then((r) => r.json())
          .catch(() => ({ status: "unavailable", message: "Couldn't reach the equity engine." }))
      : Promise.resolve(null);

  const [stressRes, weekly, equityRes] = await Promise.all([stressPromise, weeklyPromise, equityPromise]);

  return {
    ticker: ticker.toUpperCase(),
    assetClass,
    instrument,
    status: stressRes?.distresse && stressRes?.intra ? "done" : "error",
    error: stressRes?.error ?? (!stressRes ? "Couldn't reach the model engines." : undefined),
    distresse: stressRes?.distresse,
    intra: stressRes?.intra,
    weekly,
    equity: {
      attempted: assetClass === "equity",
      status: equityRes?.status === "ok" ? "ok" : "unavailable",
      security: equityRes?.status === "ok" ? equityRes.security : null,
      message: equityRes?.message,
    },
  };
}

export function TickerHubClient() {
  const [compare, setCompare] = useState(false);
  const [assetClass, setAssetClass] = useState<AssetClass>("equity");
  const [instrument, setInstrument] = useState<Instrument>("long");
  const [tickerA, setTickerA] = useState("");
  const [tickerB, setTickerB] = useState("");
  const [loading, setLoading] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [results, setResults] = useState<Breakdown[] | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setFormError(null);
    const tickers = [tickerA.trim()].concat(compare ? [tickerB.trim()] : []).filter(Boolean);
    if (tickers.length === 0) {
      setFormError("Enter at least one ticker.");
      return;
    }
    setLoading(true);
    setResults(null);
    try {
      const out = await Promise.all(tickers.map((t) => runBreakdown(t, assetClass, instrument)));
      setResults(out);
    } finally {
      setLoading(false);
    }
  }

  const activeClass = ASSET_CLASSES.find((c) => c.value === assetClass)!;

  return (
    <div className="space-y-8">
      <Card title="Search">
        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-[1fr_1fr_1fr]">
            <label className="block">
              <span className="eyebrow">Asset class</span>
              <select
                value={assetClass}
                onChange={(e) => setAssetClass(e.target.value as AssetClass)}
                className="mt-1 w-full border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
              >
                {ASSET_CLASSES.map((c) => (
                  <option key={c.value} value={c.value}>
                    {c.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="eyebrow">Ticker</span>
              <input
                value={tickerA}
                onChange={(e) => setTickerA(e.target.value.toUpperCase())}
                placeholder={activeClass.placeholder}
                className="mt-1 w-full border border-hairline bg-background px-3 py-2 text-sm uppercase outline-none focus:border-foreground/40"
              />
            </label>
            <label className="block">
              <span className="eyebrow">Direction</span>
              <select
                value={instrument}
                onChange={(e) => setInstrument(e.target.value as Instrument)}
                className="mt-1 w-full border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
              >
                {INSTRUMENTS.map((i) => (
                  <option key={i.value} value={i.value}>
                    {i.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="flex items-center gap-2 text-sm text-foreground/80">
            <input
              type="checkbox"
              checked={compare}
              onChange={(e) => setCompare(e.target.checked)}
              className="h-4 w-4"
            />
            Compare against a second ticker
          </label>

          {compare && (
            <label className="block max-w-xs">
              <span className="eyebrow">Compare to</span>
              <input
                value={tickerB}
                onChange={(e) => setTickerB(e.target.value.toUpperCase())}
                placeholder={activeClass.placeholder}
                className="mt-1 w-full border border-hairline bg-background px-3 py-2 text-sm uppercase outline-none focus:border-foreground/40"
              />
            </label>
          )}

          {formError ? <p className="text-sm text-rose-500">{formError}</p> : null}

          <button
            disabled={loading}
            className="bg-foreground px-5 py-2.5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
          >
            {loading ? "Running every model…" : "Get the full breakdown"}
          </button>
        </form>
      </Card>

      {results && (
        <div className={`grid gap-8 ${results.length > 1 ? "lg:grid-cols-2" : ""}`}>
          {results.map((r) => (
            <TickerBreakdown key={r.ticker} r={r} />
          ))}
        </div>
      )}
    </div>
  );
}

function TickerBreakdown({ r }: { r: Breakdown }) {
  return (
    <div className="space-y-6">
      <div className="flex items-baseline gap-2">
        <h2 className="text-2xl font-semibold">{r.ticker}</h2>
        <Badge tone="neutral">{r.assetClass}</Badge>
        <Badge tone="neutral">{r.instrument}</Badge>
      </div>

      {r.status === "error" ? (
        <Card title="Couldn't run this one">
          <p className="text-sm text-rose-500">{r.error ?? "Something went wrong."}</p>
        </Card>
      ) : (
        <>
          <div className="grid gap-6 md:grid-cols-2">
            {r.distresse && <DistressePanel v={r.distresse} />}
            {r.intra && <IntraPanel p={r.intra} />}
          </div>

          <WeeklyCard weekly={r.weekly} />

          {r.assetClass === "equity" ? (
            <Card title="Equity fundamentals">
              {r.equity.status === "ok" && r.equity.security ? (
                <SecurityCard s={r.equity.security} showStressAction={false} />
              ) : (
                <p className="text-sm text-muted">
                  {r.equity.message ??
                    `No usable Incepta data for ${r.ticker} — the engine abstains rather than show made-up numbers.`}
                </p>
              )}
            </Card>
          ) : (
            <Card title="Equity fundamentals">
              <p className="text-sm text-muted">
                Not applicable — Incepta&apos;s fundamentals (SEC filings, valuation, quality) only cover equities. Marked as{" "}
                {r.assetClass} here.
              </p>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

function WeeklyCard({ weekly }: { weekly: Breakdown["weekly"] }) {
  return (
    <Card title="Weekly Ranking">
      {!weekly ? (
        <p className="text-sm text-muted">WW-Weekly hasn&apos;t exported yet.</p>
      ) : !weekly.covered ? (
        <p className="text-sm text-muted">
          Not in WW-Weekly&apos;s {weekly.universeSize}-name research universe — no cross-sectional rank signal for this
          ticker.
        </p>
      ) : weekly.forecast ? (
        <>
          <div className="flex items-baseline justify-between">
            <span className="text-sm text-muted">Decile (10 = most bullish this week)</span>
            <span className="text-lg font-semibold tabular-nums">{weekly.forecast.decile ?? "—"} / 10</span>
          </div>
          <div className="mt-4 grid grid-cols-3 gap-4 text-center">
            <QuantileField label="p10" v={weekly.forecast.quantile_p10} />
            <QuantileField label="p50" v={weekly.forecast.quantile_p50} />
            <QuantileField label="p90" v={weekly.forecast.quantile_p90} />
          </div>
          <p className="mt-4 text-[11px] text-muted">
            {weekly.forecast.model_version} · OOS rank IC {weekly.forecast.rank_ic_oos ?? "—"}
            {weekly.forecast.provisional ? " · provisional" : ""}
          </p>
        </>
      ) : (
        <p className="text-sm text-muted">Covered by WW-Weekly, but no forecast row this run.</p>
      )}
    </Card>
  );
}

function QuantileField({ label, v }: { label: string; v: number | null }) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div className={`mt-1 text-sm font-semibold tabular-nums ${v != null && v > 0 ? "text-emerald-500" : v != null && v < 0 ? "text-rose-500" : ""}`}>
        {v == null ? "—" : `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`}
      </div>
    </div>
  );
}

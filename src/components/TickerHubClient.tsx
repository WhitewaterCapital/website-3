"use client";

// TICKER HUB — one search bar, every model's read on the ticker in one place.
// Enter a commodity, equity, or FX ticker and this runs the real engines that
// apply to it (Distresse + Entry & Exit always; WW-Weekly's rank, Incepta's
// equity fundamentals, and WW-Insider's SEC Form 4 read when the ticker is
// actually covered by them) and lays the results out as one breakdown. A
// second ticker turns it into a side-by-side comparison. This is additive —
// the individual model pages
// (Stress Test, Entry & Exit, Weekly, Sentiment) are unchanged and still work
// on their own; this is the "give me everything on this name" front door.

import { useState } from "react";
import { Card, Badge, Stat } from "@/components/ui";
import { DistressePanel, IntraPanel, OptionsPanel, InsiderPanel, SecurityCard } from "@/components/panels/ModelPanels";
import { FactorPanel } from "@/components/panels/FactorPanel";
import type { Instrument, StressVerdict, EntryExitPlan } from "@/lib/models/types";
import type { WeeklyForecast } from "@/lib/models/weekly-export";
import type { SecurityAnalysis } from "@/lib/models/incepta-export";
import type { OptionsSummary } from "@/lib/models/options-export";
import type { FactorExposure, FactorDataProvenance } from "@/lib/models/factor-export";
import type { TickerSentimentResult } from "@/lib/sentiment/types";
import { THIRTEEN_F_GAP_REASON, type InsiderReading } from "@/lib/models/insider-export";
import {
  computeConviction,
  WEEKLY_FORECAST_SLOT,
  INSIDER_ACTIVITY_SLOT,
  MAX_SINGLE_MODEL_SWING,
  type ConvictionSlotInput,
} from "@/lib/models/conviction";

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
  sentiment: TickerSentimentResult | null;
  options: OptionsSummary | null;
  factor: { covered: boolean; universeSize: number; dataProvenance: FactorDataProvenance; exposure: FactorExposure | null } | null;
  insider: InsiderReading | null;
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

// Company name (when known — Incepta's SecurityAnalysis.name, equities
// only) widens the news search so a headline naming the company but not the
// ticker symbol is still found — see lib/sentiment/headlines.ts::buildQuery.
// Never blocks the breakdown: a failed/slow sentiment fetch degrades to
// `null`, same as fetchWeekly above, rather than failing the whole lookup.
async function fetchSentiment(ticker: string, companyName: string | null): Promise<TickerSentimentResult | null> {
  try {
    const qs = new URLSearchParams({ ticker: ticker.trim().toUpperCase() });
    if (companyName) qs.set("name", companyName);
    const res = await fetch(`/api/models/sentiment?${qs.toString()}`, { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as TickerSentimentResult;
  } catch {
    return null;
  }
}

// WW-FACTOR's fixed-universe coverage check — same shape as fetchWeekly
// above (a small, static export the site reads through /api/models/factor).
// Degrades to `null` on a network hiccup exactly like fetchWeekly/
// fetchSentiment/fetchOptions.
async function fetchFactor(ticker: string): Promise<Breakdown["factor"]> {
  try {
    const res = await fetch(`/api/models/factor?ticker=${encodeURIComponent(ticker.trim().toUpperCase())}`, {
      cache: "no-store",
    });
    const data = await res.json();
    if (!data.synced) return null;
    return {
      covered: Boolean(data.covered),
      universeSize: Number(data.universeSize) || 0,
      dataProvenance: data.dataProvenance ?? "synthetic-demo",
      exposure: data.exposure ?? null,
    };
  } catch {
    return null;
  }
}

// Real Alpha Vantage options/IV read — see /api/models/options and
// lib/whitewatch-data/alphavantage-options.js for the full source
// verification writeup (including the genuinely unresolved question of
// whether Alpha Vantage's options endpoint even works on a free API key).
// Degrades to `null` on a network hiccup exactly like fetchWeekly/
// fetchSentiment above; a genuine "no options for this ticker", "not
// configured", "not on this plan", or "rate limited" state is NOT this —
// those come back as a normal 200 with a `status` field, which OptionsPanel
// renders honestly (see that component).
async function fetchOptions(ticker: string): Promise<OptionsSummary | null> {
  try {
    const res = await fetch(`/api/models/options?ticker=${encodeURIComponent(ticker.trim().toUpperCase())}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as OptionsSummary;
  } catch {
    return null;
  }
}

// Live SEC EDGAR Form 4 insider-activity read — see /api/models/insider and
// lib/whitewatch-data/edgar-sources.js for the full source verification
// writeup. Only attempted for equity tickers (Form 4 only exists for SEC-
// registered equity issuers — same gating as equityPromise below). Degrades
// to `null` on a network hiccup exactly like fetchWeekly/fetchSentiment/
// fetchOptions above — that is a DIFFERENT thing from the route's own
// status:"not_found"/"unreachable" (a successful response that itself
// reports SEC couldn't be reached for this ticker); InsiderPanel and
// missingSignalReasons below both know how to render/explain that inner
// status. `null` here means this app's own /api/models/insider route
// couldn't be reached at all.
async function fetchInsider(ticker: string): Promise<InsiderReading | null> {
  try {
    const res = await fetch(`/api/models/insider?ticker=${encodeURIComponent(ticker.trim().toUpperCase())}`, {
      cache: "no-store",
    });
    if (!res.ok) return null;
    return (await res.json()) as InsiderReading;
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

  // Fired in parallel with everything else, ticker-only (no company name —
  // that would mean waiting on equityPromise first, which would slow down
  // every lookup just to widen a news search). See fetchSentiment's own
  // comment: a company name is a nice-to-have query widener, not required.
  const sentimentPromise = fetchSentiment(ticker, null);

  const optionsPromise = fetchOptions(ticker);

  const factorPromise = fetchFactor(ticker);

  // Form 4 insider filings only exist for SEC-registered equity issuers —
  // same asset-class gating as equityPromise, avoids a doomed lookup
  // (ticker directory just won't have "CL" or "EURUSD" in it) for a
  // commodity/FX ticker.
  const insiderPromise = assetClass === "equity" ? fetchInsider(ticker) : Promise.resolve(null);

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

  const [stressRes, weekly, equityRes, sentiment, options, factor, insider] = await Promise.all([
    stressPromise,
    weeklyPromise,
    equityPromise,
    sentimentPromise,
    optionsPromise,
    factorPromise,
    insiderPromise,
  ]);

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
    sentiment,
    options,
    factor,
    insider,
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
          <VerdictCard r={r} />

          <div className="grid gap-6 md:grid-cols-2">
            {r.distresse && <DistressePanel v={r.distresse} />}
            {r.intra && <IntraPanel p={r.intra} />}
          </div>

          <WeeklyCard weekly={r.weekly} />

          <FactorCard factor={r.factor} ticker={r.ticker} />

          {r.options && <OptionsPanel o={r.options} p={r.intra} />}

          <SentimentPanel sentiment={r.sentiment} />

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

          {r.assetClass === "equity" ? (
            <InsiderPanel
              r={
                r.insider ?? {
                  status: "unreachable",
                  ticker: r.ticker,
                  message: "Couldn't reach the insider-activity engine for this ticker.",
                  thirteenF: { supported: false, reason: THIRTEEN_F_GAP_REASON },
                  generatedBy: "SEC EDGAR Form 4 (data.sec.gov / www.sec.gov) — live, keyless",
                }
              }
            />
          ) : (
            <Card title="Insider activity (WW-Insider)">
              <p className="text-sm text-muted">
                Not applicable — SEC Form 4 insider-transaction filings only exist for SEC-registered equity issuers.
                Marked as {r.assetClass} here.
              </p>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════
// Verdict — one composite read built on top of Distresse + (where available)
// WW-Weekly and Incepta, via conviction.ts's already-built computeConviction
// (IMP-15). This card does NOT reimplement any scoring math — it only maps
// each real model's already-existing fields onto conviction.ts's slot
// contract and renders the result. WW-Graph and WW-Cascade are intentionally
// left out (see conviction.ts's reserved GRAPH_RESIDUAL_SLOT /
// CASCADE_EXPOSURE_SLOT): there is no live graph export or portfolio-holdings
// data in this environment to back either one honestly, so no slot is wired
// for them rather than feeding in placeholder numbers.
//
// baseScore / baseConfidence — from Distresse's existing StressVerdict:
//   baseScore = v.conviction. conviction.ts's own ConvictionSlotInput doc
//   comment names StressVerdict.conviction directly as the exact "already-
//   composited, unsigned 0..100, how-sure-are-we" scale computeConviction's
//   baseScore parameter expects — so this is the mapping the module already
//   documents, not a guessed one.
//   baseConfidence = 0.75 for a real Distresse read, 0.4 when
//   generatedBy contains "(sample)" (the same check DistressePanel uses for
//   its amber "SAMPLE — placeholder scoring" banner). StressVerdict carries
//   no separate confidence field, so the one real reliability signal it does
//   carry — demo RNG vs. a real model — is what drives this, rather than
//   re-deriving a second number out of conviction itself.
//
// WW-Weekly slot (WEEKLY_FORECAST_SLOT, reserved by conviction.ts): added
//   only when r.weekly.covered and forecast.decile is present.
//   score = ((decile - 5.5) / 4.5) * 100 — decile (1..10, 10 = most bullish
//   that week, per weekly-export.ts) is the one bounded, ready-made
//   cross-sectional read WeeklyCard already leads with, linearly mapped so
//   decile 10 -> +100, decile 1 -> -100, and 5/6 straddle zero.
//   confidence = 0.25 when forecast.provisional, else 0.45 — capped well
//   under 1 either way because weekly-export.ts's own header comment calls
//   this "a low-predictability, research-grade RANK signal, not price
//   targets".
//
// Also deliberately left out: the Alpha Vantage options/implied-volatility
// read (OptionsPanel, below WeeklyCard) — a different reason from WW-Graph/
// WW-Cascade's "no live data yet". Here the data is real (when it resolves
// at all — see alphavantage-options.js for the honest caveats about the
// free tier's request budget and its unresolved plan-gating question), but
// ATM implied vol / expected-move is a MAGNITUDE, not a directional opinion
// (a straddle price can't be negative) — conviction.ts's ConvictionSlotInput
// documents `score` as a SIGNED directional/quality read, and there is no
// honest sign to assign "the market expects a ±6% move." Put/call open
// interest ratio has a loose directional flavor but is a noisy, contested
// heuristic (elevated put OI is equally explained by covered-call writers,
// protective hedgers, or market-maker inventory) — not a vetted opinion on
// the level of Distresse's stress test or Incepta's quality composite. Full
// reasoning lives on OptionsPanel itself (components/panels/ModelPanels.tsx).
//
// Incepta equity slot (modelId "equity" — the SAME id equity.ts's
//   ModelMeta.id and horizons.ts's HORIZON_REGISTRY use, so the real "1-3m"
//   horizon band shows up in the breakdown below instead of "unspecified"):
//   added only for an equity ticker where Incepta didn't abstain
//   (confidence !== "insufficient") and quality.piotroski_f is present.
//   score = ((piotroski_f - 4.5) / 4.5) * 100 — Piotroski F (0..9) is the
//   bounded quality composite SecurityCard already headlines.
//   confidence follows Incepta's own label: high 0.8, medium 0.55, low 0.3.
//
// WW-Insider slot (INSIDER_ACTIVITY_SLOT, reserved by conviction.ts — see
//   that file's IMP-22 comment): added only for an equity ticker where
//   r.insider.status is "ok" AND summary.signalTransactionCount > 0 — i.e.
//   SEC EDGAR was actually reached, the ticker resolved to a real CIK, AND
//   there was at least one real open-market buy/sell Form 4 transaction to
//   base a score on. Per this task's explicit requirement: a ticker with
//   zero coverage (not_found), an unreachable EDGAR, or zero signal
//   transactions in the window is a MISSING signal (see
//   missingSignalReasons below), never a fabricated zero-conviction slot.
//   score = edgar-sources.js's summarizeInsiderActivity().score — already a
//   -100..100 dollar-weighted net buy(+)/sell(-) direction over the
//   open-market (P/S) transactions in the window, so no remapping is done
//   here (unlike the linear rescales above) — the underlying number is
//   already on conviction.ts's documented slot scale.
//   confidence = that same summary's confidence, which saturates only once
//   the read rests on CONFIDENCE_SATURATION_COUNT (10) independent P/S
//   transactions — see edgar-sources.js for why 2 trades from one insider's
//   own pre-scheduled plan must carry far less weight than a dozen
//   independent ones.
// ═══════════════════════════════════════════════════════════════════════════

const EQUITY_CONVICTION_SLOT = "equity"; // matches equity.ts's ModelMeta.id / horizons.ts's HORIZON_REGISTRY entry

function weeklyConvictionSlot(weekly: Breakdown["weekly"]): ConvictionSlotInput | null {
  const decile = weekly?.covered ? weekly.forecast?.decile : null;
  if (decile == null) return null;
  return {
    modelId: WEEKLY_FORECAST_SLOT,
    score: ((decile - 5.5) / 4.5) * 100,
    confidence: weekly?.forecast?.provisional ? 0.25 : 0.45,
  };
}

function equityConvictionSlot(r: Breakdown): ConvictionSlotInput | null {
  if (r.assetClass !== "equity" || r.equity.status !== "ok" || !r.equity.security) return null;
  const s = r.equity.security;
  if (s.confidence === "insufficient") return null;
  const f = s.quality?.piotroski_f;
  if (f == null) return null;
  const confidence = { high: 0.8, medium: 0.55, low: 0.3 }[s.confidence];
  return {
    modelId: EQUITY_CONVICTION_SLOT,
    score: ((f - 4.5) / 4.5) * 100,
    confidence,
  };
}

function insiderConvictionSlot(r: Breakdown): ConvictionSlotInput | null {
  if (r.assetClass !== "equity" || !r.insider || r.insider.status !== "ok" || !r.insider.summary) return null;
  const { score, confidence, signalTransactionCount } = r.insider.summary;
  // score is null (edgar-sources.js's own convention) and
  // signalTransactionCount is 0 together whenever there were zero
  // open-market P/S transactions — that's "no signal", not "score of 0";
  // never contribute a fabricated neutral slot for it.
  if (score == null || signalTransactionCount === 0) return null;
  return { modelId: INSIDER_ACTIVITY_SLOT, score, confidence };
}

// Honest accounting of which of the (up to 4) possible signals actually fed
// the composite for THIS ticker, and why any that didn't are missing — an
// equity ticker has 4 possible signals (Distresse + WW-Weekly + Incepta +
// WW-Insider), a commodity/FX ticker has 2 (neither Incepta nor WW-Insider
// cover non-equities at all, so neither is ever counted as "possible"
// there, matching the "Not applicable" cards already shown below for that
// case).
function missingSignalReasons(r: Breakdown, hasWeekly: boolean, hasEquity: boolean, hasInsider: boolean): string[] {
  const reasons: string[] = [];
  if (!hasWeekly) {
    if (!r.weekly) reasons.push("WW-Weekly hasn't exported yet.");
    else if (!r.weekly.covered) reasons.push(`WW-Weekly has no coverage for ${r.ticker}.`);
    else reasons.push("WW-Weekly is covered but has no usable decile this run.");
  }
  if (r.assetClass === "equity" && !hasEquity) {
    if (r.equity.status !== "ok" || !r.equity.security) {
      reasons.push(r.equity.message ?? "No usable Incepta data for this ticker.");
    } else if (r.equity.security.confidence === "insufficient") {
      reasons.push("Incepta abstained (insufficient data) for this ticker.");
    } else {
      reasons.push("Incepta has no Piotroski quality composite for this ticker.");
    }
  }
  if (r.assetClass === "equity" && !hasInsider) {
    if (!r.insider) reasons.push("Couldn't reach the insider-activity engine for this ticker.");
    else if (r.insider.status === "not_found") reasons.push(r.insider.message ?? `SEC has no CIK for ${r.ticker}.`);
    else if (r.insider.status === "unreachable") reasons.push(r.insider.message ?? "SEC EDGAR was unreachable for this ticker.");
    else reasons.push(`No open-market insider buying/selling for ${r.ticker} in the last ${r.insider.windowDays} days.`);
  }
  return reasons;
}

// A composite point sits meaningfully above Distresse's own conviction floor
// (40, per distresse.ts — conviction is never computed below that) once it
// clears LEAN_FULL_THRESHOLD; between the floor and that line the read is
// called only tentative.
const LEAN_FULL_THRESHOLD = 55;
const LEAN_TENTATIVE_THRESHOLD = 40;

type Lean = { label: string; detail: string; bias: "long" | "short" | null };

// Directional lean — honestly derived from the composite (intensity, not
// direction on its own — StressVerdict.conviction is unsigned) plus Entry &
// Exit's own existing long/short call, per this task's instruction not to
// invent a confident "BUY" imperative. Never asserted alone: it is dropped
// to "No clear lean" whenever Entry & Exit abstained, or Distresse's rating
// actively disagrees with it, or the composite is too weak to back it.
function directionalLean(r: Breakdown, composite: number): Lean {
  if (!r.distresse || !r.intra) {
    return { label: "No clear lean", detail: "Missing model output for this ticker.", bias: null };
  }
  if (Number.isNaN(r.intra.stop)) {
    return {
      label: "No clear lean",
      detail: "Entry & Exit abstained on this ticker — there is no engine-recommended direction to lean on.",
      bias: null,
    };
  }
  const bias = r.intra.bias;
  if (r.distresse.rating === "no-go") {
    return {
      label: "No clear lean",
      detail: `Distresse rates this idea a no-go even though Entry & Exit has ${bias} levels — the two disagree, so this reads as flat, not a real ${bias} lean.`,
      bias: null,
    };
  }
  if (composite >= LEAN_FULL_THRESHOLD) {
    return {
      label: `Leans ${bias}`,
      detail: `Composite conviction is ${Math.round(composite)}/100 and Distresse rates it "${r.distresse.rating}" — consistent with Entry & Exit's ${bias} levels.`,
      bias,
    };
  }
  if (composite >= LEAN_TENTATIVE_THRESHOLD) {
    return {
      label: `Tentatively leans ${bias}`,
      detail: `Composite conviction (${Math.round(composite)}/100) is on the weaker side — Entry & Exit's ${bias} levels have some support, but not strongly.`,
      bias,
    };
  }
  return {
    label: "No clear lean",
    detail: `Composite conviction (${Math.round(composite)}/100) is too weak to back a direction, even though Entry & Exit nominally has ${bias} levels.`,
    bias: null,
  };
}

const leanTone = (bias: Lean["bias"]) => (bias === "long" ? "up" : bias === "short" ? "down" : "neutral") as const;

function slotLabel(modelId: string): string {
  if (modelId === WEEKLY_FORECAST_SLOT) return "WW-Weekly";
  if (modelId === EQUITY_CONVICTION_SLOT) return "Incepta";
  if (modelId === INSIDER_ACTIVITY_SLOT) return "WW-Insider";
  return modelId;
}

function slotDetail(modelId: string, r: Breakdown): string {
  if (modelId === WEEKLY_FORECAST_SLOT) {
    const d = r.weekly?.forecast?.decile;
    return d == null ? "decile n/a" : `decile ${d}/10`;
  }
  if (modelId === EQUITY_CONVICTION_SLOT) {
    const q = r.equity.security?.quality;
    return q?.piotroski_f == null ? "Piotroski n/a" : `Piotroski ${q.piotroski_f}/${q.piotroski_max ?? 9}`;
  }
  if (modelId === INSIDER_ACTIVITY_SLOT) {
    const s = r.insider?.summary;
    return s == null ? "no signal txns" : `${s.signalTransactionCount} txns, ${s.distinctInsiders} insider${s.distinctInsiders === 1 ? "" : "s"}`;
  }
  return "";
}

function VerdictCard({ r }: { r: Breakdown }) {
  const [showBreakdown, setShowBreakdown] = useState(false);
  if (!r.distresse) return null; // guaranteed present on the "done" path this is rendered on; guarded for type-safety only

  const v = r.distresse;
  const isSample = v.generatedBy.includes("(sample)");
  const baseScore = v.conviction;
  const baseConfidence = isSample ? 0.4 : 0.75;

  const wSlot = weeklyConvictionSlot(r.weekly);
  const eSlot = equityConvictionSlot(r);
  const iSlot = insiderConvictionSlot(r);
  const slots = [wSlot, eSlot, iSlot].filter((s): s is ConvictionSlotInput => s !== null);

  const result = computeConviction(baseScore, baseConfidence, slots);
  const lean = directionalLean(r, result.composite);

  const possible = r.assetClass === "equity" ? 4 : 2; // Distresse + WW-Weekly (+ Incepta + WW-Insider for equities only)
  const available = 1 + (wSlot ? 1 : 0) + (eSlot ? 1 : 0) + (iSlot ? 1 : 0);
  const missing = missingSignalReasons(r, Boolean(wSlot), Boolean(eSlot), Boolean(iSlot));

  const gaugeTone = result.composite >= LEAN_FULL_THRESHOLD ? "up" : result.composite < LEAN_TENTATIVE_THRESHOLD ? "down" : "neutral";

  return (
    <Card title="Verdict" action={<Badge tone={leanTone(lean.bias)}>{lean.label}</Badge>}>
      <div className="grid gap-6 sm:grid-cols-[auto_1fr] sm:items-start">
        <Stat label="Composite conviction" value={Math.round(result.composite)} sub="out of 100" tone={gaugeTone} />

        <div className="space-y-3">
          <p className="text-sm text-foreground/80">
            {Math.round(result.composite)}/100 blends Distresse&apos;s stress-test conviction (currently rated &quot;{v.rating}
            &quot;) with WW-Weekly&apos;s rank, Incepta&apos;s quality read, and WW-Insider&apos;s SEC Form 4 read
            wherever each is actually available for {r.ticker}. It&apos;s a &quot;how much do the available models
            agree&quot; reading on a 0-100 scale — not a
            probability of any specific price move, and not a buy/sell instruction on its own.
          </p>

          <p className="text-xs text-muted">
            Confidence {Math.round(result.confidence * 100)}% — based on {available} of {possible} possible signal
            {possible === 1 ? "" : "s"} for {r.ticker}.{missing.length > 0 ? ` Missing: ${missing.join(" ")}` : ""}
          </p>

          <p className="text-sm">
            <span className="font-medium">{lean.label}.</span> <span className="text-foreground/80">{lean.detail}</span>
          </p>
        </div>
      </div>

      <button
        onClick={() => setShowBreakdown((s) => !s)}
        className="mt-5 text-xs font-medium text-accent hover:underline"
      >
        {showBreakdown ? "Hide" : "Show"} how this number was built →
      </button>
      {showBreakdown && (
        <ul className="mt-3 space-y-1.5 border-t border-hairline pt-3">
          <li className="text-sm text-foreground/80">
            Distresse: base {baseScore}/100 ({isSample ? "sample scoring" : "real read"}, rated &quot;{v.rating}&quot;)
          </li>
          {result.slotContributions.map((c) => (
            <li key={c.modelId} className="text-sm text-foreground/80">
              {slotLabel(c.modelId)}: {c.delta >= 0 ? "+" : ""}
              {c.delta.toFixed(1)} ({slotDetail(c.modelId, r)}) · horizon {c.horizon}
            </li>
          ))}
          {slots.length === 0 && (
            <li className="text-sm text-muted">No additional signals available — composite is Distresse&apos;s base read alone.</li>
          )}
        </ul>
      )}

      <p className="mt-4 text-[11px] text-muted">
        Each added signal is capped at ±{MAX_SINGLE_MODEL_SWING} composite points (conviction.ts, IMP-15) — no single
        one, however extreme, can flip this on its own.
      </p>
    </Card>
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

// WW-FACTOR — Fama-French factor exposure. Same "not in the research
// universe" honesty shape as WeeklyCard above (a small, fixed, static
// export — see factor-engine/README.md's "Why a small fixed universe, not
// 'any ticker on demand'"). NOT a conviction.ts slot: see
// components/panels/FactorPanel.tsx's own top-of-file comment for the full
// reasoning — a factor beta describes a style tilt, not a direction.
function FactorCard({ factor, ticker }: { factor: Breakdown["factor"]; ticker: string }) {
  if (!factor) {
    return (
      <Card title="Factor exposure (Fama-French)">
        <p className="text-sm text-muted">WW-Factor hasn&apos;t exported yet.</p>
      </Card>
    );
  }
  if (!factor.covered) {
    return (
      <Card title="Factor exposure (Fama-French)">
        <p className="text-sm text-muted">
          Not in WW-Factor&apos;s {factor.universeSize}-name research universe — no factor-exposure read for {ticker}
          . See factor-engine/README.md for why this universe is small and fixed today.
        </p>
      </Card>
    );
  }
  if (!factor.exposure) {
    return (
      <Card title="Factor exposure (Fama-French)">
        <p className="text-sm text-muted">Covered by WW-Factor, but no exposure row this run.</p>
      </Card>
    );
  }
  return <FactorPanel exposure={factor.exposure} dataProvenance={factor.dataProvenance} />;
}

// ═══════════════════════════════════════════════════════════════════════════
// WW-SENTIMENT — real headlines (Google News RSS), each individually scored
// by FinBERT (ProsusAI/finbert) via /api/models/sentiment. See that route
// and src/lib/sentiment/finbert.ts for the full verification writeup on the
// model/API and what is and isn't confirmed live from this codebase.
//
// WHY THIS PANEL IS STANDALONE, NOT A conviction.ts SLOT — the honest call
// this task asked for, made explicitly rather than by omission:
//
// conviction.ts already blends one clearly faster-than-structural signal in
// (WEEKLY_FORECAST_SLOT, "1w" horizon) alongside Distresse and Incepta. The
// reason that one is safe to blend is documented in this file's own
// weeklyConvictionSlot() comment and in weekly-engine/README.md: it is a
// BACKTESTED model with a measured, capped confidence (0.25-0.45) tied to
// its own known predictive power (rank IC), and macro-tracker's horizons.ts
// entry makes the same shape of argument — "the read itself is fast but the
// regime it describes moves on a monthly-to-quarterly cadence."
//
// News-headline sentiment does not have either property:
//   1. NO VALIDATED PREDICTIVE POWER. Unlike WW-Weekly, nothing in this
//      codebase has backtested whether recent headline sentiment on a name
//      predicts anything about it going forward. Wiring an unvalidated
//      signal into a composite that's meant to represent a multi-year-
//      relevant read (conviction.ts's own header comment) would be giving
//      it structural weight it hasn't earned.
//   2. NO SPEED GAP TO EXPLOIT. Macro's daily read works because the
//      REGIME it describes is slow even though the read is fast. A batch of
//      recent headlines has no such underlying slow phenomenon — the mood
//      IS the fast thing, not a fast proxy for something slower. horizons.ts
//      bands this at "1min-4h" (see that file's ww-sentiment entry) for
//      exactly this reason.
//   3. SMALL-SAMPLE FRAGILITY. A single extreme headline ("CEO resigns amid
//      fraud probe") can dominate a 2-3 headline batch for a thinly-covered
//      name. aggregate.ts's confidence formula discounts this correctly for
//      READING the number, but conviction.ts's cap mechanics were designed
//      and tuned (MAX_SINGLE_MODEL_SWING = 8, see that file's own comment)
//      around models like WW-Weekly and Incepta, not around a signal whose
//      noise floor is "one bad headline."
//
// This is the same kind of call already made once in this file — WW-Graph
// and WW-Cascade are deliberately left out of VerdictCard (see that card's
// own comment above) because there's no live data to back them honestly.
// Here the data IS live and real; what's missing is validated evidence that
// it belongs in a STRUCTURAL score. So: shown in full, individually
// attributed, right below the Verdict — never folded into its number.
// ═══════════════════════════════════════════════════════════════════════════

const sentimentLabelTone = {
  positive: "up",
  negative: "down",
  neutral: "neutral",
  unavailable: "warn",
} as const;

function formatHeadlineDate(iso: string | null): string {
  if (!iso) return "date unknown";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "date unknown";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function SentimentPanel({ sentiment }: { sentiment: Breakdown["sentiment"] }) {
  if (!sentiment) {
    return (
      <Card title="News sentiment (WW-Sentiment)">
        <p className="text-sm text-muted">Couldn&apos;t reach the sentiment engine for this ticker.</p>
      </Card>
    );
  }

  const { aggregate, headlines } = sentiment;
  const gaugeTone = aggregate.score == null ? "neutral" : aggregate.score > 10 ? "up" : aggregate.score < -10 ? "down" : "neutral";

  return (
    <Card
      title="News sentiment (WW-Sentiment)"
      action={
        <Badge tone={aggregate.method === "finbert" ? "up" : aggregate.method === "keyword-fallback" ? "warn" : "neutral"}>
          {aggregate.method === "finbert"
            ? "FinBERT"
            : aggregate.method === "mixed"
              ? "FinBERT + fallback"
              : aggregate.method === "keyword-fallback"
                ? "Keyword fallback"
                : "No read"}
        </Badge>
      }
    >
      {!sentiment.finbertConfigured && (
        <div className="mb-4 border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          ⚠ <strong>HF_API_KEY not set.</strong> Headlines below are shown unscored ("sentiment scoring
          unavailable") rather than a guessed or keyword-based number pretending to be a real model read. See
          .env.local.example for how to get a free Hugging Face token and what it costs.
        </div>
      )}

      {aggregate.abstained ? (
        <p className="text-sm text-muted">{aggregate.abstainReason}</p>
      ) : (
        <div className="grid gap-6 sm:grid-cols-[auto_1fr] sm:items-start">
          <Stat
            label="Sentiment read"
            value={aggregate.score == null ? "—" : `${aggregate.score > 0 ? "+" : ""}${aggregate.score.toFixed(0)}`}
            sub="-100 (bearish) .. +100 (bullish)"
            tone={gaugeTone}
          />
          <div className="space-y-2 text-sm text-foreground/80">
            <p>
              Confidence {Math.round(aggregate.confidence * 100)}% from {aggregate.nScored} scored headline
              {aggregate.nScored === 1 ? "" : "s"} of {aggregate.n} found in the last 14 days — deliberately scaled
              down for a thin sample (see aggregate.ts): a 2-headline read never carries the confidence a 20-headline
              read does, however extreme either one looks.
            </p>
            <p className="text-xs text-muted">
              {aggregate.counts.positive} positive · {aggregate.counts.negative} negative · {aggregate.counts.neutral}{" "}
              neutral{aggregate.counts.unavailable > 0 ? ` · ${aggregate.counts.unavailable} unscored` : ""}
            </p>
          </div>
        </div>
      )}

      {headlines.length > 0 && (
        <ul className="mt-5 space-y-2 border-t border-hairline pt-4">
          {headlines.map((h) => (
            <li key={h.id} className="flex flex-wrap items-start justify-between gap-2 text-sm">
              <a href={h.link} target="_blank" rel="noreferrer" className="flex-1 text-foreground/90 hover:underline">
                {h.title}
              </a>
              <span className="flex shrink-0 items-center gap-2 text-xs text-muted">
                {h.source} · {formatHeadlineDate(h.publishedAt)}
                <Badge tone={sentimentLabelTone[h.sentiment.label]}>
                  {h.sentiment.label}
                  {h.sentiment.method === "keyword-fallback" ? " (fallback)" : ""}
                </Badge>
              </span>
            </li>
          ))}
        </ul>
      )}

      <p className="mt-4 text-[11px] text-muted">
        Not included in the Verdict composite above — see this component&apos;s source comment for the full reasoning
        (short version: no backtested predictive power and a decay speed of hours, not weeks, unlike WW-Weekly's
        capped conviction slot).
      </p>
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

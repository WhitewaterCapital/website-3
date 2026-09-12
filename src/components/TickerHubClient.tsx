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
import { Card, Badge, Stat } from "@/components/ui";
import { DistressePanel, IntraPanel, SecurityCard } from "@/components/panels/ModelPanels";
import type { Instrument, StressVerdict, EntryExitPlan } from "@/lib/models/types";
import type { WeeklyForecast } from "@/lib/models/weekly-export";
import type { SecurityAnalysis } from "@/lib/models/incepta-export";
import {
  computeConviction,
  WEEKLY_FORECAST_SLOT,
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
          <VerdictCard r={r} />

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
// Incepta equity slot (modelId "equity" — the SAME id equity.ts's
//   ModelMeta.id and horizons.ts's HORIZON_REGISTRY use, so the real "1-3m"
//   horizon band shows up in the breakdown below instead of "unspecified"):
//   added only for an equity ticker where Incepta didn't abstain
//   (confidence !== "insufficient") and quality.piotroski_f is present.
//   score = ((piotroski_f - 4.5) / 4.5) * 100 — Piotroski F (0..9) is the
//   bounded quality composite SecurityCard already headlines.
//   confidence follows Incepta's own label: high 0.8, medium 0.55, low 0.3.
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

// Honest accounting of which of the (up to 3) possible signals actually fed
// the composite for THIS ticker, and why any that didn't are missing — an
// equity ticker has 3 possible signals (Distresse + WW-Weekly + Incepta), a
// commodity/FX ticker has 2 (Incepta doesn't cover non-equities at all, so
// it is never counted as "possible" there, matching the "Not applicable"
// card already shown below for that case).
function missingSignalReasons(r: Breakdown, hasWeekly: boolean, hasEquity: boolean): string[] {
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
  const slots = [wSlot, eSlot].filter((s): s is ConvictionSlotInput => s !== null);

  const result = computeConviction(baseScore, baseConfidence, slots);
  const lean = directionalLean(r, result.composite);

  const possible = r.assetClass === "equity" ? 3 : 2; // Distresse + WW-Weekly (+ Incepta for equities only)
  const available = 1 + (wSlot ? 1 : 0) + (eSlot ? 1 : 0);
  const missing = missingSignalReasons(r, Boolean(wSlot), Boolean(eSlot));

  const gaugeTone = result.composite >= LEAN_FULL_THRESHOLD ? "up" : result.composite < LEAN_TENTATIVE_THRESHOLD ? "down" : "neutral";

  return (
    <Card title="Verdict" action={<Badge tone={leanTone(lean.bias)}>{lean.label}</Badge>}>
      <div className="grid gap-6 sm:grid-cols-[auto_1fr] sm:items-start">
        <Stat label="Composite conviction" value={Math.round(result.composite)} sub="out of 100" tone={gaugeTone} />

        <div className="space-y-3">
          <p className="text-sm text-foreground/80">
            {Math.round(result.composite)}/100 blends Distresse&apos;s stress-test conviction (currently rated &quot;{v.rating}
            &quot;) with WW-Weekly&apos;s rank and Incepta&apos;s quality read wherever each is actually available for{" "}
            {r.ticker}. It&apos;s a &quot;how much do the available models agree&quot; reading on a 0-100 scale — not a
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

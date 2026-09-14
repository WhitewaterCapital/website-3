"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card } from "@/components/ui";
import { DistressePanel, IntraPanel, InstrumentFitPanel } from "@/components/panels/ModelPanels";
import type {
  StressVerdict,
  EntryExitPlan,
  Instrument,
  IdeaTimeframe,
  IdeaCatalystType,
} from "@/lib/models/types";
import type { OptionsSummary } from "@/lib/models/options-export";
import { assessInstrumentFit } from "@/lib/models/instrument-fit";
import type { InstrumentFitResult } from "@/lib/models/instrument-fit";

type Result = {
  distresse: StressVerdict;
  intra: EntryExitPlan;
};

const INSTRUMENTS: { value: Instrument; label: string }[] = [
  { value: "long", label: "Long stock" },
  { value: "short", label: "Short stock" },
  { value: "call", label: "Call option" },
  { value: "put", label: "Put option" },
  { value: "future", label: "Future" },
];

// What "long"/"short" alone doesn't say: the window this idea is meant to
// play out over. "Long AAPL" as a multi-quarter thesis and "long AAPL just
// for earnings" are different bets — this picks which one, and distresse.ts
// weights its six real dimensions differently depending on the answer (see
// that file's DIMENSION_RELEVANCE table). Default "position" reproduces the
// original undifferentiated read exactly.
const TIMEFRAMES: { value: IdeaTimeframe; label: string; hint: string }[] = [
  { value: "intraday", label: "Intraday", hint: "hours — closed today/next session" },
  { value: "swing", label: "Swing", hint: "days to a few weeks" },
  { value: "position", label: "Position", hint: "weeks to a few months" },
  { value: "long-term", label: "Long-term", hint: "6+ months" },
];

// What's actually expected to move it, if anything specific — independent of
// timeframe (an earnings bet can be held as a swing, or just the print).
const CATALYSTS: { value: IdeaCatalystType; label: string }[] = [
  { value: "general-thesis", label: "General thesis" },
  { value: "earnings", label: "Earnings print" },
  { value: "fed-macro-event", label: "Fed / macro event" },
  { value: "product-launch", label: "Product launch" },
  { value: "technical-level", label: "Technical level" },
];

// Reads an optional `?ticker=` query param so a caller (Trade Ideas'
// "Run Stress Test ->" links, e.g.) can land a member here with the field
// already filled in, instead of asking them to retype a symbol the app
// already knows. Additive only: prefills the form, never auto-submits — the
// member still reviews the idea's other fields (instrument, timeframe,
// catalyst, thesis) and presses Run themselves. `useSearchParams` requires
// a Suspense boundary around whatever reads it, hence the thin wrapper
// below; StressTestClient's own exported name/shape is unchanged, so every
// existing caller (this page, the dashboard's embedded copy) needs no edit.
export function StressTestClient() {
  return (
    <Suspense fallback={<StressTestClientInner initialTicker="" />}>
      <StressTestClientWithQuery />
    </Suspense>
  );
}

function StressTestClientWithQuery() {
  const searchParams = useSearchParams();
  const initialTicker = (searchParams.get("ticker") ?? "").trim().toUpperCase();
  return <StressTestClientInner initialTicker={initialTicker} />;
}

function StressTestClientInner({ initialTicker }: { initialTicker: string }) {
  const [ticker, setTicker] = useState(initialTicker);
  const [instrument, setInstrument] = useState<Instrument>("long");
  const [timeframe, setTimeframe] = useState<IdeaTimeframe>("position");
  const [catalystType, setCatalystType] = useState<IdeaCatalystType>("general-thesis");
  const [thesis, setThesis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  // Instrument Fit (src/lib/models/instrument-fit.ts) -- an ADDITIVE second
  // read, alongside Distresse/Entry & Exit above, on whether the chosen
  // instrument itself (not the thesis) fits the stated timeframe/catalyst.
  // Fetched from the same /api/models/options route OptionsPanel already
  // uses elsewhere (TickerHubClient); failure here never blocks the
  // Distresse/Entry & Exit results already rendered -- see the catch below.
  // Only the assessed InstrumentFitResult is kept in state -- the raw
  // OptionsSummary it was computed from isn't rendered separately here, so
  // it's held in a local variable inside run() rather than state.
  const [instrumentFit, setInstrumentFit] = useState<InstrumentFitResult | null>(null);
  const [instrumentFitLoading, setInstrumentFitLoading] = useState(false);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!ticker.trim()) {
      setError("Enter a ticker.");
      return;
    }
    setLoading(true);
    setInstrumentFit(null);
    try {
      const res = await fetch("/api/models/stress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, instrument, thesis, timeframe, catalystType }),
      });
      if (!res.ok) throw new Error((await res.json()).error ?? "Failed");
      setResult(await res.json());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
    }

    // Instrument Fit's options read runs as a SEPARATE, additive fetch after
    // the main Stress Test call above -- a slow or failed response here
    // (Alpha Vantage's free tier is rate-limited to roughly 25 requests/day
    // platform-wide, see options-export.ts's own header) must never block or
    // blank out the Distresse/Entry & Exit panels, which is why it isn't
    // awaited inside the try/finally that drives `loading`. It also doesn't
    // depend on the stress call having succeeded -- instrument fit is a read
    // on the idea's own fields (instrument/timeframe/catalyst) plus real
    // options data, independent of Distresse's verdict on the thesis.
    const resolvedTicker = ticker.trim().toUpperCase();
    setInstrumentFitLoading(true);
    try {
      const oRes = await fetch(`/api/models/options?ticker=${encodeURIComponent(resolvedTicker)}`);
      const oSummary = (await oRes.json()) as OptionsSummary;
      setInstrumentFit(
        assessInstrumentFit(
          { ticker: resolvedTicker, instrument, thesis, timeframe, catalystType },
          oSummary,
        ),
      );
    } catch {
      // A genuine fetch/parse failure here -- distinct from OptionsSummary's
      // own "error" status, which is a valid, handled response body this
      // route always returns 200 with. Leaves instrumentFit null so the UI
      // simply omits the Instrument Fit panel rather than rendering a broken
      // read.
      setInstrumentFit(null);
    } finally {
      setInstrumentFitLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      {/* Idea form */}
      <Card title="The idea">
        <form onSubmit={run} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-[1fr_1fr]">
            <label className="block">
              <span className="eyebrow">Ticker</span>
              <input
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                placeholder="NVDA"
                className="mt-1 w-full border border-hairline bg-background px-3 py-2 text-sm uppercase outline-none focus:border-foreground/40"
              />
            </label>
            <label className="block">
              <span className="eyebrow">Instrument</span>
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

          <div>
            <span className="eyebrow">Timeframe — what does &quot;{instrument === "short" || instrument === "put" ? "short" : "long"}&quot; mean here?</span>
            <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
              {TIMEFRAMES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  onClick={() => setTimeframe(t.value)}
                  title={t.hint}
                  className={`border px-3 py-2 text-left text-xs transition ${
                    timeframe === t.value
                      ? "border-accent bg-accent/10 text-foreground"
                      : "border-hairline text-muted hover:border-foreground/40 hover:text-foreground"
                  }`}
                >
                  <span className="block font-medium uppercase tracking-wide">{t.label}</span>
                  <span className="mt-0.5 block text-[10px] text-muted">{t.hint}</span>
                </button>
              ))}
            </div>
          </div>

          <label className="block">
            <span className="eyebrow">Catalyst — is this about one specific event?</span>
            <select
              value={catalystType}
              onChange={(e) => setCatalystType(e.target.value as IdeaCatalystType)}
              className="mt-1 w-full border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
            >
              {CATALYSTS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
            {catalystType === "earnings" && (
              <p className="mt-1 text-[11px] text-muted">
                Betting on the print itself — Distresse leans on news/positioning going into it and
                de-emphasizes valuation and the macro regime, which say almost nothing about which way
                a single earnings print goes.
              </p>
            )}
          </label>

          <label className="block">
            <span className="eyebrow">Thesis</span>
            <textarea
              value={thesis}
              onChange={(e) => setThesis(e.target.value)}
              rows={3}
              placeholder="Why this, why now, what you expect to happen."
              className="mt-1 w-full resize-y border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
            />
          </label>
          {error ? <p className="text-sm text-rose-500">{error}</p> : null}
          <button
            disabled={loading}
            className="bg-foreground px-5 py-2.5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
          >
            {loading ? "Running…" : "Run Stress Test"}
          </button>
        </form>
      </Card>

      {result ? (
        <div className="grid gap-6 lg:grid-cols-2">
          <DistressePanel v={result.distresse} />
          <IntraPanel p={result.intra} />
        </div>
      ) : null}

      {/* Instrument Fit -- additive, independent of the grid above. See
         instrument-fit.ts's header: this answers "is the chosen instrument
         well-suited to this thesis," not "is the thesis good" (Distresse's
         question), so it renders as its own block rather than folded into
         either panel above. Shown once the options read resolves; a plain
         loading line while it's in flight so the page doesn't visibly stall
         on Alpha Vantage's real (and sometimes slow, rate-limited) fetch. */}
      {result && instrumentFit ? (
        <InstrumentFitPanel f={instrumentFit} />
      ) : result && instrumentFitLoading ? (
        <Card title="Instrument fit — is this the right wrapper for the thesis?">
          <p className="text-sm text-muted">
            Reading {ticker.trim().toUpperCase() || "the ticker"}&apos;s options market for a real instrument-fit
            read…
          </p>
        </Card>
      ) : null}
    </div>
  );
}

// DistressePanel and IntraPanel now live in components/panels/ModelPanels.tsx
// (shared with EquityReader and the Ticker Hub) — nothing else to define here.

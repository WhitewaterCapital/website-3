"use client";

import { useState } from "react";
import { Badge, Card } from "@/components/ui";
import type { EntryExitPlan, Instrument } from "@/lib/models/types";

// "Type any ticker" box for the standalone Entry & Exit page. Previously this
// page only ever rendered the ~5-name static export (public/data/intra-exitus/
// latest.json) with no way to ask about anything else — the Stress Test page
// already had this via models.intraExitus.plan(), so this just exposes that
// same engine call directly, through /api/models/intra-exitus.
export function EntryExitAnalyzer() {
  const [ticker, setTicker] = useState("");
  const [instrument, setInstrument] = useState<Instrument>("long");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<EntryExitPlan | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    const wanted = ticker.trim();
    if (!wanted) {
      setError("Enter a ticker.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/models/intra-exitus", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: wanted, instrument }),
      });
      if (!res.ok) throw new Error((await res.json()).error ?? "Failed to analyze that ticker.");
      const data = await res.json();
      setPlan(data.plan as EntryExitPlan);
    } catch (err) {
      setError((err as Error).message);
      setPlan(null);
    } finally {
      setLoading(false);
    }
  }

  const abstained = plan ? Number.isNaN(plan.stop) : false;
  const isSample = plan?.generatedBy.toLowerCase().includes("sample") ?? false;

  return (
    <Card title="Analyze any ticker">
      <p className="text-xs text-muted">
        Not one of the names below? Type any ticker — this runs the same live
        engine call the Stress Test page uses, not a fixed list.
      </p>
      <form onSubmit={run} className="mt-4 flex flex-wrap items-end gap-3">
        <label className="block">
          <span className="eyebrow">Ticker</span>
          <input
            value={ticker}
            onChange={(e) => setTicker(e.target.value.toUpperCase())}
            placeholder="TSLA"
            className="mt-1 w-40 border border-hairline bg-background px-3 py-2 text-sm uppercase outline-none focus:border-foreground/40"
          />
        </label>
        <label className="block">
          <span className="eyebrow">Direction</span>
          <select
            value={instrument}
            onChange={(e) => setInstrument(e.target.value as Instrument)}
            className="mt-1 border border-hairline bg-background px-3 py-2 text-sm outline-none focus:border-foreground/40"
          >
            <option value="long">Long</option>
            <option value="short">Short</option>
          </select>
        </label>
        <button
          disabled={loading}
          className="bg-foreground px-5 py-2.5 text-sm font-medium text-background hover:opacity-90 disabled:opacity-50"
        >
          {loading ? "Analyzing…" : "Analyze"}
        </button>
      </form>
      {error ? <p className="mt-3 text-sm text-rose-500">{error}</p> : null}

      {plan ? (
        <div className="mt-6 border-t border-hairline pt-6">
          <div className="flex items-center justify-between">
            <h3 className="text-lg font-semibold">{plan.ticker}</h3>
            {!abstained && (
              <Badge tone={plan.bias === "long" ? "up" : "down"}>{plan.bias.toUpperCase()}</Badge>
            )}
          </div>

          {isSample && (
            <div className="mt-3 border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
              ⚠ Outside the engine&apos;s covered universe — this is the labelled sample fallback, not a real read.
            </div>
          )}

          {abstained ? (
            <p className="mt-4 text-sm text-foreground/80">{plan.rationale}</p>
          ) : (
            <>
              <div className="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Field label="Entry zone" value={`${plan.entryZone[0]} – ${plan.entryZone[1]}`} />
                <Field label="Stop" value={String(plan.stop)} tone="down" />
                <Field label="Targets" value={plan.targets.join("  ·  ")} tone="up" />
                <Field label="Size" value={`${plan.sizingPct}% of book`} />
              </div>
              <p className="mt-4 text-sm text-foreground/80">{plan.rationale}</p>
              {plan.invalidations.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {plan.invalidations.map((inv, i) => (
                    <li key={i} className="text-xs text-muted">— {inv}</li>
                  ))}
                </ul>
              )}
            </>
          )}
          <p className="mt-4 text-[11px] text-muted">{plan.generatedBy}</p>
        </div>
      ) : null}
    </Card>
  );
}

function Field({ label, value, tone }: { label: string; value: string; tone?: "up" | "down" }) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div
        className={`mt-1 text-sm font-semibold tabular-nums ${
          tone === "up" ? "text-emerald-500" : tone === "down" ? "text-rose-500" : ""
        }`}
      >
        {value}
      </div>
    </div>
  );
}

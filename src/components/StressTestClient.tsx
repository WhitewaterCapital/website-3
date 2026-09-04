"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import { DistressePanel, IntraPanel } from "@/components/panels/ModelPanels";
import type {
  StressVerdict,
  EntryExitPlan,
  Instrument,
} from "@/lib/models/types";

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

export function StressTestClient() {
  const [ticker, setTicker] = useState("");
  const [instrument, setInstrument] = useState<Instrument>("long");
  const [thesis, setThesis] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!ticker.trim()) {
      setError("Enter a ticker.");
      return;
    }
    setLoading(true);
    try {
      const res = await fetch("/api/models/stress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, instrument, thesis }),
      });
      if (!res.ok) throw new Error((await res.json()).error ?? "Failed");
      setResult(await res.json());
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setLoading(false);
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
    </div>
  );
}

// DistressePanel and IntraPanel now live in components/panels/ModelPanels.tsx
// (shared with EquityReader and the Ticker Hub) — nothing else to define here.

"use client";

import { useState } from "react";
import { Card, Badge } from "@/components/ui";
import { ScoreBar } from "@/components/ScoreBar";
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

const ratingTone = { go: "up", conditional: "warn", "no-go": "down" } as const;

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
            {loading ? "Running…" : "Run Distresse + Intra / Exitus"}
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

function DistressePanel({ v }: { v: StressVerdict }) {
  return (
    <Card
      title="Distresse — stress test"
      action={<Badge tone={ratingTone[v.rating]}>{v.rating.toUpperCase()}</Badge>}
    >
      {v.generatedBy.includes("sample") && (
        <div className="mb-4 border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          ⚠ <strong>SAMPLE — placeholder scoring, not a real model.</strong> The
          rating and conviction below are illustrative RNG, not analysis. Do not
          use for real decisions until the Distresse model is built.
        </div>
      )}
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-muted">{v.ticker} · {v.instrument}</span>
        <span className="text-sm text-muted">
          conviction <span className="font-semibold text-foreground">{v.conviction}</span>/100
        </span>
      </div>
      <p className="mt-2 text-xs text-muted">Regime: {v.regime}</p>

      <div className="mt-5 space-y-3">
        {v.dimensions.map((d) => (
          <div key={d.label}>
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium">{d.label}</span>
              <span className={`tabular-nums ${d.score >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                {d.score > 0 ? "+" : ""}
                {d.score}
              </span>
            </div>
            <div className="mt-1"><ScoreBar score={d.score} /></div>
            <p className="mt-1 text-xs text-muted">{d.note}</p>
          </div>
        ))}
      </div>

      <Section title="Devil's advocate">
        <ul className="space-y-1.5">
          {v.devilsAdvocate.map((d, i) => (
            <li key={i} className="text-sm text-foreground/80">— {d}</li>
          ))}
        </ul>
      </Section>
      <Section title="Tail risks">
        <ul className="space-y-1.5">
          {v.tailRisks.map((t, i) => (
            <li key={i} className="text-sm text-foreground/80">— {t}</li>
          ))}
        </ul>
      </Section>

      <div className="mt-5 border-t border-hairline pt-4">
        <p className="eyebrow">Bottom line</p>
        <p className="mt-1 text-sm">{v.bottomLine}</p>
      </div>
      <p className="mt-3 text-[11px] text-muted">{v.generatedBy}</p>
    </Card>
  );
}

function IntraPanel({ p }: { p: EntryExitPlan }) {
  return (
    <Card
      title="Intra / Exitus — entry & exit"
      action={<Badge tone={p.bias === "long" ? "up" : "down"}>{p.bias.toUpperCase()}</Badge>}
    >
      <div className="grid grid-cols-2 gap-4">
        <Field label="Entry zone" value={`${p.entryZone[0]} – ${p.entryZone[1]}`} />
        <Field label="Stop" value={String(p.stop)} tone="down" />
        <Field label="Targets" value={p.targets.join("  ·  ")} tone="up" />
        <Field label="Size" value={`${p.sizingPct}% of book`} />
      </div>

      <Section title="Time stop">
        <p className="text-sm text-foreground/80">{p.timeStop}</p>
      </Section>
      <Section title="Rationale">
        <p className="text-sm text-foreground/80">{p.rationale}</p>
      </Section>
      <Section title="Invalidations">
        <ul className="space-y-1.5">
          {p.invalidations.map((inv, i) => (
            <li key={i} className="text-sm text-foreground/80">— {inv}</li>
          ))}
        </ul>
      </Section>
      <p className="mt-4 text-[11px] text-muted">{p.generatedBy}</p>
    </Card>
  );
}

function Field({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
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

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-5">
      <p className="eyebrow">{title}</p>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

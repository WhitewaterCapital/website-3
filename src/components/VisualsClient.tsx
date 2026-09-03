"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import { DislocationField } from "@/components/DislocationField";
import { ChaosRibbon, type ChaosPoint } from "@/components/ChaosRibbon";
import { CascadeNetwork } from "@/components/CascadeNetwork";
import { AllocatorRibbon } from "@/components/AllocatorRibbon";
import type { GraphExport } from "@/lib/models/graph-export";

// VIS-01 — the static + replay visual layer, assembled with ONE shared
// replay scrubber. Per the planning doc's own recommended build order
// ("build the static version first... add a replay scrubber over stored
// data next... only then connect the live stream"), this stops after the
// replay step: the scrubber drives an INDEX into a stored array of sample
// snapshots, not a real-time clock, and nothing here streams from a
// websocket/SSE backend (none exists in this repo).
//
// ---------------------------------------------------------------------------
// CHAOS-01 sample fixture. No `src/lib/chaos.ts` / `getChaosExport()` seam
// exists yet in this tree (checked before writing this file). This is the
// ONE call site with a clearly-labeled SAMPLE array — swap it for
// `getChaosExport()` (fed into <ChaosRibbon points={...} />) the moment that
// seam lands; ChaosRibbon's prop shape is already documented for that swap.
// State labels match chaos-engine/chaos/state.py's real STATE_LEVELS exactly
// (calm/stressed/dislocated/cascade) so the swap changes no vocabulary.
// ---------------------------------------------------------------------------
const SAMPLE_CHAOS_POINTS: ChaosPoint[] = (() => {
  const n = 40;
  const start = new Date("2026-08-24T09:30:00Z");
  const states = ["calm", "calm", "calm", "stressed", "stressed", "dislocated", "cascade", "dislocated", "stressed", "calm"];
  return Array.from({ length: n }, (_, i) => {
    const phase = (i / n) * states.length;
    const state = states[Math.min(states.length - 1, Math.floor(phase))];
    // index rises into the cascade phase and decays back down — deterministic, not random
    const t = i / (n - 1);
    const index = Math.max(0.03, Math.min(0.98, 0.5 - 0.5 * Math.cos(t * Math.PI * 1.6)) * (state === "calm" ? 0.35 : state === "stressed" ? 0.65 : state === "dislocated" ? 0.85 : 1));
    return {
      state,
      index: Math.round(index * 100) / 100,
      asOf: new Date(start.getTime() + i * 30 * 60 * 1000).toISOString(),
    };
  });
})();

const SAMPLE_PRICE = SAMPLE_CHAOS_POINTS.map((p, i) => {
  // A synthetic price path that wobbles down through the stressed/cascade
  // phase and partially recovers — illustrative only, aligned 1:1 with the points above.
  const drawdown = p.index * 6;
  return 100 - drawdown + Math.sin(i / 3) * 0.6;
});

export function VisualsClient({ graph }: { graph: GraphExport | null }) {
  const [step, setStep] = useState(0);
  const maxStep = SAMPLE_CHAOS_POINTS.length - 1;
  const cascadeSteps = 16;
  const cascadeStep = Math.round((step / maxStep) * (cascadeSteps - 1));

  return (
    <div className="space-y-10">
      {/* Shared replay scrubber */}
      <Card title="Replay">
        <p className="text-xs text-muted">
          Steps through a stored array of sample snapshots — not a live clock.
          Drives the Chaos ribbon and the Cascade network below; the
          Dislocation field and Allocator ribbon are static snapshots (noted
          on each panel).
        </p>
        <div className="mt-4 flex items-center gap-4">
          <input
            type="range"
            min={0}
            max={maxStep}
            value={step}
            onChange={(e) => setStep(Number(e.target.value))}
            className="w-full accent-foreground motion-reduce:transition-none"
            aria-label="Replay position"
          />
          <span className="w-40 shrink-0 text-right font-mono text-xs text-muted tabular-nums">
            {SAMPLE_CHAOS_POINTS[step].asOf.slice(0, 16).replace("T", " ")}
          </span>
        </div>
      </Card>

      <Card title="Dislocation field — WW-GRAPH residuals">
        <DislocationField data={graph} />
      </Card>

      <Card title="Chaos ribbon — CHAOS-01 state">
        <ChaosRibbon points={SAMPLE_CHAOS_POINTS} priceSeries={SAMPLE_PRICE} currentIndex={step} sample />
      </Card>

      <Card title="Cascade network — WW-CASCADE pressure propagation">
        <CascadeNetwork currentStep={cascadeStep} />
      </Card>

      <Card title="Allocator ribbon — WW-ALLOC budgets">
        <AllocatorRibbon />
      </Card>
    </div>
  );
}

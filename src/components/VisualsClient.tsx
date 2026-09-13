"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import { DislocationField } from "@/components/DislocationField";
import { ChaosRibbon, type ChaosPoint } from "@/components/ChaosRibbon";
import type { GraphExport } from "@/lib/models/graph-export";
import type { ChaosExport } from "@/lib/models/chaos-export";

// VIS-01 — the static + replay visual layer, assembled with ONE shared
// replay scrubber. Per the planning doc's own recommended build order
// ("build the static version first... add a replay scrubber over stored
// data next... only then connect the live stream"), this stops after the
// replay step: the scrubber drives an INDEX, not a real-time clock, and
// nothing here streams from a websocket/SSE backend (none exists in this
// repo). As of 2026-09-13, that index can point into REAL stored history for
// the Dislocation field (graph-engine's history.jsonl — see
// PLATFORM_REBUILD_PLAN.md priority #4) once it has 2+ days in it; the Chaos
// ribbon still has no history source of its own (see below) and always uses
// the labeled sample array instead.
//
// REMOVED 2026-09-13 (see PLATFORM_REBUILD_PLAN.md, priority #7): Cascade
// Network and Allocator Ribbon used to render below the Chaos ribbon. Both
// were 100% fabricated fixtures with no real seam behind them at all (no
// ETF-holdings ingestion, no live WW-ALLOC run/export) — pulled off this
// page rather than left showing fake numbers next to Distresse's newly-real
// dimensions. Their component files (CascadeNetwork.tsx, AllocatorRibbon.tsx)
// are now unused/orphaned — left in place rather than deleted (this session
// hit a hard deletion-permission denial; see the plan's Roadblocks). Real
// rebuilds of both are tracked separately in the plan, not half-built here.
// Note: AllocatorPanel.tsx on /dashboard is a DIFFERENT, unrelated component
// with a real seam (getAllocExport()) already wired for a real export to
// drop into — it was not touched and stays.
//
// ---------------------------------------------------------------------------
// CHAOS-01 sample fixture — the FALLBACK, used only when `chaos` (read
// server-side via getChaosExport() in src/app/visuals/page.tsx) is null or
// has no reading with a usable chaos_index. The seam itself now exists and
// is wired below (see the `chaosIsReal` branch); this fixture stays because
// getChaosExport() returns a per-ticker snapshot, not a time series, so a
// "not synced" or "no usable reading" state still needs something to show a
// replay ribbon with. State labels match chaos-engine/chaos/state.py's real
// STATE_LEVELS exactly (calm/stressed/dislocated/cascade) either way.
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

export function VisualsClient({
  graph,
  graphHistory,
  chaos,
}: {
  graph: GraphExport | null;
  graphHistory: GraphExport[] | null;
  chaos: ChaosExport | null;
}) {
  const [step, setStep] = useState(0);

  // Real replay (2026-09-13): once graph-engine's `python -m ge.export` has
  // run on 2+ distinct days, public/data/graph/history.jsonl has real rows
  // to scrub through (see graph.ts's getGraphHistory and export.py's
  // append_history) — below that, one entry tells you nothing a static
  // snapshot doesn't, so it falls back to the single latest `graph` read,
  // same as before this history log existed.
  const hasRealGraphHistory = (graphHistory?.length ?? 0) >= 2;
  const maxStep = Math.max(SAMPLE_CHAOS_POINTS.length, graphHistory?.length ?? 0) - 1;

  // getChaosExport() is a per-ticker SNAPSHOT (one `as_of`), not a stored
  // time series — there is no chaos history to scrub through yet, and won't
  // be until WW-CHAOS has a real live intraday feed (it currently has none
  // at all — see chaos-engine's README — so this isn't fixable by re-running
  // an export the way the Dislocation field above was). When a real export
  // is present, use its first reading with a usable (non-null) chaos_index
  // as a single real ChaosPoint. Fall back to the SAMPLE fixture, clearly
  // labeled, only when no real reading is usable.
  const primaryReading = chaos?.readings.find((r) => r.chaos_index != null) ?? null;
  const chaosIsReal = primaryReading != null;
  const chaosPoints = primaryReading
    ? [{ state: primaryReading.state_label, index: primaryReading.chaos_index as number, asOf: primaryReading.as_of }]
    : SAMPLE_CHAOS_POINTS;

  const graphAtStep = hasRealGraphHistory
    ? graphHistory![Math.min(step, graphHistory!.length - 1)]
    : graph;
  const replayTimestamp = hasRealGraphHistory
    ? `${graphAtStep!.as_of} (day ${Math.min(step, graphHistory!.length - 1) + 1}/${graphHistory!.length})`
    : SAMPLE_CHAOS_POINTS[Math.min(step, SAMPLE_CHAOS_POINTS.length - 1)].asOf.slice(0, 16).replace("T", " ");

  return (
    <div className="space-y-10">
      {/* Shared replay scrubber. Drives the Dislocation field through REAL
         history once graph-engine has 2+ days exported (see above);
         otherwise (and always, for the Chaos ribbon, which has no history
         source yet) it steps through the labeled sample fixture. */}
      <Card title="Replay">
        <p className="text-xs text-muted">
          {hasRealGraphHistory
            ? `Scrubs through ${graphHistory!.length} real days of WW-GRAPH history for the Dislocation field below. The Chaos ribbon still has no history source (WW-CHAOS has no live intraday feed wired in) — it uses the labeled sample series regardless of this control.`
            : "The Dislocation field below is a single real (or synthetic-demo) snapshot until graph-engine's export has run on 2+ distinct days — this control currently only steps through the Chaos ribbon's labeled sample series."}
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
          <span className="w-48 shrink-0 text-right font-mono text-xs text-muted tabular-nums">
            {replayTimestamp}
          </span>
        </div>
      </Card>

      <Card title="Dislocation field — WW-GRAPH residuals">
        {hasRealGraphHistory && (
          <p className="mb-3 text-xs text-muted">
            Replaying real history — day {Math.min(step, graphHistory!.length - 1) + 1} of{" "}
            {graphHistory!.length}. Drag the Replay slider above.
          </p>
        )}
        <DislocationField data={graphAtStep} />
      </Card>

      <Card title="Chaos ribbon — CHAOS-01 state">
        {chaosIsReal ? (
          <>
            <p className="mb-3 text-xs text-muted">
              Ticker <strong>{primaryReading!.ticker}</strong>, current reading only — WW-CHAOS does not yet
              persist a time history, so this is one real point, not a series. Provenance:{" "}
              <strong>{chaos!.provenance}</strong>.
              {chaos!.watchlist.length > 1 &&
                ` (${chaos!.watchlist.length - 1} other watchlist ticker${chaos!.watchlist.length > 2 ? "s" : ""} not shown.)`}
            </p>
            <ChaosRibbon points={chaosPoints} currentIndex={0} sample={false} />
            <p className="mt-3 text-[11px] text-muted">{chaos!.disclaimer}</p>
          </>
        ) : (
          <ChaosRibbon points={SAMPLE_CHAOS_POINTS} priceSeries={SAMPLE_PRICE} currentIndex={step} sample />
        )}
      </Card>
    </div>
  );
}

import { ModuleNav } from "@/components/ModuleNav";
import { VisualsClient } from "@/components/VisualsClient";
import { getGraphExport } from "@/lib/graph";
import { getChaosExport } from "@/lib/chaos";

// VISUAL LAYER — VIS-01. Two static + replay views: a dislocation field
// (real WW-GRAPH residuals) and a chaos state ribbon. Static first, then a
// replay scrubber over stored snapshots — per the planning doc's own build
// order, this does NOT connect to a live stream (no websocket/SSE backend
// exists in this repo yet).
//
// Used to be four panels. The other two — a cascade-pressure network and an
// allocator budget ribbon — were 100% fabricated fixtures with no real seam
// behind them at all, and were removed 2026-09-13 rather than left showing
// fake numbers next to the two panels above that at least have real (if
// currently synthetic-demo / single-snapshot) data behind them. See
// PLATFORM_REBUILD_PLAN.md priority #7 for the full reasoning and what a
// real rebuild of either would need.
//
// Chaos ribbon data source: getChaosExport() (src/lib/chaos.ts) is read here,
// server-side, and passed down through VisualsClient into ChaosRibbon. That
// export seam is real — but per chaos-export.ts's own contract its
// `provenance` is "synthetic-demo" today (a locally generated synthetic
// intraday panel, not a live market feed), and it is a per-ticker SNAPSHOT
// (one `as_of`), not a time history — so VisualsClient renders it as a
// single real reading, not a fabricated series. If getChaosExport() returns
// null (not synced), ChaosRibbon falls back to its SAMPLE_CHAOS_POINTS
// fixture with the amber sample banner, same as before this seam existed.
export const dynamic = "force-dynamic"; // always read the latest WW-GRAPH / WW-CHAOS export

export default async function VisualsPage() {
  const graph = await getGraphExport();
  const chaos = await getChaosExport();

  return (
    <div>
      <ModuleNav crumb="Visuals" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Visuals</p>
          <span className="font-mono text-xs text-muted">static + replay</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Two ways to see the market moving.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          Both panels read real export seams — WW-GRAPH&apos;s residual
          dislocations, and WW-CHAOS&apos;s state read — though both are
          currently synthetic-demo data per their own exports, not a live
          market feed, and each is a single snapshot rather than a real
          history to scrub through yet. Each panel says exactly what it is.
        </p>

        <div className="mt-8">
          <VisualsClient graph={graph} chaos={chaos} />
        </div>
      </main>
    </div>
  );
}

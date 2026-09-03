import { ModuleNav } from "@/components/ModuleNav";
import { VisualsClient } from "@/components/VisualsClient";
import { getGraphExport } from "@/lib/graph";
import { getChaosExport } from "@/lib/chaos";

// VISUAL LAYER — VIS-01. Four static + replay views: a dislocation field
// (real WW-GRAPH residuals), a chaos state ribbon, a cascade-pressure
// network, and an allocator budget ribbon. Static first, then a replay
// scrubber over stored snapshots — per the planning doc's own build order,
// this does NOT connect to a live stream (no websocket/SSE backend exists
// in this repo yet).
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
        <h1 className="display mt-2 text-3xl sm:text-4xl">Four ways to see the market moving.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          Two panels read real export seams — WW-GRAPH&apos;s residual
          dislocations, and WW-CHAOS&apos;s state read (itself synthetic-demo
          data per its own export, not a live market feed) — and two are
          sample fixtures standing in for engines that don&apos;t have an
          export seam yet. Each panel says which is which.
        </p>

        <div className="mt-8">
          <VisualsClient graph={graph} chaos={chaos} />
        </div>
      </main>
    </div>
  );
}

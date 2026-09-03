import { ModuleNav } from "@/components/ModuleNav";
import { VisualsClient } from "@/components/VisualsClient";
import { getGraphExport } from "@/lib/graph";

// VISUAL LAYER — VIS-01. Four static + replay views: a dislocation field
// (real WW-GRAPH residuals), a chaos state ribbon, a cascade-pressure
// network, and an allocator budget ribbon. Static first, then a replay
// scrubber over stored snapshots — per the planning doc's own build order,
// this does NOT connect to a live stream (no websocket/SSE backend exists
// in this repo yet).
export const dynamic = "force-dynamic"; // always read the latest WW-GRAPH export

export default async function VisualsPage() {
  const graph = await getGraphExport();

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
          One real feed (WW-GRAPH&apos;s residual dislocations) and three
          sample fixtures standing in for engines that don&apos;t have an
          export seam yet — each panel says which is which.
        </p>

        <div className="mt-8">
          <VisualsClient graph={graph} />
        </div>
      </main>
    </div>
  );
}

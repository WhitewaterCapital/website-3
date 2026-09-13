import { ModuleNav } from "@/components/ModuleNav";
import { VisualsClient } from "@/components/VisualsClient";
import { getGraphExport, getGraphHistory } from "@/lib/graph";
import { getChaosExport } from "@/lib/chaos";

// VISUAL LAYER — VIS-01. Two views: a dislocation field (real WW-GRAPH
// residuals) and a chaos state ribbon. Neither connects to a live stream (no
// websocket/SSE backend exists in this repo) — this does NOT stream, it
// reads whatever the engines last exported.
//
// Real replay history (2026-09-13): `python -m ge.export` (graph-engine) now
// appends each run to public/data/graph/history.jsonl (see that file's
// `append_history`) instead of only overwriting latest.json. Once that log
// has 2+ distinct days in it, VisualsClient's replay scrubber drives the
// Dislocation Field through REAL accumulated history, not a static single
// snapshot — it just needs the export run more than once (daily, ideally) to
// have anything to scrub through. Below 2 entries it still shows the single
// latest snapshot, same as before. The Chaos ribbon has no equivalent yet:
// WW-CHAOS has no live intraday feed wired in at all (see chaos-engine's own
// README — this needs new data infrastructure, not just re-running a
// command), so its replay still uses the labeled SAMPLE_CHAOS_POINTS fixture
// unless a real (single-point) reading exists.
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
  const [graph, graphHistory, chaos] = await Promise.all([
    getGraphExport(),
    getGraphHistory(),
    getChaosExport(),
  ]);

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
          dislocations, and WW-CHAOS&apos;s state read. Each panel says
          exactly what it is: live vs. synthetic-demo market data, and, for
          the Dislocation field, how many real days of history it actually
          has to scrub through ({graphHistory ? graphHistory.length : 0} so
          far — it grows by one every time <code>python -m ge.export</code>
          runs).
        </p>

        <div className="mt-8">
          <VisualsClient graph={graph} graphHistory={graphHistory} chaos={chaos} />
        </div>
      </main>
    </div>
  );
}

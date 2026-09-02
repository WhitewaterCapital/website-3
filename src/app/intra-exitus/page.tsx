import { ModuleNav } from "@/components/ModuleNav";
import { Card } from "@/components/ui";
import { IntraExitusReader } from "@/components/IntraExitusReader";
import { getIntraExitusExport } from "@/lib/intra-exitus";

// INTRA / EXITUS — entry & exit. Renders the REAL engine output
// (intra-exitus-engine → public/data/intra-exitus/latest.json). Honest "not
// synced" state when the engine hasn't exported; no fake levels.
export const dynamic = "force-dynamic";

export default async function IntraExitusPage() {
  const data = await getIntraExitusExport();

  return (
    <div>
      <ModuleNav crumb="Intra / Exitus" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Intra / Exitus</p>
          <span className="font-mono text-xs text-muted">enter · exit</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">
          Where to get in, where to get out.
        </h1>
        <p className="mt-3 max-w-2xl text-muted">
          Regime-conditional entry/exit levels from the real engine — OU
          mean-reversion or trend-pullback, cost-aware sizing, and an honest
          abstain when there&apos;s no clean setup.
        </p>

        <div className="mt-8">
          {data ? (
            <IntraExitusReader data={data} />
          ) : (
            <Card>
              <p className="eyebrow">Not synced yet</p>
              <p className="mt-2 text-sm text-foreground/80">
                The engine hasn&apos;t exported. Run{" "}
                <code>python -m ie.export</code> in{" "}
                <code>intra-exitus-engine/</code> to populate{" "}
                <code>public/data/intra-exitus/latest.json</code>.
              </p>
            </Card>
          )}
        </div>
      </main>
    </div>
  );
}

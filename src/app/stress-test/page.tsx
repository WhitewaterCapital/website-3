import { ModuleNav } from "@/components/ModuleNav";
import { StressTestClient } from "@/components/StressTestClient";

export const metadata = {
  title: "Strictus Testum — Whitewater",
  description: "The rigorous test — the adversarial read before the book does.",
};

// STRICTUS TESTUM — the rigorous test. Wires the Distresse (verdict) and
// Intra / Exitus (entry & exit) engines into the module page via StressTestClient.
export default function StrictusTestumPage() {
  return (
    <div>
      <ModuleNav crumb="Strictus Testum" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Strictus Testum</p>
          <span className="font-mono text-xs text-muted">the rigorous test</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Pressure-test the idea.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          Take a trade and see it straight — the adversarial read before the book does.
        </p>

        <div className="mt-8">
          <StressTestClient />
        </div>
      </main>
    </div>
  );
}

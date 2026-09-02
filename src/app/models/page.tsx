import Link from "next/link";
import { ModuleNav } from "@/components/ModuleNav";
import { Badge } from "@/components/ui";
import { MODELS } from "@/lib/models/registry";

const statusTone = { live: "up", beta: "warn", planned: "neutral" } as const;

// MODEL REGISTRY — every model the desk runs, and its status. The hub where
// your algos are wired in (see src/lib/models/README.md).
export default function ModelRegistryPage() {
  return (
    <div>
      <ModuleNav crumb="Model registry" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <p className="font-mono text-sm text-accent">// Model registry</p>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Where our models sit.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          A hub, not a monolith. Each model plugs into one interface; add your
          algos in <code>src/lib/models/impl/</code> and register them.
        </p>

        <div className="mt-8 grid gap-px border border-hairline bg-hairline sm:grid-cols-2">
          {MODELS.map((m) => (
            <div key={m.id} className="bg-background p-6">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">{m.name}</h3>
                <Badge tone={statusTone[m.status]}>{m.status}</Badge>
              </div>
              <p className="mt-1 text-sm text-muted">{m.tagline}</p>
              <p className="mt-3 text-sm text-foreground/80">{m.description}</p>
              {m.etymology ? (
                <p className="mt-3 border-t border-hairline pt-3 text-xs italic text-muted">
                  {m.etymology}
                </p>
              ) : null}
              {(m.id === "distresse" || m.id === "intra-exitus") && (
                <Link href="/stress-test" className="mt-4 inline-block text-xs font-medium text-accent hover:underline">
                  Open in Strictus Testum →
                </Link>
              )}
              {m.id === "macro-tracker" && (
                <Link href="/sentiment" className="mt-4 inline-block text-xs font-medium text-accent hover:underline">
                  Open in Sentiment →
                </Link>
              )}
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

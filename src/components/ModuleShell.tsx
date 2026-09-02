import { ModuleNav } from "@/components/ModuleNav";
import { Card } from "@/components/ui";

// An empty module page. Frontend + routing are ready; the model is yours to
// build. Drop the algo into src/lib/models/impl/, register it, render it here.
export function ModuleShell({
  name,
  latin,
  title,
  intro,
}: {
  name: string;
  latin: string;
  title: string;
  intro: string;
}) {
  return (
    <div>
      <ModuleNav crumb={name} />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// {name}</p>
          <span className="font-mono text-xs text-muted">{latin}</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">{title}</h1>
        <p className="mt-3 max-w-2xl text-muted">{intro}</p>

        <Card>
          <p className="eyebrow">Ready for your model</p>
          <p className="mt-2 text-sm text-foreground/80">
            This tab is intentionally empty — build{" "}
            <strong className="text-foreground">{name}</strong> yourself.
          </p>
          <p className="mt-3 text-xs text-muted">
            Add the algo in <code>src/lib/models/impl/</code>, register it in{" "}
            <code>src/lib/models/registry.ts</code>, then render its output on
            this page. The interfaces, routing, and nav are already wired.
          </p>
        </Card>
      </main>
    </div>
  );
}

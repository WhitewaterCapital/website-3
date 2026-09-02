import { ModuleNav } from "@/components/ModuleNav";
import { SentimentumTabs } from "@/components/SentimentumTabs";
import { getEquityExport } from "@/lib/incepta";
import { getMacroExport } from "@/lib/aurora";

// SENTIMENTUM — the regime lens. Houses two models under one button:
// Macro (Aurora engine reader) and Equity (Incepta engine reader).
// Loads both exports server-side (files today, Supabase later — same schema,
// no change here).
export const dynamic = "force-dynamic"; // always read the latest exports

export default async function SentimentumPage() {
  const [equity, macro] = await Promise.all([
    getEquityExport(),
    getMacroExport(),
  ]);

  return (
    <div>
      <ModuleNav crumb="Sentimentum" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Sentimentum</p>
          <span className="font-mono text-xs text-muted">the regime lens</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">Sentiment, two ways.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          One lens, two models — a top-down <strong className="text-foreground">Macro</strong>{" "}
          read and a bottom-up <strong className="text-foreground">Equity</strong> read.
        </p>

        <div className="mt-8">
          <SentimentumTabs equity={equity} macro={macro} />
        </div>
      </main>
    </div>
  );
}

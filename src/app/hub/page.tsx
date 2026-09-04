import { ModuleNav } from "@/components/ModuleNav";
import { TickerHubClient } from "@/components/TickerHubClient";

// TICKER HUB — the new unified entry point: type any commodity, equity, or FX
// ticker and get the combined read from every model that applies to it
// (Distresse, Entry & Exit, WW-Weekly's rank, and Incepta's equity
// fundamentals when the ticker is actually covered), with an optional
// side-by-side comparison against a second ticker. The individual model
// pages (Stress Test, Entry & Exit, Weekly, Sentiment) are unchanged — this
// sits alongside them, not instead of them.
export const dynamic = "force-dynamic";

export const metadata = {
  title: "Ticker Hub — Whitewater",
  description: "Enter any ticker and get every model's read on it in one place.",
};

export default function TickerHubPage() {
  return (
    <div>
      <ModuleNav crumb="Ticker Hub" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Ticker Hub</p>
          <span className="font-mono text-xs text-muted">search any name, get everything</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">
          One ticker. Every model.
        </h1>
        <p className="mt-3 max-w-2xl text-muted">
          Type a commodity, equity, or FX ticker and this runs every model
          that applies to it — the stress test, entry &amp; exit levels, the
          weekly cross-sectional rank, and equity fundamentals when they
          exist for the name — and lays it all out in one breakdown. Add a
          second ticker to compare two names side by side.
        </p>

        <div className="mt-8">
          <TickerHubClient />
        </div>
      </main>
    </div>
  );
}

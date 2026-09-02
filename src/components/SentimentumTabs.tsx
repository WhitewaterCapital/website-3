"use client";

import { useState } from "react";
import { Card } from "@/components/ui";
import { EquityReader } from "@/components/EquityReader";
import { MacroReader } from "@/components/MacroReader";
import type { EquityExport } from "@/lib/models/incepta-export";
import type { MacroExport } from "@/lib/models/aurora-export";

// Sentimentum houses two models under one button: a Macro model (Aurora) and an
// Equity model (Incepta). Each renders its engine's output when present.
const MODELS = [
  { id: "macro", label: "Macro", latin: "top-down", title: "The regime lens.", intro: "Structural macro — scenarios, regime, tilt, nowcast." },
  { id: "equity", label: "Equity", latin: "bottom-up", title: "The equity lens.", intro: "Bottom-up, single-name risk & evidence — Incepta." },
];

export function SentimentumTabs({
  equity,
  macro,
}: {
  equity: EquityExport | null;
  macro: MacroExport | null;
}) {
  const [active, setActive] = useState("macro");
  const model = MODELS.find((m) => m.id === active)!;

  return (
    <div>
      {/* Sub-model switcher */}
      <div className="flex gap-6 border-b border-hairline">
        {MODELS.map((m) => (
          <button
            key={m.id}
            onClick={() => setActive(m.id)}
            className={`-mb-px border-b-2 pb-3 text-sm font-medium transition ${
              active === m.id
                ? "border-foreground text-foreground"
                : "border-transparent text-muted hover:text-foreground"
            }`}
          >
            {m.label}
            <span className="ml-2 font-mono text-xs text-muted">{m.latin}</span>
          </button>
        ))}
      </div>

      <div className="mt-8">
        {active === "macro" && macro ? (
          <MacroReader data={macro} onHandoffToEquity={() => setActive("equity")} />
        ) : active === "equity" && equity ? (
          <EquityReader data={equity} />
        ) : (
          <>
            <h2 className="display text-2xl sm:text-3xl">{model.title}</h2>
            <p className="mt-2 max-w-2xl text-muted">{model.intro}</p>
            <Card>
              <p className="eyebrow">Not synced yet</p>
              <p className="mt-2 text-sm text-foreground/80">
                {active === "macro" ? (
                  <>
                    The Aurora engine hasn&apos;t been synced. Run{" "}
                    <code>npm run sync:aurora</code> to copy its latest export into{" "}
                    <code>public/data/aurora/latest.json</code>.
                  </>
                ) : (
                  <>
                    The Incepta engine hasn&apos;t written an export yet. Run{" "}
                    <code>incepta.cli export</code> to populate{" "}
                    <code>public/data/incepta/latest.json</code>.
                  </>
                )}
              </p>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}

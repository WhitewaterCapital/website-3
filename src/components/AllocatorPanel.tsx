"use client";

import { useEffect, useRef, useState } from "react";
import { Card, Badge } from "@/components/ui";
import type { AllocExport, AllocStrategyResult } from "@/lib/models/alloc-export";
import type { StateExport } from "@/lib/models/state-export";

// ═══════════════════════════════════════════════════════════════════════════
// IMP-05 — dashboard allocator panel.
//
// Three jobs, per the spec:
//   1. Current vs. previous budget per strategy, and WHY it moved — expected
//      edge, an uncertainty penalty, and a cost penalty — sourced from
//      getAllocExport() (src/lib/alloc.ts). Today that export is a clearly
//      labeled SAMPLE (see alloc-export.ts's module doc); the shape mirrors
//      quant-infra/alloc/solve.py exactly so a real export drops in with no
//      UI change.
//   2. Market state in plain words — reuses WW-STATE's own plain-language
//      renderer (getStateExport().plain_language) rather than re-deriving a
//      words-from-numbers mapping here.
//   3. A manual override: written reason + time limit, held in React state
//      ONLY for this browser tab (no backend — see the caption on the
//      override card), with a real countdown that auto-clears on expiry.
//
// `alloc` / `state` are fetched server-side (src/app/dashboard/page.tsx) and
// passed in as plain data — this component itself is a client component only
// because the override timer needs useState/useEffect.
// ═══════════════════════════════════════════════════════════════════════════

const pctUnsigned = (x: number, digits = 1) => `${(x * 100).toFixed(digits)}%`;
const pctSigned = (x: number, digits = 1) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`;

const OVERRIDE_DURATIONS = [
  { label: "15 minutes", minutes: 15 },
  { label: "1 hour", minutes: 60 },
  { label: "4 hours", minutes: 240 },
  { label: "1 trading day", minutes: 60 * 24 },
] as const;

type ActiveOverride = {
  strategy: string; // strategy name, or "__desk__" for a desk-wide override
  reason: string;
  startedAt: number; // epoch ms
  expiresAt: number; // epoch ms
};

function formatCountdown(msRemaining: number): string {
  const totalSeconds = Math.max(0, Math.ceil(msRemaining / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m`;
  if (minutes > 0) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

// Utility breakdown — three labeled mini-bars (edge / uncertainty / cost),
// same visual language as AllocatorRibbon's utility-component bars in
// src/components/AllocatorRibbon.tsx, sized against the widest magnitude in
// this export so bars are comparable across strategies.
function UtilityBreakdown({ s, maxMag }: { s: AllocStrategyResult; maxMag: number }) {
  const w = (v: number) => `${Math.max(0, (Math.abs(v) / maxMag) * 100)}%`;
  return (
    <div className="mt-1.5 flex h-3 w-full overflow-hidden rounded-full bg-foreground/5">
      <div className="h-full bg-emerald-500" style={{ width: w(s.shrunk_edge) }} title={`+expected edge ${pctUnsigned(s.shrunk_edge, 2)}`} />
      <div className="h-full bg-amber-500" style={{ width: w(s.uncertainty_penalty_term) }} title={`-uncertainty penalty ${pctUnsigned(s.uncertainty_penalty_term, 2)}`} />
      <div className="h-full bg-rose-500" style={{ width: w(s.cost_penalty_term) }} title={`-cost penalty ${pctUnsigned(s.cost_penalty_term, 2)}`} />
    </div>
  );
}

export function AllocatorPanel({
  alloc,
  state,
}: {
  alloc: AllocExport | null;
  state: StateExport | null;
}) {
  const [activeOverride, setActiveOverride] = useState<ActiveOverride | null>(null);
  const [now, setNow] = useState<number>(() => Date.now());
  const [reasonDraft, setReasonDraft] = useState("");
  const [strategyDraft, setStrategyDraft] = useState<string>("__desk__");
  const [durationDraft, setDurationDraft] = useState<number>(OVERRIDE_DURATIONS[0].minutes);
  const [formError, setFormError] = useState<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Real auto-revert: a timeout clears the override at expiry, plus a 1s
  // ticker while one is active so the countdown actually counts down. Both
  // are torn down on unmount or when the override changes/clears.
  useEffect(() => {
    if (!activeOverride) return;
    const msRemaining = activeOverride.expiresAt - Date.now();
    timeoutRef.current = setTimeout(() => setActiveOverride(null), Math.max(0, msRemaining));
    const ticker = setInterval(() => setNow(Date.now()), 1000);
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
      clearInterval(ticker);
    };
  }, [activeOverride]);

  function submitOverride(e: React.FormEvent) {
    e.preventDefault();
    const reason = reasonDraft.trim();
    if (!reason) {
      setFormError("A written reason is required before an override can be applied.");
      return;
    }
    setFormError(null);
    const startedAt = Date.now();
    setActiveOverride({
      strategy: strategyDraft,
      reason,
      startedAt,
      expiresAt: startedAt + durationDraft * 60 * 1000,
    });
    setReasonDraft("");
  }

  const msRemaining = activeOverride ? activeOverride.expiresAt - now : 0;
  const strategies = alloc?.strategies ?? [];
  const maxMag = Math.max(
    0.005,
    ...strategies.flatMap((s) => [Math.abs(s.shrunk_edge), s.uncertainty_penalty_term, s.cost_penalty_term]),
  );

  const stateElements: { key: keyof StateExport["plain_language"]; label: string }[] = [
    { key: "volatility", label: "Volatility" },
    { key: "dispersion", label: "Dispersion" },
    { key: "correlation", label: "Correlation" },
    { key: "breadth", label: "Breadth" },
    { key: "trend", label: "Trend" },
    { key: "liquidity", label: "Liquidity" },
    { key: "slippage", label: "Slippage" },
  ];

  return (
    <div className="space-y-6">
      {/* ── Market state, in plain words — reuses WW-STATE's own renderer ── */}
      <Card title="Market state — plain language (WW-STATE)">
        {!state ? (
          <div className="py-4 text-center">
            <p className="eyebrow">Not available</p>
            <p className="mt-2 text-xs text-muted">No WW-STATE export found — market state cannot be shown.</p>
          </div>
        ) : (
          <>
            <ul className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              {stateElements.map(({ key, label }) => (
                <li key={key} className="flex items-baseline justify-between gap-3 border-t border-hairline pt-2">
                  <span className="text-xs uppercase tracking-wide text-muted">{label}</span>
                  <span className="text-right text-foreground/90">{state.plain_language[key]}</span>
                </li>
              ))}
            </ul>
            <p className="mt-4 text-[11px] text-muted">
              State as of {state.as_of} · generated {state.generated_at}
            </p>
            {state.universe_note && (
              <p className="mt-1 text-[11px] text-amber-700 dark:text-amber-400">{state.universe_note}</p>
            )}
            <p className="mt-2 text-[11px] text-muted">{state.disclaimer}</p>
          </>
        )}
      </Card>

      {/* ── Budgets by strategy — current, previous, delta, and why ── */}
      <Card title="Capital allocator — budgets by strategy (WW-ALLOC)">
        {!alloc ? (
          <div className="py-4 text-center">
            <p className="eyebrow">Not available</p>
            <p className="mt-2 text-xs text-muted">No WW-ALLOC export found — budgets cannot be shown.</p>
          </div>
        ) : (
          <>
            {alloc.generatedBy.toLowerCase().includes("sample") && (
              <div className="mb-4 border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
                ⚠ <strong>SAMPLE — {alloc.generatedBy}.</strong>
              </div>
            )}
            <div className="space-y-5">
              {strategies.map((s) => {
                const overridden =
                  activeOverride && (activeOverride.strategy === s.name || activeOverride.strategy === "__desk__");
                return (
                  <div key={s.name} className="border-t border-hairline pt-3 first:border-t-0 first:pt-0">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-foreground">{s.name}</span>
                        {s.shadow_mode && <Badge tone="neutral">Shadow mode</Badge>}
                        {overridden && <Badge tone="warn">Manual override</Badge>}
                      </div>
                      <div className="flex items-baseline gap-3 text-sm tabular-nums">
                        <span className="text-muted">prev {pctUnsigned(s.previous_budget)}</span>
                        <span className="font-semibold text-foreground">now {pctUnsigned(s.budget)}</span>
                        <span className={s.delta >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-rose-600 dark:text-rose-400"}>
                          {pctSigned(s.delta)}
                        </span>
                      </div>
                    </div>

                    <UtilityBreakdown s={s} maxMag={maxMag} />
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-muted">
                      <span><span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" /> edge {pctUnsigned(s.shrunk_edge, 2)}</span>
                      <span><span className="inline-block h-1.5 w-1.5 rounded-full bg-amber-500" /> uncertainty −{pctUnsigned(s.uncertainty_penalty_term, 2)}</span>
                      <span><span className="inline-block h-1.5 w-1.5 rounded-full bg-rose-500" /> cost −{pctUnsigned(s.cost_penalty_term, 2)}</span>
                      <span>score {s.score >= 0 ? "+" : ""}{pctUnsigned(s.score, 2)}</span>
                    </div>
                    {s.binding_constraints.length > 0 && (
                      <p className="mt-1 text-[11px] text-muted">
                        Binding: {s.binding_constraints.join(", ")}
                      </p>
                    )}
                  </div>
                );
              })}
            </div>

            <p className="mt-5 text-[11px] text-muted">
              As of {alloc.as_of} · generated {alloc.generated_at} · feasible: {alloc.feasible ? "yes" : "no"} · fallback used: {alloc.fallback_used ? "yes" : "no"}
              {alloc.fallback_reason ? ` (${alloc.fallback_reason})` : ""}
            </p>
            <p className="mt-1 text-[11px] text-muted">{alloc.disclaimer}</p>
          </>
        )}
      </Card>

      {/* ── Manual override — client-state only, real countdown, auto-revert ── */}
      <Card title="Manual override">
        <p className="text-xs text-muted">
          UI-only demonstration: this override lives only in React state in your
          browser tab. It is <strong>not</strong> persisted to any backend or
          database — reloading this page clears it immediately, the same way it
          clears itself automatically when the time limit elapses.
        </p>

        {activeOverride ? (
          <div className="mt-4 border border-amber-500/50 bg-amber-500/10 px-3 py-3 text-sm">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="font-medium text-amber-700 dark:text-amber-400">
                Active override — {activeOverride.strategy === "__desk__" ? "desk-wide" : activeOverride.strategy}
              </span>
              <span className="tabular-nums text-xs text-amber-700 dark:text-amber-400">
                reverts in {formatCountdown(msRemaining)}
              </span>
            </div>
            <p className="mt-1 text-xs text-foreground/80">&ldquo;{activeOverride.reason}&rdquo;</p>
            <button
              type="button"
              onClick={() => setActiveOverride(null)}
              className="mt-2 border border-hairline px-2 py-1 text-[11px] uppercase tracking-wide text-muted hover:text-foreground"
            >
              Cancel override now
            </button>
          </div>
        ) : (
          <p className="mt-4 text-xs text-muted">No override active.</p>
        )}

        <form onSubmit={submitOverride} className="mt-4 space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="text-xs">
              <span className="mb-1 block text-muted">Strategy</span>
              <select
                value={strategyDraft}
                onChange={(e) => setStrategyDraft(e.target.value)}
                className="w-full border border-hairline bg-background px-2 py-1.5 text-sm"
              >
                <option value="__desk__">Desk-wide</option>
                {strategies.map((s) => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs">
              <span className="mb-1 block text-muted">Time limit</span>
              <select
                value={durationDraft}
                onChange={(e) => setDurationDraft(Number(e.target.value))}
                className="w-full border border-hairline bg-background px-2 py-1.5 text-sm"
              >
                {OVERRIDE_DURATIONS.map((d) => (
                  <option key={d.minutes} value={d.minutes}>
                    {d.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs sm:col-span-1">
              <span className="mb-1 block text-muted">Reason (required)</span>
              <input
                type="text"
                value={reasonDraft}
                onChange={(e) => setReasonDraft(e.target.value)}
                placeholder="Why override the allocator right now?"
                className="w-full border border-hairline bg-background px-2 py-1.5 text-sm"
              />
            </label>
          </div>
          {formError && <p className="text-xs text-rose-600 dark:text-rose-400">{formError}</p>}
          <button
            type="submit"
            className="border border-foreground bg-foreground px-3 py-1.5 text-xs font-medium uppercase tracking-wide text-background hover:opacity-90"
          >
            Apply override
          </button>
        </form>
      </Card>
    </div>
  );
}

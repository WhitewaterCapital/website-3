"use client";

// Shared result panels for a single ticker's model output. Pulled out of
// StressTestClient.tsx and EquityReader.tsx so the new Ticker Hub (and any
// future page) can render the exact same Distresse / Entry & Exit / equity
// fundamentals cards instead of duplicating the markup — one panel, every
// place a ticker's results show up.

import { useState } from "react";
import { Card, Badge } from "@/components/ui";
import { ScoreBar } from "@/components/ScoreBar";
import type { StressVerdict, EntryExitPlan } from "@/lib/models/types";
import type { SecurityAnalysis } from "@/lib/models/incepta-export";

const dash = "—";
const ratingTone = { go: "up", conditional: "warn", "no-go": "down" } as const;
const confTone = {
  high: "neutral",
  medium: "warn",
  low: "warn",
  insufficient: "down",
} as const;

const pct = (x: number | null | undefined, signed = false) =>
  x == null ? dash : `${signed && x > 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
const ratio = (x: number | null | undefined, d = 2) =>
  x == null ? dash : x.toFixed(d);
const price = (x: number | null | undefined) =>
  x == null ? dash : `$${x.toFixed(2)}`;
const bps = (x: number | null | undefined) =>
  x == null ? dash : `${x.toFixed(0)} bps`;
const money = (x: number | null | undefined) => {
  if (x == null) return dash;
  const a = Math.abs(x);
  if (a >= 1e12) return `$${(x / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `$${(x / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `$${(x / 1e6).toFixed(1)}M`;
  return `$${x.toFixed(0)}`;
};

// ── Distresse — the stress-test verdict ─────────────────────────────────────
export function DistressePanel({ v }: { v: StressVerdict }) {
  return (
    <Card
      title="Distresse — stress test"
      action={<Badge tone={ratingTone[v.rating]}>{v.rating.toUpperCase()}</Badge>}
    >
      {v.generatedBy.includes("sample") && (
        <div className="mb-4 border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
          ⚠ <strong>SAMPLE — placeholder scoring, not a real model.</strong> The
          rating and conviction below are illustrative RNG, not analysis. Do not
          use for real decisions until the Distresse model is built.
        </div>
      )}
      <div className="flex items-baseline justify-between">
        <span className="text-sm text-muted">{v.ticker} · {v.instrument}</span>
        <span className="text-sm text-muted">
          conviction <span className="font-semibold text-foreground">{v.conviction}</span>/100
        </span>
      </div>
      <p className="mt-2 text-xs text-muted">Regime: {v.regime}</p>

      <div className="mt-5 space-y-3">
        {v.dimensions.map((d) => (
          <div key={d.label}>
            <div className="flex items-center justify-between text-xs">
              <span className="font-medium">{d.label}</span>
              <span className={`tabular-nums ${d.score >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                {d.score > 0 ? "+" : ""}
                {d.score}
              </span>
            </div>
            <div className="mt-1"><ScoreBar score={d.score} /></div>
            <p className="mt-1 text-xs text-muted">{d.note}</p>
          </div>
        ))}
      </div>

      <Section title="Devil's advocate">
        <ul className="space-y-1.5">
          {v.devilsAdvocate.map((d, i) => (
            <li key={i} className="text-sm text-foreground/80">— {d}</li>
          ))}
        </ul>
      </Section>
      <Section title="Tail risks">
        <ul className="space-y-1.5">
          {v.tailRisks.map((t, i) => (
            <li key={i} className="text-sm text-foreground/80">— {t}</li>
          ))}
        </ul>
      </Section>

      <div className="mt-5 border-t border-hairline pt-4">
        <p className="eyebrow">Bottom line</p>
        <p className="mt-1 text-sm">{v.bottomLine}</p>
      </div>
      <p className="mt-3 text-[11px] text-muted">{v.generatedBy}</p>
    </Card>
  );
}

// ── Entry & Exit — the levels plan ──────────────────────────────────────────
export function IntraPanel({ p }: { p: EntryExitPlan }) {
  // The engine abstains by publishing literal NaN in the numeric fields
  // (see impl/intra-exitus.ts) rather than a fabricated band. Showing raw
  // "NaN – NaN" to a member is its own bug on top of the abstain, so catch
  // it here and render the honest rationale instead of broken numbers.
  const abstained = Number.isNaN(p.stop);

  return (
    <Card
      title="Entry & Exit"
      action={
        !abstained && (
          <Badge tone={p.bias === "long" ? "up" : "down"}>{p.bias.toUpperCase()}</Badge>
        )
      }
    >
      {abstained ? (
        <p className="text-sm text-foreground/80">{p.rationale}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Entry zone" value={`${p.entryZone[0]} – ${p.entryZone[1]}`} />
            <Field label="Stop" value={String(p.stop)} tone="down" />
            <Field label="Targets" value={p.targets.join("  ·  ")} tone="up" />
            <Field label="Size" value={`${p.sizingPct}% of book`} />
          </div>

          <Section title="Time stop">
            <p className="text-sm text-foreground/80">{p.timeStop}</p>
          </Section>
          <Section title="Rationale">
            <p className="text-sm text-foreground/80">{p.rationale}</p>
          </Section>
          <Section title="Invalidations">
            <ul className="space-y-1.5">
              {p.invalidations.map((inv, i) => (
                <li key={i} className="text-sm text-foreground/80">— {inv}</li>
              ))}
            </ul>
          </Section>
        </>
      )}
      <p className="mt-4 text-[11px] text-muted">{p.generatedBy}</p>
    </Card>
  );
}

export function Field({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "up" | "down";
}) {
  return (
    <div>
      <div className="eyebrow">{label}</div>
      <div
        className={`mt-1 text-sm font-semibold tabular-nums ${
          tone === "up" ? "text-emerald-500" : tone === "down" ? "text-rose-500" : ""
        }`}
      >
        {value}
      </div>
    </div>
  );
}

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="mt-5">
      <p className="eyebrow">{title}</p>
      <div className="mt-1.5">{children}</div>
    </div>
  );
}

// ── Equity fundamentals — Incepta's risk/quality/valuation read ────────────
export function SecurityCard({
  s,
  showStressAction = true,
}: {
  s: SecurityAnalysis;
  /** Show the "stress-test this evidence" button. Off when the caller (e.g.
   * the Ticker Hub) already shows a Distresse panel of its own. */
  showStressAction?: boolean;
}) {
  const insufficient = s.confidence === "insufficient";
  const greyed = insufficient || s.confidence === "low";
  const allFlags = [
    ...(s.data_quality.flags ?? []),
    ...(s.valuation?.flags ?? []),
  ];

  return (
    <section
      className={`border border-hairline bg-paper p-5 ${greyed ? "opacity-60" : ""}`}
    >
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h4 className="text-lg font-semibold">{s.ticker}</h4>
            <Badge tone={confTone[s.confidence]}>{s.confidence}</Badge>
          </div>
          <p className="text-sm text-muted">
            {s.name ?? dash}
            {s.sector ? ` · ${s.sector}` : ""}
          </p>
        </div>
        <div className="text-right text-xs text-muted">
          <div className="tabular-nums text-foreground">
            {price(s.data_quality.price_last_close)}
          </div>
          <div>as of {s.as_of}</div>
        </div>
      </div>

      {/* Flags — the honesty layer */}
      {allFlags.length > 0 && (
        <ul className="mt-3 space-y-1">
          {allFlags.map((f, i) => (
            <li key={i} className="text-xs text-amber-600 dark:text-amber-400">
              ⚠ {f}
            </li>
          ))}
        </ul>
      )}

      {insufficient ? (
        <p className="mt-4 text-sm text-muted">
          Not enough data — the engine abstains rather than show unreliable
          numbers.
        </p>
      ) : (
        <>
          <div className="mt-5 grid gap-6 sm:grid-cols-3">
            <MetricGroup
              title="Risk"
              empty={!s.risk && "No price history."}
              rows={
                s.risk && [
                  ["12-1 momentum", pct(s.risk.mom_12_1, true)],
                  ["1m return", pct(s.risk.ret_1m, true)],
                  ["Realized vol", pct(s.risk.realized_vol)],
                  ["Downside vol", pct(s.risk.downside_vol)],
                  ["Max DD (1y)", pct(s.risk.max_dd_1y, true)],
                  ["52w-high ratio", ratio(s.risk.high_52w_ratio)],
                  ["Beta (mkt)", ratio(s.risk.beta_mkt)],
                  ["Idio vol", pct(s.risk.idio_vol)],
                  ["Est. spread", bps(s.risk.spread_bps)],
                ]
              }
            />
            <MetricGroup
              title="Quality"
              empty={!s.quality && "No fundamentals."}
              rows={
                s.quality && [
                  ["ROA", pct(s.quality.roa)],
                  ["ROE", pct(s.quality.roe)],
                  ["Gross margin", pct(s.quality.gross_margin)],
                  ["Net margin", pct(s.quality.net_margin)],
                  ["FCF margin", pct(s.quality.fcf_margin)],
                  ["Rev growth", pct(s.quality.rev_growth, true)],
                  ["Leverage", ratio(s.quality.leverage)],
                  [
                    "Piotroski",
                    s.quality.piotroski_f == null
                      ? dash
                      : `${s.quality.piotroski_f} / ${s.quality.piotroski_max ?? 9}`,
                  ],
                ]
              }
            />
            <MetricGroup
              title="Valuation"
              empty={!s.valuation && "No valuation."}
              rows={
                s.valuation && [
                  ["Market cap", money(s.valuation.market_cap)],
                  ["P/E", ratio(s.valuation.pe, 1)],
                  ["Earnings yield", pct(s.valuation.earnings_yield)],
                  ["P/B", ratio(s.valuation.pb, 1)],
                  ["P/S", ratio(s.valuation.ps, 1)],
                  ["FCF yield", pct(s.valuation.fcf_yield)],
                  ["EV/Sales", ratio(s.valuation.ev_sales, 1)],
                ]
              }
            />
          </div>

          {showStressAction && <StressAction ticker={s.ticker} />}
        </>
      )}
    </section>
  );
}

function MetricGroup({
  title,
  rows,
  empty,
}: {
  title: string;
  rows: [string, string][] | null | undefined | false;
  empty: string | false | undefined;
}) {
  return (
    <div>
      <div className="eyebrow mb-2">{title}</div>
      {rows ? (
        <dl className="space-y-1.5">
          {rows.map(([k, v]) => (
            <div key={k} className="flex items-center justify-between text-sm">
              <dt className="text-muted">{k}</dt>
              <dd className="tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-sm text-muted">{empty || dash}</p>
      )}
    </div>
  );
}

// Per-trade flow: feed this security into Distresse via /api/models/stress.
function StressAction({ ticker }: { ticker: string }) {
  const [state, setState] = useState<"idle" | "loading" | "done" | "error">("idle");
  const [verdict, setVerdict] = useState<StressVerdict | null>(null);

  async function run() {
    setState("loading");
    try {
      const res = await fetch("/api/models/stress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker, instrument: "long" }),
      });
      const data = await res.json();
      setVerdict(data.distresse);
      setState("done");
    } catch {
      setState("error");
    }
  }

  const ratingToneLocal = { go: "up", conditional: "warn", "no-go": "down" } as const;

  return (
    <div className="mt-5 border-t border-hairline pt-4">
      {!verdict ? (
        <button
          onClick={run}
          disabled={state === "loading"}
          className="text-xs font-medium text-accent hover:underline disabled:opacity-50"
        >
          {state === "loading"
            ? "Running Distresse…"
            : "Stress-test this evidence in Distresse →"}
        </button>
      ) : (
        <div>
          {verdict.generatedBy.includes("sample") && (
            <p className="mb-2 text-[11px] text-amber-600 dark:text-amber-400">
              ⚠ SAMPLE — placeholder scoring, not a real model.
            </p>
          )}
          <div className="flex items-center gap-2">
            <span className="eyebrow">Distresse</span>
            <Badge tone={ratingToneLocal[verdict.rating]}>{verdict.rating}</Badge>
            <span className="text-xs text-muted">
              conviction {verdict.conviction}/100
            </span>
          </div>
          <p className="mt-2 text-sm text-foreground/80">{verdict.bottomLine}</p>
          <p className="mt-2 text-[11px] text-muted">{verdict.generatedBy}</p>
        </div>
      )}
      {state === "error" && (
        <p className="text-xs text-rose-500">Couldn&apos;t reach Distresse.</p>
      )}
    </div>
  );
}

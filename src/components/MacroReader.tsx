"use client";

import { useState } from "react";
import type {
  MacroExport,
  Scenario,
  RegimeRead,
  RegimeTilt,
  Nowcast,
  SteadyState,
  Confidence,
} from "@/lib/models/aurora-export";
import { Badge, Card } from "@/components/ui";

// ── Honesty formatters. null → "—" always, never 0. ────────────────────────
const dash = "—";
const pct = (x: number | null | undefined, d = 1, signed = false) =>
  x == null ? dash : `${signed && x > 0 ? "+" : ""}${(x * 100).toFixed(d)}%`;
const num = (x: number | null | undefined, d = 2, signed = false) =>
  x == null ? dash : `${signed && x > 0 ? "+" : ""}${x.toFixed(d)}`;

// Scenario path/effect values: pct_dev & level are already in % points; bps in bps.
function fmtUnit(x: number | null | undefined, unit: string, signed = true) {
  if (x == null) return dash;
  const s = signed && x > 0 ? "+" : "";
  if (unit === "bps") return `${s}${x.toFixed(1)} bps`;
  return `${s}${x.toFixed(2)}%`;
}

const confTone = {
  high: "neutral",
  medium: "warn",
  low: "warn",
  insufficient: "down",
} as const;

function Conf({ c }: { c: Confidence }) {
  return <Badge tone={confTone[c]}>{c} confidence</Badge>;
}

// ═══════════════════════════════════════════════════════════════════════════
export function MacroReader({
  data,
  onHandoffToEquity,
}: {
  data: MacroExport;
  onHandoffToEquity?: () => void;
}) {
  return (
    <div className="space-y-10">
      {/* Framing + disclaimer */}
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Macro research</Badge>
          <span className="text-xs text-muted">
            Directional scenario analysis · not advice, not a forecast
          </span>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">{data.disclaimer}</p>
        {/* Two distinct timestamps, never merged: data as-of vs. when this run
            was computed. */}
        <p className="mt-2 font-mono text-[11px] text-muted">
          Aurora {data.schema_version} · engine {data.engine_version} ·{" "}
          {data.model_variant} · data as of {data.as_of} · computed{" "}
          {data.generated_at}
        </p>
      </div>

      <RegimeCard regime={data.regime} />
      <SteadyStateCard s={data.steady_state} />
      <ScenarioBrowser scenarios={data.scenarios} />
      <TiltCard tilt={data.tilt} onHandoffToEquity={onHandoffToEquity} />
      <NowcastCard nowcast={data.nowcast} />
    </div>
  );
}

// ── Regime — where the live economy is now ─────────────────────────────────
function RegimeCard({ regime }: { regime: RegimeRead | null }) {
  if (!regime) {
    return (
      <Block title="Current environment">
        <p className="text-sm text-muted">
          Not yet available — the live regime read comes online with the FRED
          data layer.
        </p>
      </Block>
    );
  }
  const probs = regime.probabilities
    ? Object.entries(regime.probabilities).sort((a, b) => b[1] - a[1])
    : [];
  return (
    <Block
      title="Current environment"
      action={<Conf c={regime.confidence} />}
    >
      {regime.confidence === "insufficient" ? (
        <p className="text-sm text-muted">Not enough data for a regime call yet.</p>
      ) : (
        <>
          <div className="flex items-baseline justify-between">
            <h3 className="text-xl font-semibold">{regime.label ?? dash}</h3>
            <span className="text-xs text-muted">as of {regime.as_of}</span>
          </div>

          {probs.length > 0 && (
            <div className="mt-4 space-y-1.5">
              {probs.map(([name, p]) => (
                <div key={name} className="flex items-center gap-3 text-sm">
                  <span className="w-56 shrink-0 text-muted">{name}</span>
                  <div className="h-2 flex-1 rounded-full bg-foreground/10">
                    <div
                      className="h-full rounded-full bg-foreground/70"
                      style={{ width: `${Math.round(p * 100)}%` }}
                    />
                  </div>
                  <span className="w-12 text-right tabular-nums">{pct(p, 0)}</span>
                </div>
              ))}
            </div>
          )}

          <div className="mt-5">
            <p className="eyebrow mb-2">Key indicators</p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="pb-2 font-medium">Indicator</th>
                    <th className="pb-2 text-right font-medium">Value</th>
                    <th className="pb-2 text-right font-medium">z-score</th>
                    <th className="pb-2 text-right font-medium">As of</th>
                  </tr>
                </thead>
                <tbody>
                  {regime.key_indicators.map((k) => (
                    <tr key={k.name} className="border-t border-hairline">
                      <td className="py-1.5">{k.name}</td>
                      <td className="py-1.5 text-right tabular-nums">{num(k.value)}</td>
                      <td className="py-1.5 text-right tabular-nums">{num(k.z_score, 2, true)}</td>
                      <td className="py-1.5 text-right text-xs text-muted">{k.as_of ?? dash}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {regime.flags.length > 0 && (
            <ul className="mt-4 space-y-1">
              {regime.flags.map((f, i) => (
                <li key={i} className="text-xs text-amber-600 dark:text-amber-400">
                  ⚠ {f}
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </Block>
  );
}

// ── Steady state — the model's calibrated "normal" ─────────────────────────
function SteadyStateCard({ s }: { s: SteadyState }) {
  const rows: [string, string][] = [
    ["Capital / output", num(s.KYrat)],
    ["Housing / output", num(s.HYrat)],
    ["Hours worked", num(s.Nfrac)],
    ["Mortgage burden (of income)", pct(s.MPfrac)],
    ["Implied mortgage rate", pct(s.mortgage_rate_ann, 2)],
    ["Amortisation rate", pct(s.gamma, 2)],
  ];
  return (
    <Block title="Steady state — the model's normal">
      <div className="grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-3">
        {rows.map(([k, v]) => (
          <div key={k}>
            <div className="eyebrow">{k}</div>
            <div className="mt-1 text-lg font-semibold tabular-nums">{v}</div>
          </div>
        ))}
      </div>
      <p className="mt-4 text-xs text-muted">
        Calibrated to a residual norm of {s.residual_norm.toExponential(1)} (exact
        vs. the reference model).
      </p>
    </Block>
  );
}

// ── Scenarios — the core product ───────────────────────────────────────────
function ScenarioBrowser({ scenarios }: { scenarios: Scenario[] }) {
  const [active, setActive] = useState(0);
  const s = scenarios[active];

  if (!s) {
    return (
      <Block title="Scenarios — shocks & the economy's response">
        <p className="text-sm text-muted">
          Not yet available — no scenarios in this run.
        </p>
      </Block>
    );
  }

  const unitOf = (v: string) =>
    s.paths.find((p) => p.variable === v)?.unit ?? "pct_dev";

  return (
    <Block title="Scenarios — shocks & the economy's response">
      <div className="flex flex-wrap gap-2">
        {scenarios.map((sc, i) => (
          <button
            key={sc.id}
            onClick={() => setActive(i)}
            className={`border px-3 py-1.5 text-xs font-medium transition ${
              i === active
                ? "border-foreground bg-foreground text-background"
                : "border-hairline text-muted hover:border-foreground/40 hover:text-foreground"
            }`}
          >
            {sc.label}
          </button>
        ))}
      </div>

      <div className="mt-6">
        <div className="flex items-center gap-2">
          <h3 className="text-lg font-semibold">{s.label}</h3>
          <Conf c={s.confidence} />
        </div>
        <p className="mt-1 text-sm text-muted">{s.description}</p>

        {/* Effects: direction (impact), magnitude (peak), mean-reversion */}
        <div className="mt-5 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-muted">
                <th className="pb-2 font-medium">Variable</th>
                <th className="pb-2 text-center font-medium">Dir.</th>
                <th className="pb-2 text-right font-medium">On impact</th>
                <th className="pb-2 text-right font-medium">Peak</th>
                <th className="pb-2 font-medium"></th>
              </tr>
            </thead>
            <tbody>
              {s.effects.map((e) => {
                const unit = unitOf(e.variable);
                const dir =
                  e.impact == null
                    ? { ch: dash, cls: "text-muted" }
                    : e.impact > 0
                      ? { ch: "↑", cls: "text-emerald-500" }
                      : e.impact < 0
                        ? { ch: "↓", cls: "text-rose-500" }
                        : { ch: "→", cls: "text-muted" };
                return (
                  <tr key={e.variable} className="border-t border-hairline align-top">
                    <td className="py-2 capitalize">{e.variable.replace(/_/g, " ")}</td>
                    <td className={`py-2 text-center text-base ${dir.cls}`}>{dir.ch}</td>
                    <td className="py-2 text-right tabular-nums">{fmtUnit(e.impact, unit)}</td>
                    <td className="py-2 text-right tabular-nums">
                      {fmtUnit(e.peak, unit)}
                      <span className="ml-1 text-xs text-muted">Q{e.peak_quarter}</span>
                    </td>
                    <td className="py-2">
                      {e.reverses && (
                        <Badge tone="neutral">mean-reverts</Badge>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {/* Impulse-response paths as sparklines */}
        <div className="mt-6 grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {s.paths.map((p) => (
            <div key={p.variable}>
              <div className="flex items-center justify-between text-xs">
                <span className="capitalize text-muted">
                  {p.variable.replace(/_/g, " ")}
                </span>
                <span className="font-mono text-[10px] text-muted">{p.unit}</span>
              </div>
              <PathSparkline path={p.path} />
            </div>
          ))}
        </div>

        <div className="mt-6 border-t border-hairline pt-4">
          <p className="eyebrow">Read for the book</p>
          <p className="mt-1 text-sm">{s.narrative}</p>
        </div>
      </div>
    </Block>
  );
}

function PathSparkline({ path }: { path: (number | null)[] }) {
  const width = 240;
  const height = 48;
  const pts = path
    .map((v, i) => ({ i, v }))
    .filter((p): p is { i: number; v: number } => p.v != null);
  if (pts.length < 2)
    return <div className="mt-1 text-xs text-muted">— no path</div>;

  const vals = pts.map((p) => p.v);
  const min = Math.min(0, ...vals);
  const max = Math.max(0, ...vals);
  const span = max - min || 1;
  const n = path.length;
  const x = (i: number) => (i / (n - 1)) * width;
  const y = (v: number) => height - ((v - min) / span) * (height - 6) - 3;

  const line = pts
    .map((p, k) => `${k === 0 ? "M" : "L"} ${x(p.i).toFixed(1)} ${y(p.v).toFixed(1)}`)
    .join(" ");
  const zeroY = y(0);

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="mt-1 w-full text-foreground">
      <line x1={0} x2={width} y1={zeroY} y2={zeroY} className="stroke-foreground/15" strokeWidth={1} />
      <path d={line} fill="none" stroke="currentColor" strokeWidth={1.5} strokeLinejoin="round" />
    </svg>
  );
}

// ── Tilt — macro sets the weather; hand to Incepta for the names ───────────
function TiltCard({
  tilt,
  onHandoffToEquity,
}: {
  tilt: RegimeTilt | null;
  onHandoffToEquity?: () => void;
}) {
  if (!tilt) {
    return (
      <Block title="Positioning tilt">
        <p className="text-sm text-muted">
          Not yet available — the regime-conditioned tilt comes online with the
          live data layer.
        </p>
      </Block>
    );
  }
  const lean = (l: string) =>
    l === "overweight"
      ? "text-emerald-600 dark:text-emerald-400"
      : l === "underweight"
        ? "text-rose-600 dark:text-rose-400"
        : "text-muted";

  return (
    <Block title="Positioning tilt" action={<Conf c={tilt.confidence} />}>
      <p className="text-sm text-muted">
        Macro sets the weather — the lean below; the equity model picks the names.
      </p>

      <div className="mt-4 grid gap-6 sm:grid-cols-2">
        <LeanList title="Factors" items={tilt.factors} leanClass={lean} />
        <LeanList title="Sectors" items={tilt.sectors} leanClass={lean} />
      </div>

      {onHandoffToEquity && (
        <button
          onClick={onHandoffToEquity}
          className="mt-5 text-xs font-medium text-accent hover:underline"
        >
          See the names in Equity →
        </button>
      )}
    </Block>
  );
}

function LeanList({
  title,
  items,
  leanClass,
}: {
  title: string;
  items: { name: string; lean: string; rationale: string }[];
  leanClass: (l: string) => string;
}) {
  return (
    <div>
      <p className="eyebrow mb-2">{title}</p>
      {items.length === 0 ? (
        <p className="text-sm text-muted">No {title.toLowerCase()} lean.</p>
      ) : (
        <ul className="space-y-2">
          {items.map((it) => (
            <li key={it.name} className="text-sm">
              <span className="font-medium capitalize">{it.name}</span>{" "}
              <span className={`uppercase text-xs ${leanClass(it.lean)}`}>
                {it.lean}
              </span>
              <div className="text-xs text-muted">{it.rationale}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

// ── Nowcast — factor model, honesty-gated ──────────────────────────────────
function NowcastCard({ nowcast }: { nowcast: Nowcast | null }) {
  if (!nowcast) {
    return (
      <Block title="Factor nowcast">
        <p className="text-sm text-muted">
          Not yet available — the trained factor model comes online in a later
          phase.
        </p>
      </Block>
    );
  }
  return (
    <Block title="Factor nowcast" action={<Conf c={nowcast.confidence} />}>
      <p className="text-sm">{nowcast.summary}</p>
      <div className="mt-3 border-l-2 border-hairline pl-3">
        <p className="eyebrow">Read for the book</p>
        <p className="mt-1 text-sm text-foreground/80">{nowcast.book_read}</p>
      </div>

      <div className="mt-5 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted">
              <th className="pb-2 font-medium">Factor</th>
              <th className="pb-2 text-right font-medium">Expected ({nowcast.horizon_months}m)</th>
              <th className="pb-2 text-right font-medium">OOS R²</th>
              <th className="pb-2 text-right font-medium">Hit rate</th>
            </tr>
          </thead>
          <tbody>
            {nowcast.factors.map((f) => (
              <tr key={f.factor} className="border-t border-hairline">
                <td className="py-2 font-medium">{f.factor}</td>
                <td className="py-2 text-right tabular-nums">
                  {f.skillful && f.expected_return != null ? (
                    pct(f.expected_return / 100, 2, true)
                  ) : (
                    <span className="text-xs text-muted">no out-of-sample signal</span>
                  )}
                </td>
                <td className={`py-2 text-right tabular-nums ${f.oos_r2 > 0 ? "text-emerald-500" : "text-muted"}`}>
                  {pct(f.oos_r2, 1, true)}
                </td>
                <td className="py-2 text-right tabular-nums">{pct(f.hit_rate, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 font-mono text-[11px] text-muted">
        {nowcast.method} · as of {nowcast.as_of}
      </p>
    </Block>
  );
}

// ── Shared block wrapper — the site's own Card (src/components/ui.tsx). This
// used to be a locally-defined lookalike with the same border-hairline/
// bg-paper shape; now it just is Card, so this reader stays byte-for-byte
// in step with every other Card-using page instead of a parallel copy. ──────
const Block = Card;

"use client";

// Shared result panels for a single ticker's model output. Pulled out of
// StressTestClient.tsx and EquityReader.tsx so the new Ticker Hub (and any
// future page) can render the exact same Distresse / Entry & Exit / equity
// fundamentals cards instead of duplicating the markup — one panel, every
// place a ticker's results show up.

import { useState } from "react";
import { Card, Badge, Stat } from "@/components/ui";
import { ScoreBar } from "@/components/ScoreBar";
import type { StressVerdict, EntryExitPlan } from "@/lib/models/types";
import type { SecurityAnalysis } from "@/lib/models/incepta-export";
import type { OptionsSummary } from "@/lib/models/options-export";
import type { InsiderReading, InsiderTransaction } from "@/lib/models/insider-export";

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
              {d.available ? (
                <span className={`tabular-nums ${d.score >= 0 ? "text-emerald-500" : "text-rose-500"}`}>
                  {d.score > 0 ? "+" : ""}
                  {d.score}
                </span>
              ) : (
                <span className="text-muted">n/a</span>
              )}
            </div>
            {/* An unavailable dimension gets no bar and no number — a real
               source had nothing usable here, so nothing is fabricated to
               fill the space. See types.ts's Dimension.available. */}
            {d.available && (
              <div className="mt-1">
                <ScoreBar score={d.score} />
              </div>
            )}
            <p className={`mt-1 text-xs ${d.available ? "text-muted" : "italic text-muted/80"}`}>{d.note}</p>
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

// ── Options / implied volatility — Alpha Vantage read ───────────────────────
// This panel is DELIBERATELY separate from Entry & Exit and never merged
// into it (see this task's spec, and TickerHubClient's VerdictCard comment
// block for why it also never feeds conviction.ts): Entry & Exit's
// stop/targets are this platform's own price-based levels; the numbers here
// are what the OPTIONS MARKET itself is pricing in, as complementary
// context. `p` (Entry & Exit's plan) is optional and used ONLY to print one
// extra sentence comparing the stop distance to the options-implied move —
// it never changes any number this panel shows on its own.
//
// FORMERLY backed by Tradier's sandbox (see git history) — switched to
// Alpha Vantage after the fund's owner discovered Tradier's sandbox now
// requires full identity verification to sign up, contrary to the stale
// 2014 blog post the earlier research had relied on. See
// src/lib/whitewatch-data/alphavantage-options.js's header for the full,
// honest research writeup, including a question this task explicitly asked
// to be resolved and could NOT be resolved with certainty: whether Alpha
// Vantage's options endpoint even works on a free (non-paid) API key at
// all, or is gated behind a paid plan. `plan_gated` and `rate_limited`
// below exist specifically because of that unresolved question.
export function OptionsPanel({ o, p }: { o: OptionsSummary; p?: EntryExitPlan }) {
  return (
    <Card title="Options market — implied move" action={<StatusBadge status={o.status} />}>
      {/* Always-visible caveat — per this task's requirement that a member
         sizing a real trade off this panel must see the real terms WHERE
         THEY'D READ IT, not buried in a code comment. Shown regardless of
         status, including the abstention states, since even a "no data" or
         "not applicable" card is still labeled Alpha Vantage.
         Deliberately does NOT claim a specific "X minutes delayed" figure
         the way the old Tradier banner did — no equivalently explicit,
         directly-quoted freshness figure could be confirmed for Alpha
         Vantage's HISTORICAL_OPTIONS endpoint (see alphavantage-options.js).
         What IS said below (end-of-day dataset, "as of" a specific trading
         day, ~25 requests/day platform-wide budget) are the things that
         WERE confirmed. */}
      <div className="mb-4 border border-sky-500/40 bg-sky-500/10 px-3 py-2 text-xs text-sky-800 dark:text-sky-300">
        Alpha Vantage <strong>HISTORICAL_OPTIONS</strong> data — an end-of-day dataset (
        {o.quoteDate ? `as of ${o.quoteDate}` : "as of the most recent trading day Alpha Vantage returns"}), not a
        live intraday feed. Alpha Vantage&apos;s free tier allows roughly <strong>25 requests/day, platform-wide</strong> —
        this panel is cached for 24 hours per ticker specifically to protect that budget, so a repeat search on a
        ticker already looked up today reuses the cached read rather than spending another request. Do not use this
        alone to size a live trade.
      </div>

      {o.status === "not_configured" && (
        <p className="text-sm text-muted">{o.reason ?? "Alpha Vantage isn't configured."}</p>
      )}

      {o.status === "plan_gated" && (
        <>
          <p className="text-sm text-amber-600 dark:text-amber-400">
            Alpha Vantage says the options endpoint isn&apos;t available on this API key&apos;s plan — this is a
            genuinely researched possibility for Alpha Vantage&apos;s free tier (see the code comment on this panel),
            not a bug. Upgrading to a paid Alpha Vantage plan would be required to unlock this panel; retrying will
            not change this outcome on its own.
          </p>
          {o.reason && <p className="mt-2 text-xs text-muted">Alpha Vantage&apos;s own message: &quot;{o.reason}&quot;</p>}
        </>
      )}

      {o.status === "rate_limited" && (
        <>
          <p className="text-sm text-amber-600 dark:text-amber-400">
            Alpha Vantage&apos;s free-tier request limit was hit for this pull (roughly 25 requests/day,
            platform-wide, shared across every member and every ticker). This is temporary — try again later, or
            tomorrow once the daily quota resets.
          </p>
          {o.reason && <p className="mt-2 text-xs text-muted">Alpha Vantage&apos;s own message: &quot;{o.reason}&quot;</p>}
        </>
      )}

      {o.status === "not_applicable" && (
        <p className="text-sm text-muted">{o.reason ?? `No listed options for ${o.ticker}.`}</p>
      )}

      {o.status === "error" && <p className="text-sm text-rose-500">{o.reason ?? "Couldn't reach Alpha Vantage."}</p>}

      {o.status === "no_data" && (
        <>
          <p className="text-sm text-foreground/80">{o.reason ?? "No usable options data this pull."}</p>
          {(o.callOi != null || o.putOi != null) && (
            <p className="mt-2 text-xs text-muted">
              Open interest — calls {o.callOi ?? dash} · puts {o.putOi ?? dash}
              {o.putCallOi != null ? ` · put/call ratio ${o.putCallOi.toFixed(2)}` : ""}
            </p>
          )}
        </>
      )}

      {o.status === "ok" && (
        <>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Spot" value={price(o.spot)} />
            <Field label={`Expiration (${o.expirationBasis === "standard-monthly" ? "monthly" : "nearest listed"})`} value={o.expiration ?? dash} />
            <Field label="ATM strike / IV" value={`${o.atmStrike ?? dash} / ${pct(o.atmIv)}`} />
            <Field label="Days to expiration" value={String(o.daysToExpiration ?? dash)} />
          </div>

          <Section title={`Implied move to ${o.expiration}`}>
            <p className="text-sm text-foreground/80">
              The ATM straddle&apos;s implied volatility ({pct(o.atmIv)} annualized) prices in roughly a{" "}
              <strong>±{pct(o.expectedMovePct)}</strong> move ({price(o.expectedMoveDollars)}) by expiration — a
              one-standard-deviation (~68% confidence) band of {price(o.expectedMoveLow)} – {price(o.expectedMoveHigh)},
              not a hard ceiling, and it ignores volatility skew.
            </p>
            {stopVsMoveNote(o, p) && <p className="mt-2 text-sm text-foreground/80">{stopVsMoveNote(o, p)}</p>}
          </Section>

          <Section title="Positioning">
            <p className="text-sm text-foreground/80">
              Put/call open interest ratio:{" "}
              <span className="font-semibold">{o.putCallOi != null ? o.putCallOi.toFixed(2) : dash}</span>{" "}
              (calls {o.callOi ?? dash} · puts {o.putOi ?? dash} · {o.contractsCount ?? dash} contracts across this
              expiration). Descriptive only — this is NOT treated as a directional buy/sell signal anywhere on this
              platform (see the code comment on this panel for why).
            </p>
          </Section>
        </>
      )}

      <p className="mt-4 text-[11px] text-muted">{o.generatedBy}</p>
    </Card>
  );
}

function StatusBadge({ status }: { status: OptionsSummary["status"] }) {
  if (status === "ok") return <Badge tone="neutral">LIVE (end-of-day)</Badge>;
  if (status === "error") return <Badge tone="down">FETCH ERROR</Badge>;
  if (status === "plan_gated") return <Badge tone="warn">NOT ON THIS PLAN</Badge>;
  if (status === "rate_limited") return <Badge tone="warn">RATE LIMITED</Badge>;
  if (status === "not_configured") return <Badge tone="warn">NOT CONFIGURED</Badge>;
  if (status === "not_applicable") return <Badge tone="neutral">N/A</Badge>;
  return <Badge tone="warn">NO DATA</Badge>;
}

// One extra sentence bridging Entry & Exit's own stop to the options-implied
// move — additive context only (see this function's header note above);
// returns null (renders nothing) whenever Entry & Exit abstained or doesn't
// apply, rather than showing a comparison against a missing number.
function stopVsMoveNote(o: OptionsSummary, p?: EntryExitPlan): string | null {
  if (!p || Number.isNaN(p.stop) || o.spot == null || o.expectedMovePct == null) return null;
  const stopDistPct = Math.abs(p.stop - o.spot) / o.spot;
  const cmp = stopDistPct < o.expectedMovePct ? "inside" : "beyond";
  return `For reference, Entry & Exit's stop (${p.stop}) sits ${(stopDistPct * 100).toFixed(1)}% from Alpha Vantage's spot (${price(
    o.spot
  )}) — ${cmp} the options market's implied ±${pct(o.expectedMovePct)} move to ${o.expiration}.`;
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

// ── WW-Insider — SEC Form 4 insider activity, and the honest 13F gap ───────
//
// "SECURITY SPECIFIC, not opaque" (conviction.ts's own header phrase): this
// panel shows the actual filings and transactions behind the net-direction
// score conviction.ts's INSIDER_ACTIVITY_SLOT contributes — see
// TickerHubClient.tsx's insiderConvictionSlot() for that mapping — so a
// member can check the number against real, sourced filings instead of
// trusting a black box.
function InsiderStatusBadge({ status }: { status: InsiderReading["status"] }) {
  if (status === "ok") return <Badge tone="neutral">LIVE — SEC EDGAR</Badge>;
  if (status === "not_found") return <Badge tone="warn">NO CIK FOUND</Badge>;
  return <Badge tone="down">EDGAR UNREACHABLE</Badge>;
}

function formatInsiderDate(iso: string | null): string {
  if (!iso) return dash;
  const d = new Date(`${iso}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" });
}

const acquiredDisposedTone = { A: "up", D: "down" } as const;

function InsiderTransactionRow({ t }: { t: InsiderTransaction }) {
  const dollars = t.shares != null && t.pricePerShare != null ? t.shares * t.pricePerShare : null;
  return (
    <li className="border-t border-hairline py-2.5 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-sm font-medium">
          {t.insiderName ?? "Unnamed reporting person"}
          {t.insiderRoles.length > 0 && (
            <span className="ml-1.5 text-xs font-normal text-muted">({t.insiderRoles.join(", ")})</span>
          )}
        </span>
        <span className="flex items-center gap-1.5 text-xs text-muted">
          {formatInsiderDate(t.transactionDate)}
          {t.acquiredDisposedCode && (
            <Badge tone={acquiredDisposedTone[t.acquiredDisposedCode] ?? "neutral"}>{t.transactionCodeLabel}</Badge>
          )}
          {t.derivative && <Badge tone="neutral">derivative</Badge>}
          {t.isAmendment && <Badge tone="warn">amended</Badge>}
        </span>
      </div>
      <p className="mt-1 text-xs text-foreground/80">
        {t.shares != null ? t.shares.toLocaleString() : dash} shares
        {t.pricePerShare != null ? ` @ ${price(t.pricePerShare)}` : ""}
        {dollars != null ? ` (${money(dollars)})` : ""}
        {t.sharesOwnedAfter != null ? ` · ${t.sharesOwnedAfter.toLocaleString()} owned after` : ""}
        {t.ownershipType ? ` · ${t.ownershipType === "D" ? "direct" : "indirect"}` : ""}
      </p>
      <a href={t.sourceUrl} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[11px] text-accent hover:underline">
        View this Form 4 filing on SEC EDGAR →
      </a>
    </li>
  );
}

export function InsiderPanel({ r }: { r: InsiderReading }) {
  return (
    <Card title="Insider activity (WW-Insider)" action={<InsiderStatusBadge status={r.status} />}>
      {r.status === "not_found" && (
        <p className="text-sm text-muted">{r.message ?? `No SEC CIK found for ${r.ticker}.`}</p>
      )}

      {r.status === "unreachable" && (
        <p className="text-sm text-rose-500">{r.message ?? "Couldn't reach SEC EDGAR for this ticker."}</p>
      )}

      {r.status === "ok" && r.summary && (
        <>
          {r.message && (
            <div className="mb-4 border border-amber-500/50 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-400">
              ⚠ {r.message}
            </div>
          )}

          {r.summary.signalTransactionCount === 0 ? (
            <p className="text-sm text-foreground/80">
              No open-market insider buying or selling for {r.ticker} in the last {r.windowDays} days
              {r.filingsFound ? ` (${r.filingsFound} Form 4 filing${r.filingsFound === 1 ? "" : "s"} found, but none were open-market purchases/sales — see the raw filings below)` : " — SEC lists no Form 4 filings for this issuer in the window"}
              . This is a real, checked answer — not the same as SEC being unreachable or the ticker not resolving.
            </p>
          ) : (
            <div className="grid gap-6 sm:grid-cols-[auto_1fr] sm:items-start">
              <Stat
                label="Net insider direction"
                value={r.summary.score == null ? "—" : `${r.summary.score > 0 ? "+" : ""}${r.summary.score.toFixed(0)}`}
                sub="-100 (net selling) .. +100 (net buying)"
                tone={r.summary.score != null && r.summary.score > 10 ? "up" : r.summary.score != null && r.summary.score < -10 ? "down" : "neutral"}
              />
              <div className="space-y-2 text-sm text-foreground/80">
                <p>
                  Confidence {Math.round(r.summary.confidence * 100)}% from {r.summary.signalTransactionCount}{" "}
                  open-market buy/sell transaction{r.summary.signalTransactionCount === 1 ? "" : "s"} across{" "}
                  {r.summary.distinctInsiders} distinct insider{r.summary.distinctInsiders === 1 ? "" : "s"} over the
                  last {r.windowDays} days — a couple of trades from one person never carries the confidence a dozen
                  independent ones does.
                </p>
                <p className="text-xs text-muted">
                  {r.summary.buyCount} buy{r.summary.buyCount === 1 ? "" : "s"} ({money(r.summary.buyDollars)}) ·{" "}
                  {r.summary.sellCount} sell{r.summary.sellCount === 1 ? "" : "s"} ({money(r.summary.sellDollars)})
                  {" · "}dollar-weighted net direction {r.summary.netDirection >= 0 ? "+" : ""}
                  {r.summary.netDirection.toFixed(2)}
                </p>
              </div>
            </div>
          )}

          {r.transactions && r.transactions.length > 0 && (
            <Section title={`All Form 4 transactions in the window (${r.transactions.length})`}>
              <ul>
                {r.transactions.map((t, i) => (
                  <InsiderTransactionRow key={`${t.accessionNumber}-${i}`} t={t} />
                ))}
              </ul>
            </Section>
          )}

          <p className="mt-4 text-[11px] text-muted">
            Only open-market purchases (P) and sales (S) feed the direction/confidence above — grants, tax-withholding
            dispositions, option exercises and gifts are shown in the list for transparency but are compensation
            mechanics, not a discretionary buy/sell decision, so they&apos;re excluded from the score.
          </p>
        </>
      )}

      <div className="mt-4 border-t border-hairline pt-3">
        <p className="text-[11px] text-muted">
          <strong>Institutional ownership (13F) trend: not shown.</strong> {r.thirteenF.reason}
        </p>
      </div>

      <p className="mt-3 text-[11px] text-muted">{r.generatedBy}</p>
    </Card>
  );
}

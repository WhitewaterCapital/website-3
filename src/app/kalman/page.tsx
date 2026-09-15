import { ModuleNav } from "@/components/ModuleNav";
import { Card, Badge } from "@/components/ui";
import { kalmanPairs, KALMAN_UNIVERSE } from "@/lib/models/impl/kalman-pairs";
import { getKalmanExport } from "@/lib/kalman";
import type { EquityReading, EquitySignal } from "@/lib/models/types";
import type { KalmanExport, KalmanPairReading } from "@/lib/models/kalman-export";

// Kalman Pairs — an adaptive Kalman-filter pairs-trading / statistical-
// arbitrage screen. Server-renders kalmanPairs.read() directly, same
// pattern smart-money/page.tsx and earnings/page.tsx use, plus a second
// pass over the raw kalman-engine export for the cointegration/adaptive-
// noise detail table the plain EquityReading shape doesn't carry.
export const dynamic = "force-dynamic";

export default async function KalmanPage() {
  const dateISO = new Date().toISOString().slice(0, 10);
  const [reading, raw] = await Promise.all([kalmanPairs.read(dateISO), getKalmanExport()]);

  return (
    <div>
      <ModuleNav crumb="Kalman Pairs" />
      <main className="mx-auto max-w-5xl px-6 py-8">
        <div className="flex items-baseline gap-3">
          <p className="font-mono text-sm text-accent">// Kalman Pairs</p>
          <span className="font-mono text-xs text-muted">adaptive Kalman filter, pairs trading / stat-arb</span>
        </div>
        <h1 className="display mt-2 text-3xl sm:text-4xl">A filter that re-estimates its own noise, as it runs.</h1>
        <p className="mt-3 max-w-2xl text-muted">
          Tests every pair in a fixed {KALMAN_UNIVERSE.length}-name universe ({KALMAN_UNIVERSE.join(", ")}) for real
          cointegration (Engle-Granger two-step), then tracks a time-varying hedge ratio for every genuinely
          cointegrated pair with a Kalman filter whose process- and observation-noise covariances are re-estimated
          online from its own innovations — not fixed by a hand-set hyperparameter. A research read, not investment
          advice.
        </p>
        <SigNote />

        <div className="mt-8">
          <KalmanTable data={reading} />
        </div>

        {raw ? (
          <div className="mt-8">
            <CointegrationDetail raw={raw} />
          </div>
        ) : null}
      </main>
    </div>
  );
}

function SigNote() {
  return (
    <Card>
      <p className="eyebrow">On &quot;Susquehanna-style&quot;</p>
      <p className="mt-2 text-xs leading-relaxed text-muted">
        Susquehanna (SIG) is a private, secretive firm — there is no public documentation of its actual proprietary
        models, and nothing here claims to reproduce one. What is publicly documented is SIG&apos;s stated
        philosophy: probabilistic decision-making under uncertainty, Bayesian updating on incoming data, continuous
        real-time iteration over a static thesis. This model is built in that spirit, using real, standard
        quantitative finance theory — not a SIG replica. See{" "}
        <code className="text-foreground/80">kalman-engine/README.md</code> for the full citation trail.
      </p>
    </Card>
  );
}

function KalmanTable({ data }: { data: EquityReading }) {
  return (
    <div className="space-y-6">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="neutral">Research read</Badge>
          <span className="text-xs text-muted">Pairs / stat-arb signal · not investment advice</span>
        </div>
        <p className="mt-3 text-xs leading-relaxed text-muted">{data.summary}</p>
      </div>

      {data.signals.length === 0 ? (
        <Card>
          <p className="eyebrow">No pairs cointegrated this read</p>
          <p className="mt-2 text-sm text-foreground/80">
            Every candidate pair either lacked enough overlapping history or failed the Engle-Granger cointegration
            test over the available window — see the detail table below for exactly which, and why. This is honest
            abstention, not a fabricated empty screen: a pair with no statistical evidence of a stationary spread
            gets no signal, ever.
          </p>
        </Card>
      ) : (
        <Card title="Cointegrated pairs — ranked by |score|">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="pb-2 font-medium">Pair</th>
                  <th className="pb-2 text-right font-medium">Score</th>
                  <th className="pb-2 font-medium">Reasoning</th>
                </tr>
              </thead>
              <tbody>
                {data.signals.map((s) => (
                  <SignalRow key={s.symbol} s={s} />
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-[11px] text-muted">
            Score is a stated, simple linear scaling of the filter&apos;s own standardized spread z-score (positive =
            long the first ticker / short the second — the filter judges it cheap relative to the pair right now),
            not a fitted or backtested weighting.
          </p>
        </Card>
      )}

      <p className="text-[11px] text-muted">Overall breadth across ranked pairs: {data.breadth > 0 ? "+" : ""}{data.breadth}.</p>
    </div>
  );
}

function SignalRow({ s }: { s: EquitySignal }) {
  return (
    <tr className="border-t border-hairline align-top">
      <td className="py-2 font-medium whitespace-nowrap">{s.symbol}</td>
      <td className="py-2 text-right tabular-nums">
        {s.score > 0 ? "+" : ""}
        {s.score}
      </td>
      <td className="py-2 text-xs text-muted">{s.note}</td>
    </tr>
  );
}

function CointegrationDetail({ raw }: { raw: KalmanExport }) {
  const provenanceTone = raw.provenance === "live" ? "up" : "neutral";
  return (
    <Card title="Every candidate pair, and the adaptive filter's own noise-covariance trail">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={provenanceTone}>{raw.provenance === "live" ? "Live data" : "Synthetic-demo"}</Badge>
        <span className="text-xs text-muted">
          {raw.pairs_cointegrated} of {raw.pairs_tested} pairs cointegrated · as of {raw.as_of}
        </span>
      </div>
      {raw.provenance === "synthetic-demo" ? (
        <p className="mt-2 text-xs text-muted">
          Prices are a locally generated synthetic panel (see <code>kalman-engine/kf/synthetic.py</code>) — the
          cointegration test and Kalman filter math below are real, run over that synthetic input, not fabricated
          output wearing real math&apos;s label.
        </p>
      ) : null}
      <div className="mt-4 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-left text-muted">
              <th className="pb-2 pr-4 font-medium">Pair</th>
              <th className="pb-2 pr-4 font-medium">Cointegrated?</th>
              <th className="pb-2 pr-4 font-medium">ADF t-stat vs. 5% crit.</th>
              <th className="pb-2 pr-4 font-medium">Hedge ratio (γ)</th>
              <th className="pb-2 pr-4 font-medium">z-score</th>
              <th className="pb-2 pr-4 font-medium">Q trace: init → now</th>
              <th className="pb-2 font-medium">R: init → now</th>
            </tr>
          </thead>
          <tbody>
            {raw.pairs.map((p) => (
              <DetailRow key={p.pair} p={p} />
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] text-muted">
        &quot;Q trace: init → now&quot; and &quot;R: init → now&quot; are the concrete evidence that this filter
        genuinely re-estimates its own process- and observation-noise covariances online, from its own innovations,
        as it runs — the initial value is only the hand-set t=0 starting guess (<code>kalman-engine/kf/config.py</code>
        ); every value after that comes from the filter&apos;s own adaptive update (Mehra/Akhlaghi-style covariance
        matching — see <code>kalman-engine/kf/filter.py</code> for the exact equations and citations).
      </p>
    </Card>
  );
}

function DetailRow({ p }: { p: KalmanPairReading }) {
  const adf = p.cointegration;
  const kf = p.kalman;
  return (
    <tr className="border-t border-hairline">
      <td className="py-1.5 pr-4 font-medium whitespace-nowrap">{p.pair}</td>
      <td className="py-1.5 pr-4">
        {p.available ? (
          <Badge tone={p.cointegrated ? "up" : "neutral"}>{p.cointegrated ? "yes" : "no"}</Badge>
        ) : (
          <Badge tone="neutral">n/a</Badge>
        )}
      </td>
      <td className="py-1.5 pr-4 tabular-nums text-muted">
        {adf && adf.adf_t_stat !== null ? `${adf.adf_t_stat.toFixed(2)} vs ${adf.critical_value_5pct.toFixed(2)}` : "—"}
      </td>
      <td className="py-1.5 pr-4 tabular-nums text-muted">{kf ? kf.gamma.toFixed(3) : "—"}</td>
      <td className="py-1.5 pr-4 tabular-nums text-muted">{kf ? kf.z_score.toFixed(2) : "—"}</td>
      <td className="py-1.5 pr-4 tabular-nums text-muted">
        {kf ? `${kf.adaptive_noise.initial_q_trace.toExponential(1)} → ${kf.adaptive_noise.final_q_trace.toExponential(1)}` : "—"}
      </td>
      <td className="py-1.5 tabular-nums text-muted">
        {kf ? `${kf.adaptive_noise.initial_r.toExponential(1)} → ${kf.adaptive_noise.final_r.toExponential(1)}` : "—"}
      </td>
    </tr>
  );
}

import type { EquityModel, EquityReading, EquitySignal } from "../types";
import { getKalmanExport } from "@/lib/kalman";
import type { KalmanPairReading } from "../kalman-export";

// ═══════════════════════════════════════════════════════════════════════════
// Kalman Pairs — an EquityModel. Built 2026-09-14 in direct response to
// "build a kalman filter for equities which learns from itself ... look at
// what susquehanna builds and do smth similar or as good as possible."
//
// ON SUSQUEHANNA: SIG is a private, secretive firm — there is no public
// documentation of its actual proprietary models, and nothing here claims
// to replicate one. What IS public (checked via WebSearch/WebFetch — see
// kalman-engine/README.md for sources) is SIG's stated philosophy:
// probabilistic decision-making under uncertainty (poker/game-theory
// roots), Bayesian updating on incoming data, continuous real-time
// iteration over a static thesis. This model is built in THAT SPIRIT using
// real, standard quantitative finance theory (Engle-Granger cointegration;
// a Kalman filter tracking a time-varying hedge ratio; Mehra/Akhlaghi-style
// ONLINE adaptive noise-covariance re-estimation) — not a SIG replica.
//
// WHAT "LEARNS FROM ITSELF" ACTUALLY MEANS HERE: the Kalman filter's own
// process- and observation-noise covariances (Q, R) are re-estimated
// online, every time step, from the filter's own innovation sequence —
// not fixed by a hand-picked hyperparameter. See kalman-engine/kf/
// filter.py's module docstring for the exact cited method (Mehra 1970;
// Akhlaghi, Zhou & Huang 2017, arXiv:1702.00884) and
// kalman-engine/README.md for what this deliberately does NOT implement
// (EM-based batch noise-covariance learning — a real, different,
// considered-but-not-built complementary method from the same literature).
//
// WHY "TICKER1/TICKER2" SYMBOLS, NOT SINGLE-NAME: this is a cross-sectional
// PAIRS screen, not a single-name read — `symbol` is the pair notation
// (e.g. "AAPL/MSFT"), and `score` is a signed read of the STANDARDIZED
// SPREAD between the two names (positive = long ticker1/short ticker2 read
// — the filter judges ticker1 cheap relative to ticker2 right now),
// derived from the filter's own z-score by a stated, NOT backtested linear
// scale (kalman-engine/kf/config.py::Z_TO_SCORE_SCALE) — same "stated
// simple scaling" discipline as smart-money-momentum.ts / earnings-move.ts.
//
// HONESTY / ABSTENTION: a pair appears in `signals` ONLY when
// kalman-engine's own Engle-Granger test found it genuinely cointegrated
// over the available history (see kalman-engine/kf/cointegration.py) —
// every OTHER candidate pair in the fixed 6-name universe is real
// evidence too (a real, tested "no" answer), so it is surfaced in
// `abstained` with the engine's own stated reason (the ADF t-stat vs. the
// MacKinnon critical value it was measured against), never silently
// dropped and never forced into a spread signal it has no statistical
// basis for. If kalman-engine hasn't exported yet, every pair reads as
// unavailable — the honest "not synced" state every *-export.ts reader in
// this repo already uses, not a fabricated empty screen.
// ═══════════════════════════════════════════════════════════════════════════

// The same fixed 6-name universe WW-Factor / Smart Money Momentum /
// Earnings Move / kalman-engine's own kf/config.py all already target.
export const KALMAN_UNIVERSE = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO"] as const;

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}

function noteFor(p: KalmanPairReading): string {
  if (p.note) return p.note;
  return p.cointegrated ? "Cointegrated — see kalman-engine export for detail." : "Not cointegrated this run.";
}

export const kalmanPairs: EquityModel = {
  meta: {
    id: "kalman-pairs",
    name: "Kalman Pairs",
    kind: "equity",
    status: "live",
    tagline: "Adaptive Kalman-filter pairs trading — a self-tuning statistical-arbitrage read over a fixed 6-name universe.",
    description:
      "Tests every pair in a fixed 6-name universe (AAPL, MSFT, NVDA, JPM, XOM, KO) for real cointegration " +
      "(Engle-Granger two-step, implemented from scratch), and for every genuinely cointegrated pair runs an " +
      "adaptive Kalman filter that tracks a time-varying hedge ratio between the two names' log prices. The " +
      "filter's own process- and observation-noise covariances are re-estimated ONLINE from its own innovations " +
      "as new data arrives (Mehra/Akhlaghi-style covariance matching) rather than fixed by a hand-set " +
      "hyperparameter — the specific mechanism behind 'learns from itself'. Built in the spirit of Susquehanna's " +
      "publicly stated probabilistic, Bayesian-updating philosophy — not a claim to replicate any real SIG " +
      "system, which is private. A pair not found cointegrated is honestly excluded, never forced into a signal. " +
      "Research read, not investment advice — never fed into any single-name composite conviction score.",
  },

  async read(dateISO: string): Promise<EquityReading> {
    const data = await getKalmanExport();

    if (!data) {
      return {
        date: dateISO,
        breadth: 0,
        signals: [],
        summary:
          "kalman-engine hasn't exported yet (no public/data/kalman/latest.json) — run `python -m kf.export` " +
          "in kalman-engine/. Nothing fabricated in its place.",
        generatedBy: "Kalman Pairs",
      };
    }

    const signals: EquitySignal[] = [];
    const abstained: string[] = [];

    for (const p of data.pairs) {
      if (!p.available) {
        abstained.push(`${p.pair}: ${noteFor(p)}`);
        continue;
      }
      if (!p.cointegrated || p.score === null || !p.kalman) {
        abstained.push(`${p.pair}: ${noteFor(p)}`);
        continue;
      }
      const score = Math.round(clamp(p.score, -100, 100));
      signals.push({
        symbol: p.pair,
        score,
        note: noteFor(p),
      });
    }

    signals.sort((a, b) => Math.abs(b.score) - Math.abs(a.score));

    const breadth = signals.length > 0 ? Math.round(signals.reduce((s, x) => s + x.score, 0) / signals.length) : 0;

    const provenanceLine =
      data.provenance === "synthetic-demo"
        ? "This read is SYNTHETIC-DEMO: prices come from a locally generated synthetic panel (kalman-engine/kf/synthetic.py), " +
          "not a live market feed — the cointegration test and Kalman filter math themselves are real, run over synthetic input."
        : "This read is LIVE: prices come from Alpaca's real daily-bar feed (IEX).";

    const coverageLine = `${data.pairs_cointegrated} of ${data.pairs_tested} candidate pairs tested cointegrated this run and are ranked below.`;
    const abstainLine = abstained.length > 0 ? ` Not ranked (tested, not cointegrated, or insufficient data): ${abstained.join("; ")}.` : "";

    const summary =
      `Adaptive Kalman-filter pairs screen over the fixed ${KALMAN_UNIVERSE.length}-name universe ` +
      `(${KALMAN_UNIVERSE.join(", ")}), as of ${data.as_of}. ${provenanceLine} ${coverageLine}${abstainLine} ` +
      `Descriptive/research screen — not fed into any single-name composite conviction score.`;

    return {
      date: dateISO,
      breadth,
      signals,
      summary,
      generatedBy: "Kalman Pairs",
    };
  },
};

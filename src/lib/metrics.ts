import type { Snapshot } from "./types";

// ---------------------------------------------------------------------------
// Performance & risk metrics, all derived from the snapshot history.
// These are the numbers on both the public track-record page and the
// members dashboard.
// ---------------------------------------------------------------------------

// Rebase a series to start at 100 so the portfolio and SPY are comparable
// regardless of absolute size. Good for the "us vs SPY" chart.
export function indexed(values: number[]): number[] {
  if (!values.length) return [];
  const base = values[0];
  return values.map((v) => (base ? (v / base) * 100 : 100));
}

// Total return over the whole window, as a fraction (0.12 = +12%).
export function totalReturn(values: number[]): number {
  if (values.length < 2) return 0;
  return values[values.length - 1] / values[0] - 1;
}

// Max drawdown: worst peak-to-trough drop, as a positive fraction.
export function maxDrawdown(values: number[]): number {
  let peak = -Infinity;
  let worst = 0;
  for (const v of values) {
    if (v > peak) peak = v;
    if (peak > 0) worst = Math.min(worst, v / peak - 1);
  }
  return Math.abs(worst);
}

// Annualized volatility from periodic returns. `periodsPerYear` = 52 for weekly.
export function volatility(values: number[], periodsPerYear = 52): number {
  const rets: number[] = [];
  for (let i = 1; i < values.length; i++) {
    rets.push(values[i] / values[i - 1] - 1);
  }
  if (rets.length < 2) return 0;
  const mean = rets.reduce((s, r) => s + r, 0) / rets.length;
  const variance =
    rets.reduce((s, r) => s + (r - mean) ** 2, 0) / (rets.length - 1);
  return Math.sqrt(variance) * Math.sqrt(periodsPerYear);
}

// Sharpe ratio (excess return over risk-free, per unit of volatility).
export function sharpe(
  values: number[],
  riskFreeAnnual = 0.04,
  periodsPerYear = 52,
): number {
  const rets: number[] = [];
  for (let i = 1; i < values.length; i++) {
    rets.push(values[i] / values[i - 1] - 1);
  }
  if (rets.length < 2) return 0;
  const mean = rets.reduce((s, r) => s + r, 0) / rets.length;
  const annReturn = mean * periodsPerYear;
  const vol = volatility(values, periodsPerYear);
  return vol > 0 ? (annReturn - riskFreeAnnual) / vol : 0;
}

// Current invested-vs-cash split, for the exposure gauge.
export function exposure(latest: Snapshot): {
  investedPct: number;
  cashPct: number;
} {
  const total = latest.totalValueUsd || 1;
  const investedPct = (latest.investedUsd / total) * 100;
  return { investedPct, cashPct: 100 - investedPct };
}

// One bundle of everything the dashboards need, computed once.
export function computeMetrics(snapshots: Snapshot[]) {
  // Performance is measured on UNIT VALUE, not raw account value — otherwise
  // deposits would look like gains. Exposure still uses the latest account totals.
  const values = snapshots.map((s) => s.unitValueUsd);
  const spy = snapshots.map((s) => s.spyPrice);
  const latest = snapshots[snapshots.length - 1];

  const portReturn = totalReturn(values);
  const spyReturn = totalReturn(spy);

  return {
    latest,
    portReturn,
    spyReturn,
    alpha: portReturn - spyReturn, // simple excess vs benchmark
    maxDrawdown: maxDrawdown(values),
    volatility: volatility(values),
    sharpe: sharpe(values),
    exposure: exposure(latest),
    portIndexed: indexed(values),
    spyIndexed: indexed(spy),
  };
}

export type Metrics = ReturnType<typeof computeMetrics>;

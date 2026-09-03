"""Validation metrics: rank IC, decile spread, hit rate, turnover, deflated Sharpe.

`rank_ic`, `hit_rate`, `probabilistic_sharpe_ratio` and `deflated_sharpe_ratio`
are VENDORED (re-typed, not imported) from `engine/incepta/validation/metrics.py`
— same reasoning as validation/splits.py's vendoring note: this engine is
sealed, so the well-tested formula is duplicated here with its own docstring
and its own tests (tests/test_metrics.py), rather than reached into engine/
at runtime. `decile_spread` and `turnover` are new — the incepta metrics
module doesn't need them (its scoring is continuous composite scores, not a
published decile bucket), but the spec here explicitly asks for both since
WW-WEEKLY's output is a ranked cross section.

Deflated Sharpe Ratio uses only stdlib `statistics.NormalDist` (no scipy
dependency), same as the incepta original.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

_N = NormalDist()
_EULER = 0.5772156649015329


def _clean_pair(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    m = ~(np.isnan(a) | np.isnan(b))
    return a[m], b[m]


def rank_ic(pred, actual) -> float:
    """Spearman rank IC = Pearson correlation on the ranks. The primary
    metric for this engine: robust to outliers, and the ordering — not the
    raw predicted level — is the actual output (spec: "The ordering is the
    output, not the number")."""
    a, b = _clean_pair(pred, actual)
    if a.size < 3:
        return float("nan")
    ra = np.argsort(np.argsort(a))
    rb = np.argsort(np.argsort(b))
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def hit_rate(pred, actual) -> float:
    """Fraction where the sign of the (demeaned) prediction matches the
    (demeaned) outcome — a coarser, more interpretable cousin of rank IC."""
    a, b = _clean_pair(pred, actual)
    if a.size == 0:
        return float("nan")
    a = a - np.mean(a)
    b = b - np.mean(b)
    return float(np.mean(np.sign(a) == np.sign(b)))


def decile_spread(pred, actual, n_deciles: int = 10) -> float:
    """Mean actual return of the top decile of `pred` minus the mean actual
    return of the bottom decile — the classic long-top/short-bottom spread a
    ranked cross-sectional signal is actually meant to be judged on (rank IC
    is the summary statistic; decile spread is closer to "would a simple
    long/short book built on this ranking have made money").

    Requires at least `n_deciles` valid, non-degenerate observations; returns
    NaN otherwise rather than a spread computed on a meaningless bucket size.
    """
    a, b = _clean_pair(pred, actual)
    if a.size < n_deciles or np.std(a) == 0:
        return float("nan")
    ranks = pd.Series(a).rank(method="first")
    buckets = pd.qcut(ranks, n_deciles, labels=False, duplicates="drop")
    n_buckets = int(np.nanmax(buckets)) + 1
    if n_buckets < 2:
        return float("nan")
    top = b[buckets == n_buckets - 1]
    bottom = b[buckets == 0]
    if top.size == 0 or bottom.size == 0:
        return float("nan")
    return float(top.mean() - bottom.mean())


def turnover(prev_ranks: pd.Series, curr_ranks: pd.Series) -> float:
    """Rank-based turnover between two consecutive periods' cross-sectional
    rankings of the SAME universe: mean absolute change in percentile rank
    (0..1 scale) across names present in both periods. 0 = identical
    ordering; larger values mean the ranking is churning, which matters
    because churn is what a real book would pay transaction costs on — a
    signal with a great rank IC but a new top/bottom decile every single
    week is a much weaker candidate than one whose ranking is comparatively
    sticky, cost-wise, even before backtest costs are modeled explicitly.

    `prev_ranks`/`curr_ranks` are pandas Series indexed by ticker, already
    expressed as percentile ranks (0..1) — see harness.py for how they are
    built from raw predictions. Only tickers present in BOTH periods count;
    returns NaN if there are none (e.g. the very first period).
    """
    common = prev_ranks.index.intersection(curr_ranks.index)
    if len(common) == 0:
        return float("nan")
    return float((curr_ranks.loc[common] - prev_ranks.loc[common]).abs().mean())


def probabilistic_sharpe_ratio(
    sr: float, n_obs: int, sr_benchmark: float = 0.0, skew: float = 0.0, kurt: float = 3.0
) -> float:
    """P(true SR > benchmark) given estimation error, skew and kurtosis.
    `sr` is the PER-OBSERVATION Sharpe (not annualized)."""
    if n_obs < 2:
        return float("nan")
    denom = math.sqrt(1 - skew * sr + (kurt - 1) / 4.0 * sr ** 2)
    if denom == 0:
        return float("nan")
    z = (sr - sr_benchmark) * math.sqrt(n_obs - 1) / denom
    return float(_N.cdf(z))


def deflated_sharpe_ratio(
    sr: float,
    n_obs: int,
    n_trials: int,
    sr_variance_across_trials: float,
    skew: float = 0.0,
    kurt: float = 3.0,
) -> float:
    """Bailey & López de Prado (2014). Deflates the observed (per-observation)
    Sharpe by the expected MAX Sharpe achievable from `n_trials` independent
    random trials, then returns the probability the strategy is genuinely
    better than that. A DSR below ~0.95 is not distinguishable from luck
    given how many things were tried."""
    if n_trials <= 1 or sr_variance_across_trials <= 0:
        return probabilistic_sharpe_ratio(sr, n_obs, 0.0, skew, kurt)
    sigma = math.sqrt(sr_variance_across_trials)
    e_max = (1 - _EULER) * _N.inv_cdf(1 - 1.0 / n_trials) + _EULER * _N.inv_cdf(
        1 - 1.0 / (n_trials * math.e)
    )
    sr_star = sigma * e_max
    return probabilistic_sharpe_ratio(sr, n_obs, sr_star, skew, kurt)


def sharpe_of_returns(returns, periods_per_year: int = 52) -> float:
    """Annualized Sharpe of a return series (default: weekly periods/year=52)."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2 or np.std(r, ddof=1) == 0:
        return float("nan")
    return float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(periods_per_year))

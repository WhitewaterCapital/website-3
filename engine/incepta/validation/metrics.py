"""Evaluation metrics. The dossier forbids judging the model on cumulative
backtest return alone — so this module leads with signal quality (IC), honest
probability metrics (Brier), and the **Deflated Sharpe Ratio**, which penalises a
Sharpe for the number of trials, sample length, skew and kurtosis.

Uses only the stdlib `statistics.NormalDist` for Φ/Φ⁻¹ (no scipy dependency).
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np

_N = NormalDist()
_EULER = 0.5772156649015329


def _clean_pair(a, b):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    m = ~(np.isnan(a) | np.isnan(b))
    return a[m], b[m]


def information_coefficient(pred, actual) -> float:
    """Pearson correlation between predictions and realized outcomes."""
    a, b = _clean_pair(pred, actual)
    if a.size < 3 or np.std(a) == 0 or np.std(b) == 0:
        return float("nan")
    return float(np.corrcoef(a, b)[0, 1])


def rank_ic(pred, actual) -> float:
    """Spearman rank IC = Pearson on the ranks. Robust to outliers; the primary
    metric for cross-sectional ranking."""
    a, b = _clean_pair(pred, actual)
    if a.size < 3:
        return float("nan")
    ra = np.argsort(np.argsort(a))
    rb = np.argsort(np.argsort(b))
    if np.std(ra) == 0 or np.std(rb) == 0:
        return float("nan")
    return float(np.corrcoef(ra, rb)[0, 1])


def hit_rate(pred, actual) -> float:
    """Fraction where the sign of the (demeaned) prediction matches the outcome."""
    a, b = _clean_pair(pred, actual)
    if a.size == 0:
        return float("nan")
    a = a - np.mean(a)
    b = b - np.mean(b)
    return float(np.mean(np.sign(a) == np.sign(b)))


def brier_score(probs, outcomes) -> float:
    """Mean squared error of probabilistic forecasts (lower better)."""
    p, o = _clean_pair(probs, outcomes)
    if p.size == 0:
        return float("nan")
    return float(np.mean((p - o) ** 2))


def sharpe(returns, periods_per_year: int = 252) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2 or np.std(r, ddof=1) == 0:
        return float("nan")
    return float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(periods_per_year))


def sortino(returns, periods_per_year: int = 252) -> float:
    """Sortino ratio: mean return / downside deviation. Downside deviation is the
    TARGET semi-deviation (target 0) with denominator = total N (standard)."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2:
        return float("nan")
    downside = np.minimum(r, 0.0)                     # target semi-deviation
    dd = math.sqrt(float(np.mean(downside ** 2)))     # divide by TOTAL n
    if dd == 0:
        return float("nan")
    return float(np.mean(r) / dd * math.sqrt(periods_per_year))


def max_drawdown(returns) -> float:
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size == 0:
        return float("nan")
    equity = np.cumprod(1 + r)
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1.0).min())


def probabilistic_sharpe_ratio(
    sr: float, n_obs: int, sr_benchmark: float = 0.0, skew: float = 0.0, kurt: float = 3.0
) -> float:
    """P(true SR > benchmark) given estimation error, skew and kurtosis.
    `sr` is the per-observation Sharpe (NOT annualized)."""
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
    Sharpe by the EXPECTED MAX Sharpe achievable from `n_trials` independent
    random trials, then returns the probability the strategy is genuinely > that.
    A DSR below ~0.95 means the result is not distinguishable from luck given how
    many things were tried.
    """
    if n_trials <= 1 or sr_variance_across_trials <= 0:
        # 1 trial (or unknown cross-trial variance) → nothing to deflate; the
        # expected-max term is undefined (inv_cdf(1 - 1/1) = inv_cdf(0)), so fall
        # back to the plain PSR vs 0.
        return probabilistic_sharpe_ratio(sr, n_obs, 0.0, skew, kurt)
    sigma = math.sqrt(sr_variance_across_trials)
    # expected maximum of N iid standard-normal SRs (Gumbel approximation)
    e_max = (1 - _EULER) * _N.inv_cdf(1 - 1.0 / n_trials) + _EULER * _N.inv_cdf(
        1 - 1.0 / (n_trials * math.e)
    )
    sr_star = sigma * e_max
    return probabilistic_sharpe_ratio(sr, n_obs, sr_star, skew, kurt)


# --- tail risk (coherent) ----------------------------------------------------
def historical_var(returns, alpha: float = 0.95) -> float:
    """Historical Value-at-Risk: the loss NOT exceeded with probability `alpha`
    over one period, as a POSITIVE number. VaR_0.95 = 0.03 → "5% of periods lose
    more than 3%." Non-parametric (uses the empirical distribution)."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2:
        return float("nan")
    return float(-np.quantile(r, 1.0 - alpha))


def expected_shortfall(returns, alpha: float = 0.95) -> float:
    """Expected Shortfall / CVaR: the AVERAGE loss in the worst (1-alpha) tail, as
    a positive number. Coherent risk measure (Artzner et al. 1999) — unlike VaR it
    accounts for how bad the tail is, not just where it starts. ES >= VaR always."""
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2:
        return float("nan")
    threshold = np.quantile(r, 1.0 - alpha)
    tail = r[r <= threshold]
    if tail.size == 0:
        return float("nan")
    return float(-tail.mean())

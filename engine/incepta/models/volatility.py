"""Volatility estimators. Volatility is the most forecastable quantity in the
system (dossier §6) and it powers sizing and stress — so it is built first and
kept simple/transparent (EWMA now; GJR-GARCH is a later slice).
"""

from __future__ import annotations

import numpy as np

TRADING_DAYS = 252
RISKMETRICS_LAMBDA = 0.94  # daily EWMA decay (RiskMetrics)


def ewma_vol(returns: np.ndarray, lam: float = RISKMETRICS_LAMBDA, annualize: bool = True) -> float:
    """Exponentially-weighted volatility. Recursive form:
    sigma2_t = lam*sigma2_{t-1} + (1-lam)*r_{t-1}^2. Seeded with sample variance.
    """
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    if r.size < 2:
        return float("nan")
    var = float(np.var(r, ddof=1))  # seed
    for x in r:
        var = lam * var + (1.0 - lam) * x * x
    vol = float(np.sqrt(var))
    return vol * np.sqrt(TRADING_DAYS) if annualize else vol

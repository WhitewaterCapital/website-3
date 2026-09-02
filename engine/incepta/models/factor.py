"""Factor-exposure estimation via regression on Fama-French 5 + Momentum returns.

Decomposes a stock's excess return into systematic (factor) and idiosyncratic
parts (dossier §6/§9). Uses ordinary least squares by default, with an optional
ridge penalty (shrinkage) which stabilises betas when factors are collinear or
the window is short.

    r_i - r_f = alpha + sum_k beta_k * F_k + epsilon
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADING_DAYS = 252
DEFAULT_FACTORS = ["mkt_rf", "smb", "hml", "rmw", "cma", "mom"]


@dataclass
class FactorFit:
    alpha_annual: float
    betas: dict
    r2: float
    idio_vol_annual: float
    n_obs: int
    factors: list = field(default_factory=list)


def _ridge_beta(X: np.ndarray, y: np.ndarray, lam: float) -> np.ndarray:
    """Closed-form (ridge) least squares. Intercept (column 0) is NOT penalised."""
    p = X.shape[1]
    penalty = lam * np.eye(p)
    penalty[0, 0] = 0.0
    return np.linalg.solve(X.T @ X + penalty, X.T @ y)


def blume_adjust_beta(raw_beta: float, w: float = 2.0 / 3.0) -> float:
    """Blume (1971) market-beta shrinkage toward 1.0. A single-window raw beta is
    noisy and betas mean-revert toward the market over time, so a shrunk beta
    predicts the *future* beta better. Apply to the MARKET beta only (not the
    style factors). adj = w*raw + (1-w)*1.0; classic w≈2/3."""
    return w * raw_beta + (1.0 - w) * 1.0


def factor_exposures(
    stock_returns: pd.Series,
    factors: pd.DataFrame,
    window: int = TRADING_DAYS,
    ridge_lambda: float = 0.0,
    factor_cols: list = None,
) -> FactorFit:
    """`stock_returns` = daily simple returns indexed by date. `factors` includes
    an `rf` column plus the factor columns. Returns a FactorFit using the most
    recent `window` overlapping days.
    """
    factor_cols = factor_cols or DEFAULT_FACTORS
    df = pd.DataFrame({"r": stock_returns}).join(factors, how="inner").dropna()
    if window:
        df = df.iloc[-window:]
    n = len(df)
    if n < len(factor_cols) + 2:
        return FactorFit(float("nan"), {}, float("nan"), float("nan"), n, factor_cols)

    y = np.ascontiguousarray((df["r"] - df["rf"]).to_numpy(), dtype=np.float64)
    F = np.ascontiguousarray(df[factor_cols].to_numpy(), dtype=np.float64)
    X = np.ascontiguousarray(np.column_stack([np.ones(n), F]), dtype=np.float64)

    beta = _ridge_beta(X, y, ridge_lambda)
    if not np.all(np.isfinite(beta)):
        return FactorFit(float("nan"), {}, float("nan"), float("nan"), n, factor_cols)
    # np.errstate guards a benign FP warning some macOS BLAS builds emit here;
    # inputs are verified finite above, so results are unaffected.
    with np.errstate(over="ignore", divide="ignore", invalid="ignore"):
        resid = y - X @ beta
    ss_res = float(resid @ resid)
    ss_tot = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    idio_daily = float(np.std(resid, ddof=X.shape[1]))

    return FactorFit(
        alpha_annual=float(beta[0] * TRADING_DAYS),
        betas={c: float(b) for c, b in zip(factor_cols, beta[1:])},
        r2=r2,
        idio_vol_annual=idio_daily * np.sqrt(TRADING_DAYS),
        n_obs=n,
        factors=factor_cols,
    )

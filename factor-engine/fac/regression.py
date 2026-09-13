"""Closed-form OLS factor-exposure regression, plus the honesty gate.

This is WW-FACTOR's version of the "done when" gate every sealed engine in
this repo carries (see `graph-engine/ge/reversion.py`'s Dickey-Fuller gate,
which this module's structure deliberately mirrors): a beta is reported ONLY
when there is enough overlapping history to trust it and the regression
design matrix is not numerically degenerate. Otherwise the model abstains —
`FactorFit.betas` is `None` and `FactorFit.confidence`/`.abstain_reason`
explain why — rather than publish a number the arithmetic could not actually
pin down.

Why plain numpy instead of statsmodels/sklearn (same reasoning as
`ge/reversion.py`'s hand-rolled OU fit): the model here is one closed-form
expression,

    beta_hat = (X'X)^-1 X'y

with y = ticker's excess return (return - RF) and X = [1, factor_1, ...,
factor_6] (the leading column of ones fits the intercept/alpha). There is no
need for a heavy statistics dependency that might not even be installed to
compute six numbers and their standard errors — the full derivation,
including the standard-error and t-statistic formulas, is standard
introductory-econometrics material (e.g. Greene, *Econometric Analysis*,
ordinary least squares chapter) and is reproduced inline below rather than
imported from anywhere.

`sigma^2_hat = RSS / (n - k)` (k = number of parameters, including the
intercept) is the usual unbiased variance estimator; `Var(beta_hat) =
sigma^2_hat * (X'X)^-1`; `se(beta_hat_j) = sqrt(Var(beta_hat)_jj)`;
`t_j = beta_hat_j / se(beta_hat_j)`. `R^2 = 1 - RSS/TSS` where TSS is the
total sum of squares of y around its own mean.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .config import BETA_T_CRIT, MAX_CONDITION_NUMBER, MIN_OBS


@dataclass(frozen=True)
class FactorBeta:
    factor: str
    beta: float
    se: float
    t_stat: float
    significant: bool  # |t_stat| >= BETA_T_CRIT — an honest annotation, NOT a per-factor abstain gate (see module docstring)


@dataclass(frozen=True)
class FactorFit:
    """Result of one trailing-window factor regression for one ticker.

    `betas` (and `alpha`/`r2`/etc.) are `None` whenever `confidence !=
    "ok"` — the whole point of this dataclass is that a caller can never
    accidentally read a beta off an abstained fit, because there isn't one
    to read.
    """

    n_obs: int
    confidence: str  # "ok" | "insufficient_history" | "degenerate"
    abstain_reason: str | None = None
    alpha: float | None = None  # daily, NOT annualized — see export.py for the annualized figure shown on the site
    alpha_annualized: float | None = None
    r2: float | None = None
    condition_number: float | None = None
    betas: list[FactorBeta] | None = field(default=None)

    def beta_of(self, factor: str) -> FactorBeta | None:
        if not self.betas:
            return None
        return next((b for b in self.betas if b.factor == factor), None)


def _abstain(n_obs: int, confidence: str, reason: str, condition_number: float | None = None) -> FactorFit:
    return FactorFit(
        n_obs=n_obs,
        confidence=confidence,
        abstain_reason=reason,
        condition_number=condition_number,
    )


def fit_ols(y: np.ndarray, X: np.ndarray) -> tuple[np.ndarray, np.ndarray, float, float]:
    """The closed-form OLS primitive, with no gating and no domain knowledge
    of what X's columns mean — a pure numeric building block, tested in
    isolation (`tests/test_regression.py`) against a known-answer case
    (regressing a variable against itself must give beta=1, R^2=1).

    `X` must already include a leading column of ones for the intercept if
    one is wanted; this function does not add one itself.

    Returns `(beta_hat, se, r2, condition_number)` where `beta_hat`/`se` are
    length-k arrays (k = X.shape[1]) and `condition_number` is
    `np.linalg.cond(X.T @ X)` — the caller (`fit_factor_exposure`) is
    responsible for checking it before trusting `beta_hat`/`se`; this
    function computes it but does not itself refuse to run on a degenerate
    matrix, so it stays a pure, always-succeeds-or-raises-on-shape numeric
    primitive independent of this engine's own honesty policy.
    """
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    n, k = X.shape
    if y.shape[0] != n:
        raise ValueError(f"y has {y.shape[0]} rows, X has {n}")
    if n <= k:
        raise ValueError(f"need more observations ({n}) than parameters ({k}) to fit OLS")

    xtx = X.T @ X
    condition_number = float(np.linalg.cond(xtx))
    xtx_inv = np.linalg.pinv(xtx)  # pinv, not inv: never raises on a singular matrix — the condition-number gate is what refuses it
    beta_hat = xtx_inv @ X.T @ y

    resid = y - X @ beta_hat
    rss = float(resid @ resid)
    dof = max(n - k, 1)
    sigma2 = rss / dof
    var_beta = sigma2 * np.diag(xtx_inv)
    se = np.sqrt(np.clip(var_beta, 0.0, None))  # clip: guards a tiny negative from floating-point noise on a near-singular xtx_inv

    y_mean = y.mean()
    tss = float(np.sum((y - y_mean) ** 2))
    r2 = float(1.0 - rss / tss) if tss > 0 else 0.0

    return beta_hat, se, r2, condition_number


def fit_factor_exposure(
    ticker_returns: pd.Series,
    factor_panel: pd.DataFrame,
    factor_columns: list[str],
    rf_column: str,
    *,
    window: int,
    min_obs: int = MIN_OBS,
    t_crit: float = BETA_T_CRIT,
    max_condition_number: float = MAX_CONDITION_NUMBER,
) -> FactorFit:
    """The one honesty-gated entry point either export path (`export.py`)
    calls — same discipline as `ge.reversion.fit_ou` / `ge/export.py`'s
    `_residuals_for_universe`: identical gate applied whether the inputs
    came from real Tiingo/French data or the synthetic-demo generator.

    Steps:
      1. Align `ticker_returns` and `factor_panel` on date (inner join) —
         a date missing from either side is dropped, never filled.
      2. Take the trailing `window` observations of that aligned history
         (or fewer, if less than `window` overlapping dates exist at all).
      3. Gate on sample size: fewer than `min_obs` aligned observations ->
         abstain with confidence "insufficient_history".
      4. Build y = ticker_return - RF (excess return) and
         X = [1, factor_1, ..., factor_k].
      5. Gate on numerical degeneracy: `np.linalg.cond(X'X) >
         max_condition_number`, or `y` has zero variance (e.g. a halted or
         perfectly flat ticker over the window) -> abstain with confidence
         "degenerate".
      6. Otherwise fit and return confidence "ok" with every beta, its
         standard error, t-stat, and a `significant` flag at `t_crit`
         (reported alongside the beta, never used to hide it — see
         regression.py's module docstring for why).
    """
    aligned = factor_panel.join(ticker_returns.rename("_ticker"), how="inner")
    aligned = aligned.dropna(subset=[rf_column, "_ticker", *factor_columns])
    aligned = aligned.sort_index()
    windowed = aligned.iloc[-window:] if len(aligned) > window else aligned

    n_obs = len(windowed)
    if n_obs < min_obs:
        return _abstain(
            n_obs,
            "insufficient_history",
            f"Only {n_obs} overlapping (price, factor) trading days available "
            f"(need >= {min_obs}) — the ticker may be recently listed, thinly "
            f"covered by Tiingo, or missing recent French factor data.",
        )

    y = (windowed["_ticker"] - windowed[rf_column]).to_numpy(dtype=float)
    X_factors = windowed[factor_columns].to_numpy(dtype=float)
    X = np.column_stack([np.ones(n_obs), X_factors])

    if np.nanstd(y) == 0.0:
        return _abstain(
            n_obs,
            "degenerate",
            "The ticker's excess return has zero variance over this window "
            "(e.g. a halted or perfectly flat security) — a beta cannot be "
            "identified against a constant.",
        )

    beta_hat, se, r2, condition_number = fit_ols(y, X)

    if not np.isfinite(condition_number) or condition_number > max_condition_number:
        return _abstain(
            n_obs,
            "degenerate",
            f"Regression design matrix is numerically degenerate over this window "
            f"(condition number {condition_number:.3g} > {max_condition_number:.0e}) — "
            f"likely two factors are collinear or one is constant over this specific "
            f"window; refusing to publish a beta the arithmetic could not reliably pin down.",
            condition_number=condition_number,
        )

    alpha = float(beta_hat[0])
    betas = []
    for i, name in enumerate(factor_columns, start=1):
        b = float(beta_hat[i])
        s = float(se[i])
        t = b / s if s > 0 else 0.0
        betas.append(FactorBeta(factor=name, beta=b, se=s, t_stat=t, significant=bool(abs(t) >= t_crit)))

    return FactorFit(
        n_obs=n_obs,
        confidence="ok",
        alpha=alpha,
        alpha_annualized=float((1.0 + alpha) ** 252 - 1.0),
        r2=r2,
        condition_number=condition_number,
        betas=betas,
    )

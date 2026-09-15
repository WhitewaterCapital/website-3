"""Engle-Granger two-step cointegration test — real math, no canned library
call, because `statsmodels` is not importable in any sandbox this engine has
been built in (confirmed this pass: `python3 -c "import statsmodels"` raises
`ModuleNotFoundError` — see README.md for the exact command and output).
This module reimplements, by hand, exactly the two steps the task requires:

  Step 1 (OLS): regress y1_t on a constant and y2_t, obtaining a hedge ratio
    (the OLS slope) and a residual series u_t = y1_t - a - b*y2_t.
  Step 2 (ADF): test u_t for a unit root via an augmented Dickey-Fuller
    regression. If the null of a unit root in u_t is REJECTED, y1 and y2 are
    judged cointegrated with hedge ratio b — a genuine, mean-reverting linear
    combination of two individually non-stationary (I(1)) price series. If
    the null is NOT rejected, the pair is judged not cointegrated, and this
    module says so plainly — kf/export.py then honestly excludes that pair
    from `kf/filter.py`'s Kalman stage rather than forcing a spread signal
    onto a relationship with no statistical basis for mean reversion.

This is the standard method (Engle & Granger, 1987, "Co-integration and
Error Correction: Representation, Estimation, and Testing", Econometrica
55(2)) as applied to pairs trading (Vidyamurthy, "Pairs Trading:
Quantitative Methods and Analysis", Wiley, 2004, ch. 4-5) — not a novel
statistical method invented for this engine.

## The ADF critical-value approximation this module makes, named honestly

The Engle-Granger test's residual series u_t is an ESTIMATED quantity (OLS
residuals from step 1), not an observed series — the standard ADF critical
values (for testing a raw observed series) do not apply to it. The correct
critical values for this exact test were derived by MacKinnon (1991, 2010,
"Critical Values for Cointegration Tests", Queen's Economics Department
Working Paper No. 1227) via a response-surface simulation that depends on
BOTH the number of variables in the cointegrating regression (here: 2) AND
the sample size T (finite-sample correction). `statsmodels.tsa.stattools.
coint()` implements MacKinnon's full response-surface formula; without
statsmodels, this module instead uses MacKinnon's reported ASYMPTOTIC
(T -> infinity) critical values for the two-variable case directly, as
fixed constants:

    1%: -3.9001   5%: -3.3377   10%: -3.0462

(MacKinnon 2010, Table 2, "Case 2" / N=2, no deterministic trend beyond the
constant already in the step-1 regression.) This is a DOCUMENTED
APPROXIMATION, not the exact finite-sample value: for a sample of a few
hundred observations (this engine's actual window — see kf/config.py's
LOOKBACK_CALENDAR_DAYS/MIN_OBSERVATIONS), the true finite-sample critical
value is typically slightly less negative than the asymptotic figure, which
means using the asymptotic constant is a MODEST CONSERVATIVE bias toward
finding NOT-cointegrated (the honest-abstention direction, not the
false-positive direction) — but this is a documented approximation
regardless, not claimed as exact. A pair whose ADF t-statistic sits close
to (within roughly a few hundredths of) the threshold should be read as a
genuinely marginal case, not a crisp yes/no.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# MacKinnon (2010) asymptotic critical values for the Engle-Granger
# two-step cointegration test, N=2 variables (one dependent, one regressor
# plus a constant), no additional deterministic trend. See module docstring
# for the exact citation and the honesty caveat about the finite-sample gap.
MACKINNON_EG_CRITICAL_VALUES_N2: dict[int, float] = {
    1: -3.9001,
    5: -3.3377,
    10: -3.0462,
}

SIGNIFICANCE_TO_PCT: dict[float, int] = {0.01: 1, 0.05: 5, 0.10: 10}


@dataclass(frozen=True)
class OLSResult:
    intercept: float
    slope: float
    residuals: np.ndarray
    r_squared: float
    n_obs: int


def ols_regress(y: np.ndarray, x: np.ndarray) -> OLSResult:
    """Plain OLS of y on [1, x] via numpy.linalg.lstsq — the "Step 1" of
    Engle-Granger. No statsmodels dependency; this is exactly the closed-form
    normal-equations solution any OLS routine computes, just written out
    directly (numpy's lstsq uses an SVD-based least-squares solve, which is
    numerically more stable than forming (X'X)^-1 X'y by hand for a design
    matrix that can be near-collinear when two price series are highly
    correlated — exactly the case where cointegration testing is most
    interesting)."""
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = y.size
    design = np.column_stack([np.ones(n), x])
    coeffs, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    intercept, slope = float(coeffs[0]), float(coeffs[1])
    fitted = design @ coeffs
    residuals = y - fitted
    ss_res = float(np.sum(residuals ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    return OLSResult(intercept=intercept, slope=slope, residuals=residuals, r_squared=r_squared, n_obs=n)


@dataclass(frozen=True)
class ADFResult:
    t_stat: float
    lag_used: int
    n_obs: int  # observations actually used in the auxiliary regression


def _aic(residuals: np.ndarray, n_params: int) -> float:
    n = residuals.size
    ss = float(np.sum(residuals ** 2))
    if ss <= 0 or n <= n_params:
        return float("inf")
    sigma2 = ss / n
    return n * np.log(sigma2) + 2 * n_params


def adf_test_statistic(series: np.ndarray, max_lag: int) -> ADFResult:
    """Augmented Dickey-Fuller test statistic on `series`, WITHOUT a
    constant or trend term in the auxiliary regression — the correct
    specification when `series` is itself a set of OLS residuals that are
    already mean-zero by construction (adding a constant back in would be
    redundant and would change the correct critical values again). This
    matches statsmodels.tsa.stattools.coint()'s own internal convention
    (regression="n" on the residual series) even though this module does
    not import statsmodels.

    Regression run, for each candidate lag order p from 0 to max_lag:

        delta(u_t) = rho * u_{t-1} + sum_{i=1..p} phi_i * delta(u_{t-i}) + e_t

    The reported t-statistic is rho_hat / se(rho_hat) — the standard ADF
    test statistic. Lag order p is chosen by AIC (Akaike Information
    Criterion) over the candidate range, the same selection principle
    statsmodels' adfuller(autolag="AIC") uses (not identical numerically —
    a from-scratch AIC search over a shared, fixed sample window across all
    candidate lags, rather than statsmodels' exact implementation detail of
    re-truncating the sample per lag order — but the same real selection
    criterion, not an arbitrary fixed lag)."""
    u = np.asarray(series, dtype=float)
    n_full = u.size
    du = np.diff(u)  # delta(u_t) for t = 1..n_full-1, i.e. du[t-1] = u[t]-u[t-1]

    best: ADFResult | None = None
    best_aic = float("inf")
    max_lag = max(0, min(max_lag, n_full - 3))  # need at least a few usable rows

    for p in range(0, max_lag + 1):
        # Usable rows: need du[t-1] as the dependent variable, u[t-1] as the
        # level regressor, and du[t-2], ..., du[t-1-p] as lagged-diff
        # regressors. First usable index (into du) is p+1.. up to end.
        start = p + 1
        if start >= du.size:
            continue
        y_rows = du[start:]
        # Index alignment: du[k] = u[k+1]-u[k]. For row index k=start..,
        # the level regressor is u[k] (=u_{t-1} where t=k+1), and lag j of the
        # diff regressor is du[k-j] for j=1..p.
        level = u[start:n_full - 1]
        design_cols = [level]
        for j in range(1, p + 1):
            design_cols.append(du[start - j: du.size - j])
        design = np.column_stack(design_cols) if design_cols else level.reshape(-1, 1)
        if design.shape[0] != y_rows.size:
            # Alignment guard: if any lag construction produced a mismatched
            # length (can happen at the small-sample edge), skip this lag
            # order rather than silently regress on misaligned rows.
            continue
        if design.shape[0] <= design.shape[1] + 1:
            continue  # not enough degrees of freedom for a meaningful se
        coeffs, _, _, _ = np.linalg.lstsq(design, y_rows, rcond=None)
        fitted = design @ coeffs
        resid = y_rows - fitted
        dof = design.shape[0] - design.shape[1]
        sigma2 = float(np.sum(resid ** 2)) / dof
        try:
            xtx_inv = np.linalg.inv(design.T @ design)
        except np.linalg.LinAlgError:
            continue
        se_rho = float(np.sqrt(sigma2 * xtx_inv[0, 0]))
        if se_rho <= 0 or not np.isfinite(se_rho):
            continue
        rho_hat = float(coeffs[0])
        t_stat = rho_hat / se_rho
        aic = _aic(resid, n_params=design.shape[1])
        if aic < best_aic:
            best_aic = aic
            best = ADFResult(t_stat=t_stat, lag_used=p, n_obs=design.shape[0])

    if best is None:
        # Degenerate: no lag order produced a usable regression (series too
        # short). Caller (engle_granger_test) treats this as "cannot test",
        # not as a fabricated pass/fail.
        return ADFResult(t_stat=float("nan"), lag_used=-1, n_obs=0)
    return best


@dataclass(frozen=True)
class CointegrationResult:
    ticker1: str
    ticker2: str
    is_cointegrated: bool
    hedge_ratio: float
    intercept: float
    r_squared: float
    adf_t_stat: float
    adf_lag_used: int
    critical_value_used: float
    significance: float
    critical_values: dict[int, float]
    n_obs: int
    reason: str  # human-readable — always populated, both on pass and abstain


def engle_granger_test(
    ticker1: str,
    ticker2: str,
    y1: np.ndarray,
    y2: np.ndarray,
    significance: float = 0.05,
    max_lag: int = 8,
) -> CointegrationResult:
    """Full two-step Engle-Granger test. `y1`/`y2` should be log-prices (see
    kf/filter.py's module docstring for why this engine uses log-prices, not
    raw prices) of equal length, already aligned to the same trading days by
    the caller (kf/export.py). Returns a CointegrationResult whose
    `is_cointegrated` is False, with a stated `reason`, whenever the ADF test
    fails to reject the unit-root null at `significance` — this function
    NEVER returns is_cointegrated=True on a technicality; a NaN t-stat
    (too-short series) is always False."""
    n = len(y1)
    ols = ols_regress(y1, y2)
    adf = adf_test_statistic(ols.residuals, max_lag=max_lag)

    pct = SIGNIFICANCE_TO_PCT.get(round(significance, 2), 5)
    critical_value = MACKINNON_EG_CRITICAL_VALUES_N2[pct]

    if not np.isfinite(adf.t_stat):
        return CointegrationResult(
            ticker1=ticker1, ticker2=ticker2, is_cointegrated=False,
            hedge_ratio=ols.slope, intercept=ols.intercept, r_squared=ols.r_squared,
            adf_t_stat=float("nan"), adf_lag_used=adf.lag_used,
            critical_value_used=critical_value, significance=significance,
            critical_values=dict(MACKINNON_EG_CRITICAL_VALUES_N2), n_obs=n,
            reason=(
                f"ADF regression on the step-1 OLS residuals could not be computed "
                f"(too few usable observations after differencing/lagging, n={n})."
            ),
        )

    # Reject the unit-root null (i.e. residual series is judged stationary,
    # i.e. y1/y2 ARE cointegrated) when the test statistic is MORE NEGATIVE
    # than the critical value — the ADF null is "has a unit root"; a more
    # negative statistic is stronger evidence against it, same convention as
    # every ADF/EG implementation.
    is_cointegrated = adf.t_stat < critical_value
    reason = (
        f"ADF t-stat {adf.t_stat:.3f} vs. {pct}% critical value {critical_value:.3f} "
        f"(lag={adf.lag_used}, n={adf.n_obs} in the auxiliary regression, MacKinnon "
        f"2010 asymptotic N=2 critical values — see module docstring for the "
        f"finite-sample-approximation caveat): "
        + (
            "unit-root null rejected — residual spread is judged mean-reverting."
            if is_cointegrated
            else "unit-root null NOT rejected — no statistical evidence this pair's "
            "OLS residual spread is stationary; abstaining rather than forcing a "
            "mean-reversion signal onto an untested relationship."
        )
    )
    return CointegrationResult(
        ticker1=ticker1, ticker2=ticker2, is_cointegrated=is_cointegrated,
        hedge_ratio=ols.slope, intercept=ols.intercept, r_squared=ols.r_squared,
        adf_t_stat=adf.t_stat, adf_lag_used=adf.lag_used,
        critical_value_used=critical_value, significance=significance,
        critical_values=dict(MACKINNON_EG_CRITICAL_VALUES_N2), n_obs=n,
        reason=reason,
    )

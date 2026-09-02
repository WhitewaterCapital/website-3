"""Ornstein-Uhlenbeck estimation — the mean-reversion core.

The OU process is the continuous-time mean-reverting SDE

        dX_t = theta * (mu - X_t) dt + sigma dW_t

with three quantities we care about for placing levels:

    mu         the long-run mean (the level price is pulled toward)
    theta      the speed of reversion (bigger => snaps back faster)
    sigma_eq   the equilibrium (stationary) standard deviation of X,
               = sigma / sqrt(2*theta) — the natural width of the band

and the derived, decision-ready number

    half_life  = ln(2) / theta   — how long a deviation takes to halve.
                 THIS is the model's time-stop: if the trade hasn't reverted in a
                 couple of half-lives, the thesis is stale.

Estimation. Sampled at spacing dt, an OU process is exactly a Gaussian AR(1):

        X_t = a + b * X_{t-1} + e,     b = exp(-theta*dt),   a = mu*(1-b)

so an ordinary least-squares fit of X_t on X_{t-1} is the maximum-likelihood
estimator (Gaussian errors), and we back out the OU parameters in closed form:

        theta    = -ln(b) / dt
        mu       = a / (1 - b)
        sigma_eq = sqrt( var(e) / (1 - b^2) )

Honesty guard: mean reversion only exists when 0 < b < 1. A random walk has
b ~ 1 (theta ~ 0, half-life -> infinity) and is NOT mean-reverting; a fit with
b >= 1 or b <= 0 returns `reverts = False` so the template declines rather than
inventing a band. Whether a *finite* half-life is short enough to trade is the
template's call, not this estimator's.

Everything here is a pure function over a 1-D array — unit-testable, and validated
against a simulated OU path with KNOWN parameters before it sees real prices.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OUParams:
    """Fitted OU parameters plus fit diagnostics."""

    mu: float          # long-run mean (in the units of the input series)
    theta: float       # mean-reversion speed (per unit time; dt sets the unit)
    sigma_eq: float    # equilibrium (stationary) std of the level
    half_life: float   # ln(2)/theta, in the same time units as dt
    b: float           # AR(1) slope = exp(-theta*dt)
    sigma_resid: float # residual std of the AR(1) fit
    # AR(1) level-on-level R^2. This tracks PERSISTENCE, not reversion strength:
    # near 1 for slow / random-walk-like series (b -> 1), LOWER for fast reversion
    # (small b). It is a diagnostic of autocorrelation, NOT a "good OU" score — the
    # template judges tradeability by half_life, not by this.
    r2: float
    n: int             # number of transitions used
    reverts: bool      # True only if b is STATISTICALLY below 1 (see se_b/df_stat)
    se_b: float = float("nan")     # standard error of the AR(1) slope b
    df_stat: float = float("nan")  # Dickey-Fuller t-stat (b - 1)/se_b


# Dickey-Fuller t-statistic critical value (constant, no trend; large-sample
# MacKinnon). The DF statistic (b-1)/se(b) must fall BELOW this to reject the unit
# root at ~5%. Using -2.86 gives roughly a 5% false-positive rate on a true random
# walk, vs ~50-65% for the old "b < 1" point estimate.
DF_CRIT_5PCT = -2.86


def fit_ou(x, dt: float = 1.0, df_crit: float = DF_CRIT_5PCT) -> OUParams:
    """Fit an OU process to a 1-D series `x` sampled at spacing `dt` (default 1
    'bar'). Returns OUParams; check `.reverts` before trusting the band.

    REVIEW FIXES (2026-08): `reverts` is no longer a bare point estimate (b < 1).
    A driftless random walk yields b < 1 by sampling noise a large fraction of the
    time, so the old rule accepted spurious mean reversion. We now require b to be
    STATISTICALLY below 1 via a Dickey-Fuller t-test: reverts only if the DF
    statistic (b-1)/se(b) < df_crit. The closed-form OU back-out is unchanged — only
    the accept/reject decision is. se_b and df_stat are exposed on OUParams."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 20:
        raise ValueError("need at least 20 points to fit OU")

    x0 = x[:-1]
    x1 = x[1:]
    n = x0.size

    # OLS of x1 on x0 (== Gaussian MLE for the AR(1) transition).
    x0m = x0.mean()
    x1m = x1.mean()
    sxx = np.sum((x0 - x0m) ** 2)
    if sxx <= 0:
        raise ValueError("degenerate series (no variance)")
    b = np.sum((x0 - x0m) * (x1 - x1m)) / sxx
    a = x1m - b * x0m

    resid = x1 - (a + b * x0)
    dof = max(n - 2, 1)
    var_resid = float(np.sum(resid ** 2) / dof)
    sigma_resid = float(np.sqrt(var_resid))

    ss_tot = float(np.sum((x1 - x1m) ** 2))
    r2 = float(1.0 - np.sum(resid ** 2) / ss_tot) if ss_tot > 0 else 0.0

    # Standard error of the OLS slope and the Dickey-Fuller t-statistic. reverts
    # requires b to be SIGNIFICANTLY below 1, not merely below 1.
    se_b = float(sigma_resid / np.sqrt(sxx)) if sxx > 0 else float("inf")
    df_stat = float((b - 1.0) / se_b) if np.isfinite(se_b) and se_b > 0 else 0.0
    reverts = bool(0.0 < b < 1.0 and df_stat < df_crit)
    if reverts:
        theta = -np.log(b) / dt
        mu = a / (1.0 - b)
        sigma_eq = float(np.sqrt(var_resid / (1.0 - b * b)))
        half_life = float(np.log(2.0) / theta)
    else:
        # No mean reversion (random walk / explosive): report an honest non-fit.
        theta = 0.0 if b >= 1.0 else float("nan")
        mu = float(x1m)  # best-effort location; not a reversion target
        sigma_eq = float("inf")
        half_life = float("inf")

    return OUParams(
        mu=float(mu),
        theta=float(theta),
        sigma_eq=float(sigma_eq),
        half_life=float(half_life),
        b=float(b),
        sigma_resid=sigma_resid,
        r2=r2,
        n=int(n),
        reverts=reverts,
        se_b=se_b,
        df_stat=df_stat,
    )


def simulate_ou(
    n: int,
    mu: float,
    theta: float,
    sigma: float,
    dt: float = 1.0,
    x0: float | None = None,
    seed: int = 0,
) -> np.ndarray:
    """Exact-discretisation OU simulator (for tests and what-ifs).

    Uses the exact transition X_{t+1} = mu + b*(X_t - mu) + N(0, sigma_eq^2*(1-b^2))
    with b = exp(-theta*dt), sigma_eq = sigma/sqrt(2*theta) — no Euler bias."""
    rng = np.random.default_rng(seed)
    b = np.exp(-theta * dt)
    sigma_eq = sigma / np.sqrt(2.0 * theta)
    step_sd = sigma_eq * np.sqrt(1.0 - b * b)
    x = np.empty(n)
    x[0] = mu if x0 is None else x0
    for i in range(1, n):
        x[i] = mu + b * (x[i - 1] - mu) + rng.normal(0.0, step_sd)
    return x

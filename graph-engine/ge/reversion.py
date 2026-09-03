"""Half-life of reversion for the graph residual's OWN time series.

This is the "done when" gate for the whole model (see README): the residual
computed in `residual.py` is only a *candidate* tradeable signal. Before it
ships, we fit a mean-reversion model to each name's residual time series and
require a SHORT, STATISTICALLY SIGNIFICANT half-life, materially inside the
proposed 1-10 day holding window (see `backtest.py`). If it doesn't revert, the
graph is wrong (wrong edges, wrong sparsification, wrong diffusion strength —
something upstream is not actually capturing "this name's peer group") and the
model does not ship, on this or any universe.

The math and the honesty discipline here are copied VERBATIM in pattern from
`intra-exitus-engine/ie/levels/ou.py` (same OUParams fields, same closed-form
AR(1)->OU back-out, same Dickey-Fuller significance gate, same
DF_CRIT_5PCT/OU_DF_CRIT_5PCT constant, same se_b/df_stat diagnostics). It is
duplicated, not imported — this engine is sealed and shares no code with
Intra/Exitus or any other model in this repo. See that module's docstring for
the full derivation; the summary:

The OU process dX_t = theta*(mu - X_t)dt + sigma*dW_t, sampled at spacing dt,
is exactly a Gaussian AR(1): X_t = a + b*X_{t-1} + e, b = exp(-theta*dt). An
OLS fit of X_t on X_{t-1} is the MLE, and

    theta    = -ln(b) / dt
    mu       = a / (1 - b)
    sigma_eq = sqrt(var(e) / (1 - b^2))
    half_life = ln(2) / theta

Honesty guard: a random walk has b ~ 1 (theta ~ 0, half-life -> infinity) and
is NOT mean-reverting. Because sampling noise alone makes a true random walk's
point-estimate b < 1 a majority of the time, `reverts` requires b to be
STATISTICALLY below 1 via a one-sided Dickey-Fuller t-test:
`(b - 1) / se(b) < OU_DF_CRIT_5PCT`. `half_life_days`/`half_life_significant`
in the export are None/False whenever this gate fails — never a fabricated
number.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .config import OU_DF_CRIT_5PCT

DF_CRIT_5PCT = OU_DF_CRIT_5PCT  # local alias, matching ou.py's constant name


@dataclass(frozen=True)
class OUParams:
    """Fitted OU parameters plus fit diagnostics. Field-for-field identical to
    intra-exitus-engine's OUParams (see module docstring)."""

    mu: float
    theta: float
    sigma_eq: float
    half_life: float
    b: float
    sigma_resid: float
    r2: float
    n: int
    reverts: bool
    se_b: float = float("nan")
    df_stat: float = float("nan")


def fit_ou(x, dt: float = 1.0, df_crit: float = DF_CRIT_5PCT) -> OUParams:
    """Fit an OU/AR(1) process to a 1-D series `x` sampled at spacing `dt`
    (default: 1 trading day, since this fits a daily residual series). Returns
    OUParams; check `.reverts` before trusting `half_life`."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if x.size < 20:
        raise ValueError("need at least 20 points to fit OU")

    x0 = x[:-1]
    x1 = x[1:]
    n = x0.size

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

    se_b = float(sigma_resid / np.sqrt(sxx)) if sxx > 0 else float("inf")
    df_stat = float((b - 1.0) / se_b) if np.isfinite(se_b) and se_b > 0 else 0.0
    reverts = bool(0.0 < b < 1.0 and df_stat < df_crit)
    if reverts:
        theta = -np.log(b) / dt
        mu = a / (1.0 - b)
        sigma_eq = float(np.sqrt(var_resid / (1.0 - b * b)))
        half_life = float(np.log(2.0) / theta)
    else:
        theta = 0.0 if b >= 1.0 else float("nan")
        mu = float(x1m)
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
    """Exact-discretisation OU simulator, for tests/what-ifs. Identical to
    ie/levels/ou.py's simulator."""
    rng = np.random.default_rng(seed)
    b = np.exp(-theta * dt)
    sigma_eq = sigma / np.sqrt(2.0 * theta)
    step_sd = sigma_eq * np.sqrt(1.0 - b * b)
    x = np.empty(n)
    x[0] = mu if x0 is None else x0
    for i in range(1, n):
        x[i] = mu + b * (x[i - 1] - mu) + rng.normal(0.0, step_sd)
    return x

"""
Barrier option payoffs (PATH-03): all eight up/down x in/out x call/put
combinations, configurable monitoring frequency, WITH the Brownian-bridge
continuity correction PATH-04 explicitly calls for.

Why the correction matters
---------------------------
A simulated path only tells you the spot at each *monitored* time step. A
barrier at H can be breached by the true continuous path strictly between
two monitored dates without either endpoint being on the wrong side of H —
discrete monitoring on a simulated path therefore systematically
*understates* knock probability (overstates "in" wait no — understates
knock-out frequency / overstates knock-in survival) relative to the
continuously-monitored contract, and the bias does not vanish as
`n_paths -> inf`; it only shrinks as the monitoring grid is refined
(`n_steps -> inf`), which is expensive. The fix used here does not refine
the grid — it corrects for what happened *between* the grid points
analytically.

The correction: for a step of length `dt` with (log-)spot endpoints known
and instantaneous volatility `sigma` locally constant over the step, the
probability that a Brownian motion **bridge** between those two endpoints
dipped below (down-barrier) or rose above (up-barrier) the log-barrier
strictly inside the interval has the closed form (reflection principle for
Brownian motion; see Glasserman, P. (2003), "Monte Carlo Methods in
Financial Engineering", Springer, Section 6.4.2, and the original
application to discrete barrier bias in Broadie, Glasserman & Kou (1997),
"A Continuity Correction for Discrete Barrier Options", Mathematical
Finance 7(4)):

    P(min_{[0,dt]} X_s < b | X_0 = x0, X_dt = x1) = exp(-2*(x0-b)*(x1-b) / (sigma^2 * dt))
        for a DOWN barrier, valid when x0 > b and x1 > b (log-space: b = ln H)

    P(max_{[0,dt]} X_s > b | X_0 = x0, X_dt = x1) = exp(-2*(b-x0)*(b-x1) / (sigma^2 * dt))
        for an UP barrier, valid when x0 < b and x1 < b

This module uses that per-interval probability as a **conditional
expectation replacing a 0/1 indicator** (a Rao-Blackwellized / conditional
Monte Carlo estimator, per Glasserman Ch. 6.4): the probability the path
*survived* the whole monitoring schedule without ever touching the barrier
continuously is the product, over every interval, of `(1 - p_cross_i)`
(taking `p_cross_i = 1` outright for any interval whose discretely-observed
endpoints already breached). A knock-out payoff is then the vanilla payoff
times that survival probability; a knock-in payoff is the vanilla payoff
times its complement. This is strictly more informative *per path* than a
hard indicator (it also reduces Monte Carlo variance, a standard side
benefit of conditional Monte Carlo), and it is what removes the
discrete-monitoring bias that a raw endpoint check leaves on the table —
`tests/test_barrier_analytic.py` checks the corrected estimator against the
Reiner-Rubinstein continuous-barrier closed form (`pe.payoffs.closed_form`)
specifically to demonstrate that improvement.

The correction assumes volatility is (at least locally) constant over each
monitoring interval — exact for the flat-vol GBM engine this is validated
against, and the standard, documented approximation when applied to
local-vol or Heston paths (pass the instantaneous vol realized over that
step, e.g. from a local-vol lookup or `sqrt(v_t)` from a Heston variance
path, as `sigma_path`).
"""
from __future__ import annotations

from typing import Literal, Optional

import numpy as np

OptionType = Literal["call", "put"]
BarrierDirection = Literal["up", "down"]
BarrierKind = Literal["in", "out"]


def _vanilla_payoff(S_T: np.ndarray, K: float, option_type: OptionType) -> np.ndarray:
    phi = 1.0 if option_type == "call" else -1.0
    return np.maximum(phi * (S_T - K), 0.0)


def discrete_breach_indicator(
    paths: np.ndarray,
    H: float,
    direction: BarrierDirection,
    monitor_idx: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Boolean array, one per path: True if any *monitored* column crossed
    the barrier. `monitor_idx` defaults to every column including t=0 (the
    usual convention: a barrier already breached at inception counts)."""
    n_paths, n_cols = paths.shape
    idx = np.arange(n_cols) if monitor_idx is None else np.asarray(monitor_idx, dtype=int)
    monitored = paths[:, idx]
    if direction == "up":
        return np.any(monitored >= H, axis=1)
    return np.any(monitored <= H, axis=1)


def survival_probability_with_bridge(
    paths: np.ndarray,
    times: np.ndarray,
    H: float,
    direction: BarrierDirection,
    sigma_path: float | np.ndarray,
    monitor_idx: Optional[np.ndarray] = None,
) -> np.ndarray:
    """P(never continuously breached H over the whole schedule), per path,
    via the bridge-crossing correction described in the module docstring.

    `sigma_path` is either a single flat volatility (GBM) or an array of
    shape (n_paths, n_steps) or (n_steps,) giving the volatility realized
    over each monitoring interval `[idx[j], idx[j+1]]` (index j of that
    array corresponds to the interval *starting* at `monitor_idx[j]`).
    """
    n_paths, n_cols = paths.shape
    idx = np.arange(n_cols) if monitor_idx is None else np.asarray(monitor_idx, dtype=int)
    n_intervals = idx.size - 1
    if n_intervals < 0:
        raise ValueError("need at least one monitored point")

    log_b = np.log(H)
    log_paths = np.log(paths[:, idx])  # (n_paths, n_monitored)

    sigma_arr = np.asarray(sigma_path, dtype=float)
    if sigma_arr.ndim == 0:
        sigma_arr = np.full(n_intervals, float(sigma_arr))
    elif sigma_arr.ndim == 1 and sigma_arr.shape[0] == n_intervals:
        pass
    elif sigma_arr.ndim == 2:
        sigma_arr = sigma_arr[:, : n_intervals]
    else:
        raise ValueError("sigma_path must be scalar, shape (n_intervals,), or (n_paths, n_intervals)")

    survive = np.ones(n_paths)
    for j in range(n_intervals):
        x0 = log_paths[:, j]
        x1 = log_paths[:, j + 1]
        dt = times[idx[j + 1]] - times[idx[j]]
        sig = sigma_arr[j] if sigma_arr.ndim == 1 else sigma_arr[:, j]
        sig = np.asarray(sig, dtype=float)

        if direction == "down":
            already = (x0 <= log_b) | (x1 <= log_b)
            gap0 = np.maximum(x0 - log_b, 0.0)
            gap1 = np.maximum(x1 - log_b, 0.0)
        else:
            already = (x0 >= log_b) | (x1 >= log_b)
            gap0 = np.maximum(log_b - x0, 0.0)
            gap1 = np.maximum(log_b - x1, 0.0)

        with np.errstate(divide="ignore", invalid="ignore"):
            denom = np.where((sig > 0) & (dt > 0), sig * sig * dt, np.inf)
            p_cross = np.exp(-2.0 * gap0 * gap1 / denom)
        p_cross = np.where(already, 1.0, p_cross)
        p_cross = np.clip(p_cross, 0.0, 1.0)
        survive *= 1.0 - p_cross

    return survive


def barrier_payoff(
    paths: np.ndarray,
    K: float,
    H: float,
    option_type: OptionType,
    direction: BarrierDirection,
    kind: BarrierKind,
    monitor_idx: Optional[np.ndarray] = None,
    times: Optional[np.ndarray] = None,
    sigma_path: Optional[float | np.ndarray] = None,
) -> np.ndarray:
    """Undiscounted per-path payoff for one of the eight
    up/down x in/out x call/put barrier flavors.

    Without `sigma_path` (i.e. `times`/`sigma_path` both None): a plain
    discrete-monitoring indicator (`discrete_breach_indicator`) — the naive,
    biased-relative-to-continuous estimator, kept available deliberately so
    the bias it carries can be measured directly against the corrected
    version and the closed form (see `tests/test_barrier_analytic.py`).

    With `times` and `sigma_path` given: the Brownian-bridge-corrected
    estimator (`survival_probability_with_bridge`) is used instead of a
    hard 0/1 breach flag.
    """
    S_T = paths[:, -1]
    vanilla = _vanilla_payoff(S_T, K, option_type)

    if times is not None and sigma_path is not None:
        p_survive = survival_probability_with_bridge(paths, times, H, direction, sigma_path, monitor_idx)
        if kind == "out":
            return vanilla * p_survive
        return vanilla * (1.0 - p_survive)

    breached = discrete_breach_indicator(paths, H, direction, monitor_idx)
    if kind == "out":
        return np.where(breached, 0.0, vanilla)
    return np.where(breached, vanilla, 0.0)

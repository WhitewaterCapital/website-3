"""
Geometric Brownian Motion path simulation — the closed-form-checkable
baseline every other engine in this package is validated against
(PATH-02a). If this doesn't reprice Black-Scholes within its own reported
standard error, nothing built on top of it can be trusted either.
"""
from __future__ import annotations

import numpy as np

from .random_streams import normal_increments


def simulate_gbm_paths(
    S0: float,
    r: float,
    q: float,
    sigma: float,
    T: float,
    n_steps: int,
    n_paths: int,
    seed: int,
    antithetic: bool = True,
    use_sobol: bool = True,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Exact-in-distribution GBM path simulation (log-Euler is exact for GBM
    since sigma is constant — no discretization bias at all, unlike local
    vol or Heston).

    Returns (times, paths, info):
        times: shape (n_steps + 1,), times[0] = 0
        paths: shape (n_paths, n_steps + 1), paths[:, 0] = S0
        info: dict from `normal_increments` (whether Sobol/bridge were used)
    """
    if T <= 0:
        raise ValueError("T must be positive")
    dt = T / n_steps
    z, info = normal_increments(n_paths, n_steps, seed, antithetic=antithetic, use_sobol=use_sobol, dt=dt)
    drift = (r - q - 0.5 * sigma * sigma) * dt
    diffusion = sigma * np.sqrt(dt) * z
    log_increments = drift + diffusion
    log_paths = np.cumsum(log_increments, axis=1)
    paths = S0 * np.exp(np.concatenate([np.zeros((n_paths, 1)), log_paths], axis=1))
    times = np.linspace(0.0, T, n_steps + 1)
    return times, paths, info

"""
Random number generation: seed/stream splitting for common random numbers
(CRN), antithetic pairing, and a Sobol + Brownian-bridge path generator with
a documented, honest fallback.

Common random numbers (PATH-04)
--------------------------------
`spawn_streams(base_seed, n)` uses `numpy.random.SeedSequence.spawn`, which
gives `n` *independent, reproducible* child streams from one base seed.
The CRN pattern used throughout this engine is: call the same simulation
function twice (two strikes, two valuation dates, model A vs model B) with
the *same* `seed` argument. Because path generation here is a pure function
of `(seed, n_paths, n_steps, use_sobol)`, identical draws are reused across
the two calls and only the payoff/model difference shows up in the
difference of the two prices — which is the entire point of CRN: it turns
"is A more expensive than B" into a paired comparison with much lower
variance than pricing A and B independently. `pe.validation.model_comparison`
uses exactly this pattern to keep the three-model spread comparison honest
(same terminal payoffs are not implied, but the same driving noise is used
wherever the models share a noise source, e.g. GBM vs local vol both being
driven by the same Brownian increments).

Sobol + Brownian bridge (PATH-04)
----------------------------------
`scipy.stats.qmc.Sobol` is available in this environment (checked at import
time below), so this module uses it: draws are generated in Sobol's
low-discrepancy sequence, mapped to standard normals via the inverse CDF,
and then re-ordered through a Brownian-bridge construction so that the
*best-distributed* (earliest) Sobol dimensions carry the *coarsest* features
of the path (the terminal value first, then the midpoint, etc.) rather than
the first daily increment — this is exactly the point of pairing QMC with a
bridge (see Caflisch, Morokoff & Owen (1997), "Valuation of mortgage-backed
securities using Brownian bridges to reduce effective dimension"; Glasserman,
"Monte Carlo Methods in Financial Engineering" (2003), Section 3.1 gives the
same construction as the standard reference implementation, which is also
what QuantLib's `BrownianBridge` class implements and what the index
bookkeeping below is transcribed from).

Honest fallback: Sobol's construction quality degrades once the requested
dimension (== `n_steps`, one Sobol coordinate per time step before bridging)
gets large, and `scipy`'s direction numbers are only tabulated up to a
fixed maximum dimension. This module caps Sobol use at `MAX_SOBOL_DIM`
dimensions; above that, or if Sobol construction raises for any reason, it
falls back to plain pseudo-random normals from `numpy.random.Generator` and
tags the result accordingly (`used_sobol=False` in the returned info) —
never silently claims QMC quality it didn't deliver. `n_paths` also does
not need to be a power of two here (`Sobol.random` is used, not
`random_base2`), which trades away some of Sobol's exact net-balance
property for the flexibility of an arbitrary path count; that trade-off is
the honest thing to state rather than hide.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy.stats import norm

try:
    from scipy.stats import qmc as _qmc

    _SOBOL_AVAILABLE = True
except Exception:  # pragma: no cover - environment without qmc
    _qmc = None
    _SOBOL_AVAILABLE = False

MAX_SOBOL_DIM = 1000  # conservative cap; see module docstring


def spawn_streams(base_seed: int, n: int) -> list[np.random.Generator]:
    """n independent, reproducible RNG streams from one base seed (for CRN
    across, e.g., the variance driver and the price driver in Heston, or
    across two calibration runs being compared)."""
    ss = np.random.SeedSequence(base_seed)
    return [np.random.default_rng(child) for child in ss.spawn(n)]


# ---------------------------------------------------------------------------
# Brownian bridge index construction (Caflisch-Morokoff-Owen / Glasserman
# Sec. 3.1 construction; same bookkeeping as QuantLib's BrownianBridge).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _BridgeIndices:
    bridge_index: np.ndarray
    left_index: np.ndarray
    right_index: np.ndarray
    left_weight: np.ndarray
    right_weight: np.ndarray
    std_dev: np.ndarray


def _build_bridge_indices(times: np.ndarray) -> _BridgeIndices:
    n = len(times)
    bridge_index = np.zeros(n, dtype=int)
    left_index = np.zeros(n, dtype=int)
    right_index = np.zeros(n, dtype=int)
    left_weight = np.zeros(n)
    right_weight = np.zeros(n)
    std_dev = np.zeros(n)

    populated = np.zeros(n, dtype=bool)

    # Step 0: the terminal point is generated first from a single Gaussian.
    left_index[0] = 0
    right_index[0] = n - 1
    bridge_index[0] = n - 1
    std_dev[0] = np.sqrt(times[n - 1])
    left_weight[0] = right_weight[0] = 0.0
    populated[n - 1] = True

    j = 0
    for i in range(1, n):
        while populated[j]:
            j += 1
        k = j
        while not populated[k]:
            k += 1
        ell = j + ((k - 1 - j) >> 1)
        populated[ell] = True
        bridge_index[i] = ell
        left_index[i] = j
        right_index[i] = k
        if j:
            left_weight[i] = (times[k] - times[ell]) / (times[k] - times[j - 1])
            right_weight[i] = (times[ell] - times[j - 1]) / (times[k] - times[j - 1])
            std_dev[i] = np.sqrt(
                (times[ell] - times[j - 1]) * (times[k] - times[ell]) / (times[k] - times[j - 1])
            )
        else:
            left_weight[i] = (times[k] - times[ell]) / times[k]
            right_weight[i] = times[ell] / times[k]
            std_dev[i] = np.sqrt(times[ell] * (times[k] - times[ell]) / times[k])
        j = k + 1
        if j >= n:
            j = 0
    return _BridgeIndices(bridge_index, left_index, right_index, left_weight, right_weight, std_dev)


def _apply_bridge(z: np.ndarray, times: np.ndarray, idx: _BridgeIndices) -> np.ndarray:
    """z: (n_paths, n_steps) standard normals in Sobol-dimension order.
    Returns W(t_1..t_n) path *levels* (not increments), shape (n_paths, n_steps).
    """
    n_paths, n = z.shape
    path = np.zeros((n_paths, n))
    path[:, idx.bridge_index[0]] = idx.std_dev[0] * z[:, 0]
    for i in range(1, n):
        ell = idx.bridge_index[i]
        j = idx.left_index[i]
        k = idx.right_index[i]
        if j:
            path[:, ell] = (
                idx.left_weight[i] * path[:, j - 1]
                + idx.right_weight[i] * path[:, k]
                + idx.std_dev[i] * z[:, i]
            )
        else:
            path[:, ell] = idx.right_weight[i] * path[:, k] + idx.std_dev[i] * z[:, i]
    return path


def normal_increments(
    n_paths: int,
    n_steps: int,
    seed: int,
    antithetic: bool = True,
    use_sobol: bool = True,
    dt: Optional[float] = None,
) -> tuple[np.ndarray, dict]:
    """Standard-normal increments per step, shape (n_paths, n_steps).

    Returns (z, info) where info reports what was actually used
    (`{'used_sobol': bool, 'used_bridge': bool, 'antithetic': bool}`) —
    callers/tests should read this rather than assume the request was
    honored, per the honest-fallback policy in the module docstring.

    `dt` is only used to build the bridge's (uniform) time grid; if omitted
    a unit grid `1..n_steps` is used, which is equivalent for the bridge's
    *increment* output (increments are dimensionless standard normals
    regardless of the time scale used to build the bridge weights, since a
    uniform grid rescales all bridge weights by the same factor).
    """
    n_base = int(np.ceil(n_paths / 2)) if antithetic else n_paths
    used_sobol = False
    used_bridge = False

    if use_sobol and _SOBOL_AVAILABLE and 1 <= n_steps <= MAX_SOBOL_DIM:
        try:
            sampler = _qmc.Sobol(d=n_steps, scramble=True, seed=seed)
            u = sampler.random(n_base)
            eps = 1e-10
            u = np.clip(u, eps, 1.0 - eps)
            z_dims = norm.ppf(u)  # (n_base, n_steps), dimension order = Sobol dim order
            times = np.arange(1, n_steps + 1, dtype=float) if dt is None else np.arange(1, n_steps + 1) * dt
            idx = _build_bridge_indices(times)
            levels = _apply_bridge(z_dims, times, idx)  # W(t_1..t_n) per path
            increments = np.diff(np.concatenate([np.zeros((n_base, 1)), levels], axis=1), axis=1)
            step_dt = times[1] - times[0] if n_steps > 1 else times[0]
            z = increments / np.sqrt(step_dt)  # back to iid-standard-normal-equivalent increments
            used_sobol = True
            used_bridge = True
        except Exception:
            z = None
    else:
        z = None

    if z is None:
        rng = np.random.default_rng(seed)
        z = rng.standard_normal((n_base, n_steps))

    if antithetic:
        z_full = np.concatenate([z, -z], axis=0)[:n_paths]
    else:
        z_full = z[:n_paths]

    info = {"used_sobol": used_sobol, "used_bridge": used_bridge, "antithetic": antithetic, "n_paths": n_paths}
    return z_full, info

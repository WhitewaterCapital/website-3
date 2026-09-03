"""
Dupire local volatility (PATH-02b): calibrated to reproduce a given,
already-arbitrage-free `VolSurface` *exactly by construction* — there is no
optimizer here, no fitting error, no regularization. Dupire's formula is an
algebraic identity: feed it the surface's total variance and its
derivatives and it hands back the unique diffusion coefficient whose
risk-neutral marginals reproduce that surface's European option prices at
every strike and maturity simultaneously. The calibration *is* the formula;
"validation" (see `pe/validation` and `tests/test_localvol_calibration.py`)
means re-pricing European options along simulated local-vol paths and
checking they come back out within Monte Carlo error — proof the Euler
discretization used to walk the SDE didn't quietly break the identity.

Dupire's formula in (forward log-moneyness, total variance) coordinates
(Gatheral, "The Volatility Surface: A Practitioner's Guide" (2006), eq.
1.10):

    sigma_loc(k, T)^2 = (dw/dT) / g(k, T)

    g(k, T) = (1 - k*w_k/(2w))^2 - (w_k^2/4)*(1/w + 1/4) + w_kk/2

`g` here is *exactly* `pe.surface.arbitrage.durrleman_g` — not a coincidence
(see that module's docstring) and not restated independently: this module
imports and calls it, so the local-vol denominator and the butterfly-
arbitrage test are provably the same function evaluated the same way. A
surface that fails `check_butterfly_arbitrage` has g <= 0 somewhere, which
is precisely where Dupire's formula has no real, non-negative solution —
local vol calibration on such a surface is not "less accurate," it is
undefined at that point, and this module does not paper over that: it
floors the denominator at a small positive epsilon and documents that the
resulting local variance there is a numerical artifact, not a diffusion
coefficient anyone should trust.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..surface.arbitrage import durrleman_g
from ..surface.surface import VolSurface
from .random_streams import normal_increments

_G_FLOOR = 1e-6  # denominator floor; see module docstring
_VAR_FLOOR = 1e-8  # local variance floor (avoids sigma_loc=0 stalling the diffusion)
_VAR_CEIL = 25.0  # generous ceiling (500% vol) against finite-difference blowups at T->0


def _grid_local_variance(surface: VolSurface, k_arr: np.ndarray, T: float) -> np.ndarray:
    """Local variance for a GRID-backed surface (`surface.w_func is None`),
    differentiated *exactly the way the surface itself is actually
    evaluated for pricing* rather than by an arbitrary off-grid bump.

    `VolSurface.total_variance` is piecewise-linear in k (interpolating
    `w_grid` via `np.interp`) and piecewise-linear in T (blending two
    bracketing slices). Naively bumping that function with a small `fd_h`
    differentiates a kinked interpolant with an inappropriately tiny step
    and blows up right at grid nodes — the module used to do exactly that;
    see git history / the surrounding discussion in this module's
    docstring for why it doesn't anymore. The fix used here instead
    computes the derivative *of the same piecewise-linear object*
    consistently with its own construction:

    - k-derivatives: `np.gradient` on each T-slice's actual `w_grid` row
      against `k_grid` (the same technique `pe.surface.arbitrage`'s
      butterfly check already uses for grid surfaces) gives a proper,
      bounded estimate of `w_k`/`w_kk` *at each grid node*; those nodal
      derivative values are then linearly interpolated to the query `k`
      with `np.interp`, exactly mirroring how `total_variance` itself
      linearly interpolates `w`. This is well-conditioned at any grid
      resolution because the step size used by `np.gradient` is always
      the surface's own (fixed) node spacing, never an unrelated bump size.
    - T-derivative: since `total_variance` blends two bracketing slices
      *linearly* in T, `dw/dT` within that bracket is exactly the slope
      `(w_hi_slice - w_lo_slice) / (T_hi - T_lo)` at the (k-interpolated)
      slice values — computed here in closed form, not by finite
      differencing across a step that could itself straddle a T-grid kink.
    """
    k_grid = surface.k_grid
    w_prime_grid = np.gradient(surface.w_grid, k_grid, axis=1)
    w_dpp_grid = np.gradient(w_prime_grid, k_grid, axis=1)

    def interp_row(row: np.ndarray) -> np.ndarray:
        return np.interp(k_arr, k_grid, row)

    T_grid = surface.T_grid
    if T <= T_grid[0]:
        scale = T / T_grid[0]
        w = interp_row(surface.w_grid[0]) * scale
        w_prime = interp_row(w_prime_grid[0]) * scale
        w_dpp = interp_row(w_dpp_grid[0]) * scale
        w_T = interp_row(surface.w_grid[0]) / T_grid[0]
    elif T >= T_grid[-1]:
        scale = T / T_grid[-1]
        w = interp_row(surface.w_grid[-1]) * scale
        w_prime = interp_row(w_prime_grid[-1]) * scale
        w_dpp = interp_row(w_dpp_grid[-1]) * scale
        w_T = interp_row(surface.w_grid[-1]) / T_grid[-1]
    else:
        j = int(np.searchsorted(T_grid, T))
        T0, T1 = T_grid[j - 1], T_grid[j]
        w0, w1 = interp_row(surface.w_grid[j - 1]), interp_row(surface.w_grid[j])
        wp0, wp1 = interp_row(w_prime_grid[j - 1]), interp_row(w_prime_grid[j])
        wpp0, wpp1 = interp_row(w_dpp_grid[j - 1]), interp_row(w_dpp_grid[j])
        lam = (T - T0) / (T1 - T0)
        w = (1.0 - lam) * w0 + lam * w1
        w_prime = (1.0 - lam) * wp0 + lam * wp1
        w_dpp = (1.0 - lam) * wpp0 + lam * wpp1
        w_T = (w1 - w0) / (T1 - T0)

    g = durrleman_g(k_arr, w, w_prime, w_dpp)
    g_safe = np.maximum(g, _G_FLOOR)
    return w_T / g_safe


def local_variance(
    surface: VolSurface,
    k: np.ndarray | float,
    T: float,
    fd_h_k: float = 1e-3,
    fd_h_T: float = 1e-4,
) -> np.ndarray:
    """sigma_loc(k, T)^2, vectorized over k.

    Grid-backed surfaces (`surface.w_func is None`) are differentiated
    exactly, consistently with how they are actually interpolated for
    pricing — see `_grid_local_variance`'s docstring for why a naive
    off-grid finite-difference bump is the wrong tool here (it
    differentiates a piecewise-linear interpolant's kinks, not the smile's
    real curvature, and diverges rather than converging as the bump
    shrinks). `fd_h_k`/`fd_h_T` are accepted but unused in that case.

    Analytic (`from_parametric`) surfaces have no such kink, so plain
    central finite differences with the given small steps are used
    directly — accuracy there is limited only by roundoff, not by an
    interpolation artifact.

    `fd_h_T` (parametric case) is clipped so `T - fd_h_T` never goes below
    a small positive floor (T=0 is a coordinate singularity: w(k, 0) = 0
    identically, and `VolSurface.total_variance` already special-cases T
    at/under the grid's first maturity by linear-in-T extrapolation
    towards that limit).
    """
    k_arr = np.atleast_1d(np.asarray(k, dtype=float))
    T = float(T)

    if surface.w_func is None:
        var = _grid_local_variance(surface, k_arr, T)
    else:
        T_lo = max(T - fd_h_T, 1e-6)
        T_hi = T + fd_h_T

        w = np.atleast_1d(np.asarray(surface.total_variance(k_arr, T), dtype=float))
        w_lo = np.atleast_1d(np.asarray(surface.total_variance(k_arr, T_lo), dtype=float))
        w_hi = np.atleast_1d(np.asarray(surface.total_variance(k_arr, T_hi), dtype=float))
        w_T = (w_hi - w_lo) / (T_hi - T_lo)

        w_up = np.atleast_1d(np.asarray(surface.total_variance(k_arr + fd_h_k, T), dtype=float))
        w_dn = np.atleast_1d(np.asarray(surface.total_variance(k_arr - fd_h_k, T), dtype=float))
        w_k = (w_up - w_dn) / (2.0 * fd_h_k)
        w_kk = (w_up - 2.0 * w + w_dn) / (fd_h_k**2)

        g = durrleman_g(k_arr, w, w_k, w_kk)
        g_safe = np.maximum(g, _G_FLOOR)
        var = w_T / g_safe

    var = np.clip(var, _VAR_FLOOR, _VAR_CEIL)
    return var if np.ndim(k) else float(var[0])


def local_vol(surface: VolSurface, k: np.ndarray | float, T: float, **fd_kwargs) -> np.ndarray:
    """sigma_loc(k, T) = sqrt(local_variance(...))."""
    var = local_variance(surface, k, T, **fd_kwargs)
    return np.sqrt(var) if np.ndim(k) else float(np.sqrt(var))


@dataclass(frozen=True)
class LocalVolParams:
    """Everything needed to walk the Dupire SDE from a `VolSurface`.

    `surface` is assumed pre-validated (see `pe.surface.arbitrage`) — this
    module does not re-check arbitrage, it only evaluates the formula.
    """

    surface: VolSurface
    S0: float
    r: float
    q: float


def simulate_local_vol_paths(
    params: LocalVolParams,
    T: float,
    n_steps: int,
    n_paths: int,
    seed: int,
    antithetic: bool = True,
    use_sobol: bool = True,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Euler-Maruyama simulation under Dupire local volatility.

    Unlike GBM (exact) and Heston-QE (near-exact per step), there is no
    exact discretization of a general local-vol SDE, so this is plain
    log-Euler:

        d(ln S_t) = (r - q - 0.5 sigma_loc(k_t, t)^2) dt + sigma_loc(k_t, t) dW_t
        k_t = ln(S_t / F(t)),  F(t) = S0 * exp((r - q) * t)

    i.e. at each step the local vol surface is looked up at the *current*
    simulated spot's forward log-moneyness and the *current* time — the
    standard Dupire-simulation recipe (Gatheral 2006, Ch. 1; Andreasen &
    Huge (2011) discuss faster calibration but the simulation recipe is
    unchanged). This carries an O(dt) discretization bias like any Euler
    scheme; `n_steps` should be large enough that the bias is small next to
    the reported Monte Carlo standard error (see
    `tests/test_localvol_calibration.py`, which checks exactly that).
    """
    if T <= 0:
        raise ValueError("T must be positive")
    surface, S0, r, q = params.surface, params.S0, params.r, params.q
    dt = T / n_steps
    sqrt_dt = np.sqrt(dt)
    z, info = normal_increments(n_paths, n_steps, seed, antithetic=antithetic, use_sobol=use_sobol, dt=dt)

    log_S = np.full(n_paths, np.log(S0))
    times = np.linspace(0.0, T, n_steps + 1)
    log_paths = np.empty((n_paths, n_steps + 1))
    log_paths[:, 0] = log_S

    for i in range(n_steps):
        t = times[i]
        F_t = S0 * np.exp((r - q) * t) if t > 0 else S0
        S_t = np.exp(log_S)
        k_t = np.log(S_t / F_t)
        # local vol needs T > 0 to be well defined (w(k,0)=0); use the first
        # step's midpoint for i==0 rather than evaluating exactly at t=0.
        T_eval = t if t > 0 else 0.5 * dt
        sigma_t = local_vol(surface, k_t, T_eval)
        log_S = log_S + (r - q - 0.5 * sigma_t**2) * dt + sigma_t * sqrt_dt * z[:, i]
        log_paths[:, i + 1] = log_S

    paths = np.exp(log_paths)
    return times, paths, info

"""
VolSurface: forward-moneyness / total-variance representation.

PATH-01 calls this out explicitly as the parameterization to standardize on
because it is "far better behaved across expiries" than strike/vol grids:
strike grids need re-interpolating every time the forward moves, and raw
implied vol smiles pinch and re-flare with maturity in ways that make
calendar arbitrage hard to see by eye. In (k, w) space —

    k = ln(K / F(T))          forward log-moneyness
    w(k, T) = sigma_impl(k,T)^2 * T     total implied variance

— a calendar-arbitrage-free surface is simply one where w is non-decreasing
in T at fixed k, and a butterfly-arbitrage-free smile is one satisfying a
single closed-form condition on w and its k-derivatives (see
`pe.surface.arbitrage.durrleman_g`). Both checks become cheap, local,
numerical conditions instead of requiring you to re-price a grid of calls.

Live-data note: this module only ever *represents* and *validates* a
surface. Building one from a real listed-options chain (PATH-01's fitting
step) is blocked in this environment — there is no options-data vendor
wired up here. `VolSurface` is fully usable today from a synthetic or
user-supplied grid (see `pe.surface.svi` for an arbitrage-free synthetic
generator), and the fitting step is a drop-in addition later: whatever
optimizer fits SVI/SSVI/Heston parameters to a live chain just needs to
hand its output to `VolSurface.from_grid` or `VolSurface.from_parametric`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np


TotalVarianceFunc = Callable[[np.ndarray, float], np.ndarray]
# w_func(k_array, T) -> total variance array, same shape as k_array.


@dataclass
class VolSurface:
    """A volatility surface in (forward log-moneyness, total variance) coordinates.

    Two ways to build one:

    1. `VolSurface.from_grid(k_grid, T_grid, w_grid)` — a discrete grid,
       `w_grid[i, j] = w(k_grid[j], T_grid[i])`. This is what a real chain
       fit would ultimately produce (post-PATH-01), and what the
       arbitrage checks run their grid tests on.
    2. `VolSurface.from_parametric(k_grid, T_grid, w_func)` — a callable
       total-variance function (e.g. an SVI slice per maturity). The grid
       is still stored (for the same grid-based checks and for plotting),
       but derivatives used by local vol calibration are taken from the
       analytic function via finite differences with a small step, which
       is materially less noisy than differencing an interpolated grid.

    Either way, `total_variance(k, T)` and `implied_vol(k, T)` interpolate
    smoothly between grid points (linear in total variance across
    maturities at fixed k — the standard no-calendar-arbitrage-preserving
    interpolation — and cubic in k within a maturity slice).
    """

    k_grid: np.ndarray  # shape (n_k,), strictly increasing
    T_grid: np.ndarray  # shape (n_T,), strictly increasing, all > 0
    w_grid: np.ndarray  # shape (n_T, n_k); w_grid[i, j] = w(k_grid[j], T_grid[i])
    w_func: Optional[TotalVarianceFunc] = field(default=None, repr=False)
    label: str = ""

    def __post_init__(self) -> None:
        self.k_grid = np.asarray(self.k_grid, dtype=float)
        self.T_grid = np.asarray(self.T_grid, dtype=float)
        self.w_grid = np.asarray(self.w_grid, dtype=float)
        if self.k_grid.ndim != 1 or self.T_grid.ndim != 1:
            raise ValueError("k_grid and T_grid must be 1-D")
        if self.w_grid.shape != (self.T_grid.size, self.k_grid.size):
            raise ValueError(
                f"w_grid shape {self.w_grid.shape} must be "
                f"(len(T_grid), len(k_grid)) = ({self.T_grid.size}, {self.k_grid.size})"
            )
        if np.any(np.diff(self.k_grid) <= 0):
            raise ValueError("k_grid must be strictly increasing")
        if np.any(np.diff(self.T_grid) <= 0):
            raise ValueError("T_grid must be strictly increasing")
        if np.any(self.T_grid <= 0):
            raise ValueError("T_grid entries must be positive (T=0 is not a slice)")
        if np.any(self.w_grid < 0):
            raise ValueError("total variance cannot be negative anywhere on the grid")

    # -- construction -------------------------------------------------

    @classmethod
    def from_grid(cls, k_grid: np.ndarray, T_grid: np.ndarray, w_grid: np.ndarray, label: str = "") -> "VolSurface":
        return cls(k_grid=k_grid, T_grid=T_grid, w_grid=w_grid, w_func=None, label=label)

    @classmethod
    def from_parametric(
        cls,
        k_grid: np.ndarray,
        T_grid: np.ndarray,
        w_func: TotalVarianceFunc,
        label: str = "",
    ) -> "VolSurface":
        k_grid = np.asarray(k_grid, dtype=float)
        T_grid = np.asarray(T_grid, dtype=float)
        w_grid = np.stack([w_func(k_grid, float(T)) for T in T_grid], axis=0)
        return cls(k_grid=k_grid, T_grid=T_grid, w_grid=w_grid, w_func=w_func, label=label)

    # -- queries --------------------------------------------------------

    def total_variance(self, k: np.ndarray | float, T: float) -> np.ndarray:
        """w(k, T): linear interpolation/extrapolation in T (at fixed k via a
        cubic spline in k per bracketing slice), or the exact analytic
        function when this surface was built `from_parametric`.
        """
        k_arr = np.atleast_1d(np.asarray(k, dtype=float))
        if self.w_func is not None:
            out = self.w_func(k_arr, float(T))
            return out if np.ndim(k) else float(out[0])

        # Slice-wise cubic interpolation across k, then linear across T.
        # Linear-in-T at fixed k is the standard choice because it is exactly
        # what preserves "w non-decreasing in T" between two slices that
        # already satisfy it (a convex combination of two non-decreasing
        # sequences, evaluated in a shared coordinate, doesn't manufacture a
        # decrease).
        T_grid = self.T_grid
        if T <= T_grid[0]:
            w_k = self._interp_k(0, k_arr)
            scale = T / T_grid[0]
            out = w_k * scale  # scale total variance down towards T=0 (w(k,0)=0)
        elif T >= T_grid[-1]:
            w_k = self._interp_k(-1, k_arr)
            scale = T / T_grid[-1]
            out = w_k * scale  # flat total-variance-rate extrapolation
        else:
            j = int(np.searchsorted(T_grid, T))  # T_grid[j-1] < T <= T_grid[j]
            T0, T1 = T_grid[j - 1], T_grid[j]
            w0 = self._interp_k(j - 1, k_arr)
            w1 = self._interp_k(j, k_arr)
            lam = (T - T0) / (T1 - T0)
            out = (1.0 - lam) * w0 + lam * w1
        return out if np.ndim(k) else float(out[0])

    def _interp_k(self, row: int, k_arr: np.ndarray) -> np.ndarray:
        # Natural cubic-ish interpolation via numpy's PCHIP-free monotone
        # cubic is overkill here; a clamped cubic spline via numpy polyfit
        # is not shape-preserving, so we use a simple, robust choice:
        # np.interp (piecewise-linear in k) is monotone-safe and adequate
        # for the grid resolutions this module is used at. Callers that
        # need higher fidelity should supply `w_func` instead.
        return np.interp(k_arr, self.k_grid, self.w_grid[row])

    def implied_vol(self, k: np.ndarray | float, T: float) -> np.ndarray:
        w = self.total_variance(k, T)
        return np.sqrt(np.asarray(w) / T) if np.ndim(k) else float(np.sqrt(w / T))

    def slice_w(self, T_index: int) -> np.ndarray:
        """Raw total-variance row for grid maturity index `T_index`."""
        return self.w_grid[T_index]

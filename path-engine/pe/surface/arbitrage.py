"""
No-static-arbitrage checks on a VolSurface, in (k, w) coordinates.

Two conditions, both standard and both cited at the point they're used:

1. Calendar spread: total variance must be non-decreasing in T at fixed k.
   This is a model-free consequence of no-arbitrage between two European
   calendar-spread calls at the same strike (see Gatheral, "The Volatility
   Surface: A Practitioner's Guide" (2006), Ch. 3; also Roper (2010),
   "Arbitrage Free Implied Volatility Surfaces"). If w decreases with T at
   some k, you can sell the longer-dated option, buy the shorter-dated one,
   and lock in a riskless profit at that strike.

2. Butterfly / no-negative-density: the implied risk-neutral density of the
   terminal price must be non-negative everywhere, which — worked through
   Breeden-Litzenberger (the density is proportional to the second
   derivative of the call price with respect to strike) into (k, w)
   coordinates — reduces to a single closed-form condition on the total
   variance smile and its first two k-derivatives at *fixed* T:

       g(k) = (1 - k*w'(k) / (2 w(k)))^2
              - (w'(k)^2 / 4) * (1/w(k) + 1/4)
              + w''(k) / 2   >= 0   for all k

   This is the Durrleman condition, given in exactly this form in Gatheral
   & Jacquier, "Arbitrage-free SVI volatility surfaces", Quantitative
   Finance 14(1), 2014, equation (2.1) (attributed there to Durrleman's
   2003 PhD thesis). g(k) >= 0 everywhere on a slice is equivalent to the
   slice admitting a non-negative implied density; it is also, not by
   coincidence, exactly the denominator of Dupire's local-variance formula
   (see `pe.engine.localvol`) — a slice that fails this test does not just
   look wrong, it corresponds to a local volatility model with no
   well-defined (non-negative) solution at that point.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .surface import VolSurface


@dataclass
class ArbitrageReport:
    """Pass/fail plus enough detail to see exactly where a check failed."""

    ok: bool
    check: str
    violations: list[dict] = field(default_factory=list)
    worst_margin: float = 0.0  # most negative slack found (<=0 means a real violation)

    def __bool__(self) -> bool:
        return self.ok


def _finite_diff_first(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    return np.gradient(y, x)


def _finite_diff_second(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    dy = np.gradient(y, x)
    return np.gradient(dy, x)


def durrleman_g(
    k: np.ndarray,
    w: np.ndarray,
    w_prime: np.ndarray | None = None,
    w_double_prime: np.ndarray | None = None,
) -> np.ndarray:
    """The Durrleman butterfly-arbitrage function g(k) for one T-slice.

    See module docstring for the formula and citation. If the derivatives
    aren't supplied they are estimated on the given k-grid via `np.gradient`
    (2nd-order accurate central differences on a non-uniform grid); pass
    them explicitly (e.g. from an analytic SVI derivative, or a finite
    difference on a much finer grid than the pricing grid) for a cleaner
    read when the grid is coarse.
    """
    k = np.asarray(k, dtype=float)
    w = np.asarray(w, dtype=float)
    if w_prime is None:
        w_prime = _finite_diff_first(w, k)
    if w_double_prime is None:
        w_double_prime = _finite_diff_second(w, k)
    with np.errstate(divide="ignore", invalid="ignore"):
        term1 = (1.0 - k * w_prime / (2.0 * w)) ** 2
        term2 = (w_prime**2 / 4.0) * (1.0 / w + 0.25)
        g = term1 - term2 + w_double_prime / 2.0
    return g


def check_butterfly_arbitrage(
    surface: VolSurface,
    tol: float = -1e-9,
    fd_h: float = 1e-4,
) -> ArbitrageReport:
    """Check g(k) >= tol on every maturity slice of `surface`.

    `tol` is a small negative slack (not exactly 0) to absorb finite
    difference / floating point noise near a genuinely-flat boundary case;
    it is not there to paper over real violations, which run to margins
    far larger than 1e-9 in practice.

    When the surface carries an analytic `w_func` (built via
    `VolSurface.from_parametric`), the k-derivatives are evaluated by
    central finite differences on the function itself with step `fd_h`
    (much less noisy than differencing the discrete display grid);
    otherwise they come from `np.gradient` on `surface.k_grid`.
    """
    violations: list[dict] = []
    worst = np.inf
    for i, T in enumerate(surface.T_grid):
        k = surface.k_grid
        if surface.w_func is not None:
            w = surface.w_func(k, float(T))
            w_up = surface.w_func(k + fd_h, float(T))
            w_dn = surface.w_func(k - fd_h, float(T))
            w_prime = (w_up - w_dn) / (2 * fd_h)
            w_dpp = (w_up - 2 * w + w_dn) / (fd_h**2)
            g = durrleman_g(k, w, w_prime, w_dpp)
        else:
            w = surface.slice_w(i)
            g = durrleman_g(k, w)

        bad = np.where(g < tol)[0]
        worst = min(worst, float(np.min(g)))
        if bad.size:
            violations.append(
                {
                    "T": float(T),
                    "k_bad": k[bad].tolist(),
                    "g_bad": g[bad].tolist(),
                }
            )
    return ArbitrageReport(ok=(len(violations) == 0), check="butterfly", violations=violations, worst_margin=worst)


def check_calendar_arbitrage(surface: VolSurface, tol: float = -1e-10) -> ArbitrageReport:
    """Check w(k, T) is non-decreasing in T at every fixed k on the grid.

    Compares consecutive maturity slices directly on `surface.k_grid` (no
    interpolation needed since both slices already share that grid) —
    a real calendar violation shows up as `w_grid[i+1] < w_grid[i]` at some
    column, comfortably outside `tol`.
    """
    violations: list[dict] = []
    worst = np.inf
    for i in range(len(surface.T_grid) - 1):
        w0 = surface.slice_w(i)
        w1 = surface.slice_w(i + 1)
        diff = w1 - w0  # must be >= 0
        worst = min(worst, float(np.min(diff)))
        bad = np.where(diff < tol)[0]
        if bad.size:
            violations.append(
                {
                    "T_from": float(surface.T_grid[i]),
                    "T_to": float(surface.T_grid[i + 1]),
                    "k_bad": surface.k_grid[bad].tolist(),
                    "delta_w_bad": diff[bad].tolist(),
                }
            )
    return ArbitrageReport(ok=(len(violations) == 0), check="calendar", violations=violations, worst_margin=worst)

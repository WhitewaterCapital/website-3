"""
Raw SVI (Stochastic Volatility Inspired) parameterization, used here purely
as a synthetic, arbitrage-free-by-construction surface generator for tests
and for exercising local-vol calibration — NOT as a chain-fitting routine
(there is no chain to fit to in this environment; see path-engine/README.md).

Raw SVI (Gatheral, "A parsimonious arbitrage-free implied volatility
parameterization with application to the valuation of volatility
derivatives", 2004 presentation; formalized with arbitrage conditions in
Gatheral & Jacquier, "Arbitrage-free SVI volatility surfaces", Quantitative
Finance 14(1), 2014):

    w(k) = a + b * ( rho * (k - m) + sqrt((k - m)^2 + sigma^2) )

with a in R, b >= 0, |rho| < 1, m in R, sigma > 0. Gatheral & Jacquier give
closed-form *sufficient* parameter conditions for a single slice to be free
of butterfly arbitrage (their Section 3.2.1) — we deliberately do not lean
on a from-memory restatement of that inequality as a proof. Instead
`svi_term_structure_surface` gets calendar-arbitrage-freeness for free by
construction (see its docstring), and any butterfly claim about a specific
parameter choice is settled by actually running
`pe.surface.arbitrage.check_butterfly_arbitrage` against it — the tests do
exactly that rather than asserting a remembered constant.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .surface import VolSurface


@dataclass(frozen=True)
class SVIParams:
    a: float
    b: float
    rho: float
    m: float
    sigma: float

    def __post_init__(self) -> None:
        if self.b < 0:
            raise ValueError("SVI requires b >= 0")
        if not (-1.0 < self.rho < 1.0):
            raise ValueError("SVI requires |rho| < 1")
        if self.sigma <= 0:
            raise ValueError("SVI requires sigma > 0")


def svi_total_variance(k: np.ndarray, params: SVIParams) -> np.ndarray:
    """w(k) under raw SVI, vectorized over k."""
    k = np.asarray(k, dtype=float)
    return params.a + params.b * (params.rho * (k - params.m) + np.sqrt((k - params.m) ** 2 + params.sigma**2))


def svi_slice_surface(k_grid: np.ndarray, T: float, params: SVIParams, label: str = "SVI slice") -> VolSurface:
    """A one-maturity VolSurface from a single SVI slice (mostly for tests/plots)."""
    k_grid = np.asarray(k_grid, dtype=float)
    w = svi_total_variance(k_grid, params)
    return VolSurface.from_grid(k_grid, np.array([T]), w[None, :], label=label)


def svi_term_structure_surface(
    k_grid: np.ndarray,
    T_grid: np.ndarray,
    base_params: SVIParams,
    atm_total_variance: np.ndarray,
    label: str = "SVI term structure",
) -> VolSurface:
    """A multi-maturity SVI surface that is calendar-arbitrage-free **by construction**.

    Every slice reuses `base_params`' smile *shape* — its wings relative to
    its own at-the-money value — and only the ATM total variance level
    (`atm_total_variance[i]`, i.e. theta(T_i) = w(k=0, T_i)) is allowed to
    vary across maturities:

        w(k, T_i) = [w_base(k) - w_base(0)] + atm_total_variance[i]

    Because the bracketed wing term does not depend on T, for any two
    maturities T_i < T_j:

        w(k, T_j) - w(k, T_i) = atm_total_variance[j] - atm_total_variance[i]

    which is the *same, k-independent* quantity everywhere. Requiring
    `atm_total_variance` to be strictly increasing therefore makes
    w(k, T) strictly increasing in T at *every* k simultaneously — the
    calendar-spread condition holds exactly, not approximately, and not
    merely for the k's on this grid. This is a mathematical property of
    the construction, not a "mild parameter constraint" being hoped for.

    Butterfly-freeness of each shifted slice is a separate question (the
    shift changes the 1/w terms in the Durrleman condition) and is left to
    `pe.surface.arbitrage.check_butterfly_arbitrage` to verify for the
    concrete parameters you pick — see the surface tests, which check both
    conditions on the surface this function returns rather than assuming
    either.
    """
    T_grid = np.asarray(T_grid, dtype=float)
    atm_total_variance = np.asarray(atm_total_variance, dtype=float)
    if T_grid.shape != atm_total_variance.shape:
        raise ValueError("atm_total_variance must have one entry per T_grid maturity")
    if np.any(np.diff(atm_total_variance) <= 0):
        raise ValueError(
            "atm_total_variance (theta(T), the ATM total variance term structure) "
            "must be strictly increasing for a calendar-arbitrage-free surface"
        )
    k_grid = np.asarray(k_grid, dtype=float)
    w_shape = svi_total_variance(k_grid, base_params)
    atm_shape = float(svi_total_variance(np.array([0.0]), base_params)[0])
    wings = w_shape - atm_shape
    rows = [wings + theta for theta in atm_total_variance]
    w_grid = np.stack(rows, axis=0)
    return VolSurface.from_grid(k_grid, T_grid, w_grid, label=label)

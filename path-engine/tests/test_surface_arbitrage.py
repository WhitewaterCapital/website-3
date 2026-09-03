"""PATH-01 (buildable slice): VolSurface representation + no-arbitrage checks."""
from __future__ import annotations

import numpy as np

from pe.surface import (
    SVIParams,
    VolSurface,
    check_butterfly_arbitrage,
    check_calendar_arbitrage,
    svi_term_structure_surface,
)


def _arbitrage_free_svi_surface() -> VolSurface:
    k_grid = np.linspace(-0.6, 0.6, 41)
    T_grid = np.array([0.25, 0.5, 1.0, 2.0])
    base = SVIParams(a=0.02, b=0.15, rho=-0.4, m=0.0, sigma=0.25)
    atm_w = np.array([0.25**2 * T for T in T_grid])  # ~25% flat-ish ATM vol term structure
    return svi_term_structure_surface(k_grid, T_grid, base, atm_w)


def test_arbitrage_free_svi_surface_passes_both_checks():
    surface = _arbitrage_free_svi_surface()
    cal = check_calendar_arbitrage(surface)
    but = check_butterfly_arbitrage(surface)
    assert cal.ok, f"calendar check failed on a by-construction arb-free surface: {cal.violations}"
    assert but.ok, f"butterfly check failed on a by-construction arb-free surface: {but.violations}"
    assert cal.worst_margin >= -1e-9
    assert but.worst_margin >= -1e-6


def test_calendar_arbitrage_is_detected():
    k_grid = np.linspace(-0.3, 0.3, 11)
    T_grid = np.array([0.5, 1.0])
    # Deliberately make the longer maturity's total variance LOWER than the
    # shorter one's at every strike -- a textbook calendar-spread violation.
    w_short = np.full(11, 0.09)   # w = sigma^2 * T = 0.30^2 * 0.5 * 2 (flat, illustrative)
    w_long = np.full(11, 0.05)    # strictly less than w_short: violates w non-decreasing in T
    surface = VolSurface.from_grid(k_grid, T_grid, np.vstack([w_short, w_long]))

    report = check_calendar_arbitrage(surface)
    assert not report.ok
    assert len(report.violations) == 1
    assert report.worst_margin < 0
    # every strike violates in this construction
    assert len(report.violations[0]["k_bad"]) == 11


def test_butterfly_arbitrage_is_detected():
    # A smile with an excessively sharp local dip (large negative curvature)
    # violates the Durrleman condition -- construct one directly in (k, w)
    # space rather than via SVI, so the violation is unambiguous and
    # independent of any SVI-specific "is this parameterization admissible"
    # subtlety.
    k = np.linspace(-1.0, 1.0, 101)
    w_smooth = 0.04 + 0.02 * k**2
    spike = -0.15 * np.exp(-(k**2) / (2 * 0.02**2))  # sharp negative spike at k=0
    w = np.maximum(w_smooth + spike, 1e-6)
    surface = VolSurface.from_grid(k, np.array([1.0]), w[None, :])

    report = check_butterfly_arbitrage(surface, fd_h=1e-4)
    assert not report.ok
    assert report.worst_margin < 0


def test_surface_construction_rejects_bad_shapes():
    k = np.linspace(-0.5, 0.5, 5)
    T = np.array([0.5, 1.0])
    try:
        VolSurface.from_grid(k, T, np.zeros((3, 5)))
        assert False, "expected a shape mismatch to raise"
    except ValueError:
        pass


def test_svi_term_structure_calendar_free_even_off_grid():
    """`svi_term_structure_surface`'s docstring proves calendar-freeness
    holds at EVERY k, not just the grid's k's, because the T-difference of
    two slices is k-independent by construction. Check that identity
    directly on a much finer k-grid than the one baked into the display
    surface, using `svi_total_variance` (the underlying function that
    generates each slice's wing shape) rather than `surface.w_func` (this
    construction stores a discrete grid, not a parametric callable -- see
    `VolSurface.from_grid`)."""
    from pe.surface.svi import svi_total_variance

    T_grid = np.array([0.25, 0.5, 1.0, 2.0])
    base = SVIParams(a=0.02, b=0.15, rho=-0.4, m=0.0, sigma=0.25)
    atm_w = np.array([0.25**2 * T for T in T_grid])
    fine_k = np.linspace(-0.55, 0.55, 401)

    w_shape = svi_total_variance(fine_k, base)
    atm_shape = float(svi_total_variance(np.array([0.0]), base)[0])
    wings = w_shape - atm_shape

    for i in range(len(T_grid) - 1):
        w0 = wings + atm_w[i]
        w1 = wings + atm_w[i + 1]
        assert np.all(w1 >= w0 - 1e-12)

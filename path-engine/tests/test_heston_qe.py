"""PATH-02c: Andersen's QE scheme for the Heston variance process never
produces a negative variance, contrasted with a plain (documented-as-wrong)
Euler discretization, which does -- under Feller-violating parameters
that are entirely typical of equity-index calibrations."""
from __future__ import annotations

import numpy as np

from pe.engine.heston import (
    HestonParams,
    simulate_heston_qe_paths,
    simulate_qe_variance,
    simulate_variance_euler_naive,
)

# Deliberately Feller-violating: 2*kappa*theta = 2*1.5*0.04 = 0.12 << xi^2 = 0.36
FELLER_VIOLATING = HestonParams(v0=0.04, kappa=1.5, theta=0.04, xi=0.6, rho=-0.7)


def test_feller_condition_is_indeed_violated_by_the_test_parameters():
    assert FELLER_VIOLATING.feller_ratio() < 1.0


def test_qe_variance_never_goes_negative_across_many_seeds():
    for seed in range(30):
        _, v_paths = simulate_qe_variance(FELLER_VIOLATING, T=1.0, n_steps=252, n_paths=200, seed=seed)
        assert np.all(v_paths >= 0.0), f"QE produced a negative variance at seed={seed}: min={v_paths.min()}"


def test_naive_euler_variance_does_go_negative_under_the_same_parameters():
    """The documented-as-wrong comparison: same parameters, same horizon,
    plain Euler on sqrt(v) -- this SHOULD go negative, proving the QE
    scheme's non-negativity isn't just "these parameters happen to be
    tame"."""
    went_negative = False
    for seed in range(30):
        _, v_paths = simulate_variance_euler_naive(FELLER_VIOLATING, T=1.0, n_steps=252, n_paths=200, seed=seed)
        if np.any(v_paths < 0.0):
            went_negative = True
            break
    assert went_negative, "expected naive Euler to produce at least one negative variance across 30 seeds"


def test_qe_reverts_to_theta_on_average():
    """Basic sanity: the QE-simulated variance's long-run sample mean
    should sit near theta (mean-reversion target), well within a generous
    band given the fairly high vol-of-vol -- this is not a precision test,
    just a check that the scheme isn't producing nonsense (e.g. exploding
    or collapsing to zero)."""
    _, v_paths = simulate_qe_variance(FELLER_VIOLATING, T=5.0, n_steps=252 * 5, n_paths=5000, seed=99)
    terminal_mean = float(np.mean(v_paths[:, -1]))
    assert 0.5 * FELLER_VIOLATING.theta < terminal_mean < 2.0 * FELLER_VIOLATING.theta


def test_full_heston_qe_paths_are_finite_and_positive():
    times, S_paths, v_paths, info = simulate_heston_qe_paths(
        S0=100.0, r=0.02, q=0.0, params=FELLER_VIOLATING, T=1.0, n_steps=100, n_paths=5000, seed=7
    )
    assert np.all(np.isfinite(S_paths))
    assert np.all(S_paths > 0.0)
    assert np.all(v_paths >= 0.0)
    assert info["variance_scheme"] == "QE (Andersen 2008)"


def test_heston_qe_terminal_price_is_a_risk_neutral_martingale_at_r_equals_q():
    """With r == q, E[S_T] should equal S0 within Monte Carlo error -- a
    basic no-drift-leak sanity check on the QE log-price update's K0..K4
    coefficients (an error there commonly breaks exactly this identity)."""
    r = q = 0.03
    times, S_paths, v_paths, info = simulate_heston_qe_paths(
        S0=100.0, r=r, q=q, params=FELLER_VIOLATING, T=1.0, n_steps=100, n_paths=400_000, seed=8, antithetic=True
    )
    S_T = S_paths[:, -1]
    n = S_T.shape[0] // 2
    pair_avg = 0.5 * (S_T[:n] + S_T[n:])
    mean = float(np.mean(pair_avg))
    se = float(np.std(pair_avg, ddof=1) / np.sqrt(n))
    assert abs(mean - 100.0) < 4.0 * se, f"E[S_T]={mean:.4f} +/- {se:.4f}, expected ~100.0"

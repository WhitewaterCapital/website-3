"""Diffusion mechanics and its stability certificate.

Two independent lines of evidence, per the spec ("numerically verified to keep
the operator stable ... via eigenvalues or empirical convergence"):

  1. Eigenvalues: the symmetric normalized adjacency built from any
     non-negative weighted graph has eigenvalues in [-1, 1] (textbook spectral
     graph theory) -- checked directly.
  2. Empirical convergence: the actual (signed) damped-diffusion iteration's
     step-to-step changes shrink geometrically, bounded above by `alpha`,
     for every alpha in [0, 1) -- checked directly, including on a graph with
     NEGATIVE (anti-correlated) edges, where the eigenvalue argument for the
     non-negative Laplacian doesn't directly apply.
"""

from __future__ import annotations

import numpy as np
import pytest
from scipy import sparse

from ge.config import DiffusionConfig
from ge.graph.construct import GraphConfig, build_graph
from ge.graph.diffusion import (
    diffuse,
    diffuse_with_trace,
    normalized_laplacian,
    row_normalize_signed,
)
from ge.synthetic import make_universe, simulate_returns


def _random_signed_graph(n=25, density=0.2, seed=0):
    rng = np.random.default_rng(seed)
    w = rng.normal(size=(n, n))
    mask = rng.random((n, n)) < density
    mask = np.triu(mask, 1)
    mask = mask | mask.T
    w = w * mask
    w = (w + w.T) / 2
    np.fill_diagonal(w, 0.0)
    return w


def test_normalized_adjacency_eigenvalues_bounded():
    w = _random_signed_graph(seed=1)
    _, a_sym = normalized_laplacian(w)
    eig = np.linalg.eigvalsh(a_sym)
    assert eig.max() <= 1.0 + 1e-8
    assert eig.min() >= -1.0 - 1e-8


def test_normalized_laplacian_eigenvalues_in_0_2():
    w = np.abs(_random_signed_graph(seed=2))  # non-negative, textbook case
    lap, _ = normalized_laplacian(w)
    eig = np.linalg.eigvalsh(lap)
    assert eig.min() >= -1e-8
    assert eig.max() <= 2.0 + 1e-8


def test_normalized_laplacian_handles_isolated_node():
    w = np.zeros((3, 3))
    w[0, 1] = w[1, 0] = 1.0  # node 2 isolated
    lap, a_sym = normalized_laplacian(w)
    assert np.isfinite(lap).all()
    assert a_sym[2, :].sum() == 0.0 and a_sym[:, 2].sum() == 0.0


def test_row_normalize_signed_rows_have_unit_l1_norm():
    w = _random_signed_graph(seed=3)
    p = row_normalize_signed(w)
    row_abs_sum = np.abs(p).sum(axis=1)
    nonzero_rows = np.abs(w).sum(axis=1) > 0
    np.testing.assert_allclose(row_abs_sum[nonzero_rows], 1.0)


def test_row_normalize_signed_isolated_row_is_zero():
    w = np.zeros((3, 3))
    w[0, 1] = 1.0
    p = row_normalize_signed(w)
    assert np.all(p[2] == 0.0)


def test_diffuse_alpha_out_of_range_raises():
    w = _random_signed_graph(n=5, seed=4)
    sig = np.arange(5.0)
    with pytest.raises(ValueError):
        diffuse(sig, w, DiffusionConfig(alpha=1.0, n_iters=5))
    with pytest.raises(ValueError):
        diffuse(sig, w, DiffusionConfig(alpha=-0.1, n_iters=5))


def test_diffuse_zero_diagonal_means_no_direct_self_influence():
    # A node's own signal must not enter its own diffused value on the FIRST
    # hop (S0 = P @ signal, and P has a zero diagonal by construction). A
    # >=2-hop echo through a neighbour that is itself connected back (as in
    # this 3-node path graph) is expected and documented -- checked here with
    # n_iters=0, i.e. the result IS S0, isolating the one-hop guarantee.
    w = np.array(
        [
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
        ]
    )
    sig_a = np.array([100.0, 0.0, 0.0])
    sig_b = np.array([999.0, 0.0, 0.0])  # change node 0's OWN signal only
    cfg = DiffusionConfig(alpha=0.5, n_iters=0)
    out_a = diffuse(sig_a, w, cfg)
    out_b = diffuse(sig_b, w, cfg)
    assert out_a[0] == pytest.approx(out_b[0])  # node 0's own S0 unaffected by its own signal
    assert out_a[0] == pytest.approx(0.0)  # node 1 (its only neighbour) had signal 0


def test_diffuse_two_hop_echo_through_a_connected_neighbour_is_expected():
    # Documents the >=2-hop case referenced above: after enough iterations,
    # node 0's diffused value DOES depend on its own signal, via node 1.
    w = np.array(
        [
            [0.0, 1.0, 0.0],
            [1.0, 0.0, 1.0],
            [0.0, 1.0, 0.0],
        ]
    )
    sig_a = np.array([100.0, 0.0, 0.0])
    sig_b = np.array([999.0, 0.0, 0.0])
    cfg = DiffusionConfig(alpha=0.5, n_iters=5)
    out_a = diffuse(sig_a, w, cfg)
    out_b = diffuse(sig_b, w, cfg)
    assert out_a[0] != pytest.approx(out_b[0])


def test_diffuse_matches_hand_computation_one_hop():
    # Two nodes, one edge, weight 1 -> P is the identity swap. S0 = P @ signal.
    w = np.array([[0.0, 1.0], [1.0, 0.0]])
    sig = np.array([2.0, 5.0])
    cfg = DiffusionConfig(alpha=0.0, n_iters=3)  # alpha=0 => result is always S0
    out = diffuse(sig, w, cfg)
    np.testing.assert_allclose(out, np.array([5.0, 2.0]))


def test_diffuse_uses_sparse_matmul_and_matches_dense_reference():
    w = _random_signed_graph(n=12, seed=5)
    sig = np.random.default_rng(6).normal(size=12)
    cfg = DiffusionConfig(alpha=0.6, n_iters=20)
    out = diffuse(sig, w, cfg)

    # Reference: identical recursion computed with dense numpy only.
    p = row_normalize_signed(w)
    s0 = p @ sig
    s = s0.copy()
    for _ in range(cfg.n_iters):
        s = cfg.alpha * (p @ s) + (1 - cfg.alpha) * s0
    np.testing.assert_allclose(out, s, atol=1e-10)


@pytest.mark.parametrize("alpha", [0.1, 0.3, 0.6, 0.9, 0.99])
def test_diffusion_converges_and_ratio_bounded_by_alpha(alpha):
    tickers, sector_of = make_universe(4, 6)
    rets = simulate_returns(tickers, sector_of, 150, seed=7)
    graph = build_graph(rets.tail(60), sector_of, GraphConfig(top_k=8))
    sig = np.random.default_rng(8).normal(size=len(tickers))

    trace = diffuse_with_trace(sig, graph.sparse_weights, DiffusionConfig(alpha=alpha, n_iters=60))
    assert trace.deltas[-1] < trace.deltas[0]  # net convergence
    assert trace.deltas[-1] < 1e-4  # effectively converged within the fixed iter budget
    # every observed step ratio must respect the alpha contraction bound
    assert all(r <= alpha + 1e-6 for r in trace.ratios)


def test_diffusion_default_config_converges_tightly_within_fixed_iters():
    tickers, sector_of = make_universe(4, 5)
    rets = simulate_returns(tickers, sector_of, 150, seed=9)
    graph = build_graph(rets.tail(60), sector_of, GraphConfig())
    sig = np.random.default_rng(10).normal(size=len(tickers))
    trace = diffuse_with_trace(sig, graph.sparse_weights, DiffusionConfig())
    # DIFFUSION_ALPHA=0.60, DIFFUSION_ITERS=30 -> upper bound on remaining
    # error is roughly 0.60**30 ~ 2e-7 of the initial step.
    assert trace.deltas[-1] < 1e-5

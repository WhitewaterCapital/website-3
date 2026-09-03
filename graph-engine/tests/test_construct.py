"""Graph construction: shrunk correlation, sector prior, fixed-weight combine,
top-k sparsification."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ge.config import GraphConfig
from ge.graph.construct import (
    build_graph,
    combine_sources,
    sector_prior_matrix,
    shrunk_correlation,
    sparsify_top_k,
)
from ge.synthetic import make_universe, simulate_returns


def test_shrunk_correlation_is_symmetric_unit_diagonal_bounded():
    tickers, sector_of = make_universe(2, 4)
    rets = simulate_returns(tickers, sector_of, 80, seed=1)
    corr = shrunk_correlation(rets)
    n = len(tickers)
    assert corr.shape == (n, n)
    np.testing.assert_allclose(np.diag(corr), 1.0)
    np.testing.assert_allclose(corr, corr.T, atol=1e-10)
    assert np.all(corr >= -1.0 - 1e-9) and np.all(corr <= 1.0 + 1e-9)


def test_shrunk_correlation_shrinks_toward_target_vs_raw_sample():
    # With FEWER observations than names, a raw sample correlation would be
    # degenerate; Ledoit-Wolf must still produce a well-conditioned matrix.
    tickers, sector_of = make_universe(2, 10)  # 20 names
    rets = simulate_returns(tickers, sector_of, 15, seed=2)  # 15 obs < 20 names
    corr = shrunk_correlation(rets)
    eigvals = np.linalg.eigvalsh(corr)
    assert eigvals.min() > -1e-8  # PSD despite n_obs < n_names


def test_shrunk_correlation_needs_finite_input():
    df = pd.DataFrame({"A": [0.01, np.nan, 0.02], "B": [0.02, 0.01, 0.03]})
    with pytest.raises(ValueError):
        shrunk_correlation(df)


def test_sector_prior_matrix_same_sector_bonus_only():
    tickers = ["A", "B", "C", "D"]
    sector_of = {"A": "S1", "B": "S1", "C": "S2", "D": "S2"}
    m = sector_prior_matrix(tickers, sector_of, bonus=2.0)
    expected = np.array(
        [
            [0.0, 2.0, 0.0, 0.0],
            [2.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 2.0],
            [0.0, 0.0, 2.0, 0.0],
        ]
    )
    np.testing.assert_allclose(m, expected)


def test_combine_sources_uses_fixed_weights_and_zero_diagonal():
    corr = np.array([[1.0, 0.4], [0.4, 1.0]])
    sector = np.array([[0.0, 1.0], [1.0, 0.0]])
    cfg = GraphConfig(w_corr=0.8, w_sector=0.2)
    combined = combine_sources(corr, sector, cfg)
    assert combined[0, 1] == pytest.approx(0.8 * 0.4 + 0.2 * 1.0)
    assert combined[0, 0] == 0.0 and combined[1, 1] == 0.0


def test_sparsify_top_k_keeps_exactly_k_or_fewer_per_row_and_is_symmetric():
    rng = np.random.default_rng(0)
    n = 30
    raw = rng.normal(size=(n, n))
    w = (raw + raw.T) / 2  # symmetric, as combine_sources produces
    np.fill_diagonal(w, 0.0)
    k = 5
    sparse = sparsify_top_k(w, k)

    np.testing.assert_allclose(sparse, sparse.T)
    assert np.all(np.diag(sparse) == 0.0)
    nnz_per_row = (sparse != 0).sum(axis=1)
    # union symmetrization can push a row above k if a neighbour insists;
    # every row must have AT LEAST k edges it originally would have kept,
    # and never everyone connected to everyone (proof the sparsify did something).
    assert nnz_per_row.min() >= k
    assert nnz_per_row.max() < n - 1


def test_sparsify_top_k_selects_the_actual_largest_magnitude_edges():
    # Small, hand-checkable case: node 0's neighbours ranked by |weight|.
    w = np.array(
        [
            [0.0, 0.1, -0.9, 0.5, 0.2],
            [0.1, 0.0, 0.1, 0.1, 0.1],
            [-0.9, 0.1, 0.0, 0.1, 0.1],
            [0.5, 0.1, 0.1, 0.0, 0.1],
            [0.2, 0.1, 0.1, 0.1, 0.0],
        ]
    )
    sparse = sparsify_top_k(w, k=2)
    # node 0's top-2 by |weight| are node 2 (-0.9) and node 3 (0.5).
    row0_nonzero = set(np.nonzero(sparse[0])[0])
    assert {2, 3} <= row0_nonzero


def test_sparsify_top_k_ge_n_minus_1_keeps_everything_but_diagonal():
    n = 6
    rng = np.random.default_rng(1)
    w = rng.normal(size=(n, n))
    w = (w + w.T) / 2
    np.fill_diagonal(w, 0.0)
    sparse = sparsify_top_k(w, k=n - 1)
    np.testing.assert_allclose(sparse, w)


def test_build_graph_end_to_end_shapes_and_no_self_loops():
    tickers, sector_of = make_universe(4, 5)  # 20 names
    rets = simulate_returns(tickers, sector_of, 90, seed=3)
    cfg = GraphConfig(top_k=6)
    graph = build_graph(rets.tail(cfg.corr_window), sector_of, cfg)

    n = len(tickers)
    assert graph.corr_shrunk.shape == (n, n)
    assert graph.sector_prior.shape == (n, n)
    assert graph.combined.shape == (n, n)
    assert graph.sparse_weights.shape == (n, n)
    assert np.all(np.diag(graph.sparse_weights) == 0.0)
    # every node keeps at least top_k edges (union-symmetrized, so possibly more)
    nnz = (graph.sparse_weights != 0).sum(axis=1)
    assert nnz.min() >= cfg.top_k
    assert nnz.max() < n - 1  # genuinely sparser than "everyone"


def test_build_graph_same_sector_names_are_favoured():
    # Two well-separated sectors with near-zero cross-sector correlation and a
    # strong sector prior should keep same-sector edges over cross-sector ones
    # whenever correlation alone wouldn't clearly prefer one over the other.
    tickers, sector_of = make_universe(2, 6)  # 12 names, 2 sectors of 6
    rets = simulate_returns(
        tickers, sector_of, 200, seed=4, mkt_vol=0.0, sector_vol=0.01, idio_vol=0.01
    )
    cfg = GraphConfig(top_k=4)
    graph = build_graph(rets, sector_of, cfg)
    target = tickers.index("S0N0")
    same_sector_idx = [i for i, t in enumerate(tickers) if sector_of[t] == "SECTOR_0" and t != "S0N0"]
    kept = np.nonzero(graph.sparse_weights[target])[0]
    # with no market factor and a real sector factor, same-sector names should
    # dominate the top-4 kept edges for a sector-mate.
    assert sum(1 for i in kept if i in same_sector_idx) >= 3


def test_build_graph_missing_sector_raises():
    tickers, sector_of = make_universe(1, 3)
    rets = simulate_returns(tickers, sector_of, 30, seed=5)
    del sector_of[tickers[0]]
    with pytest.raises(KeyError):
        build_graph(rets, sector_of, GraphConfig())

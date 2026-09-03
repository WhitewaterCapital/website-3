"""Build the relationship graph between names.

Two independent edge SOURCES, each stored as its own (n x n) matrix so a
contribution is always inspectable and attributable:

  1. `corr_shrunk`   — rolling return correlation, shrunk toward a structured
                        target via Ledoit-Wolf (sklearn.covariance.LedoitWolf).
                        SIGNED: two names that move opposite to each other are
                        a real edge too (that's a pairs-trade candidate), not a
                        zero.
  2. `sector_prior`  — a trivial structural prior: `SECTOR_PRIOR_BONUS` on any
                        (i, j) pair in the same sector, 0 otherwise. This is
                        the "structural" edge source referenced in the module
                        docstring below — see README for why real
                        holdings-weighted / supply-chain / text-similarity
                        edges are NOT implemented here.

The two sources are combined with FIXED, documented weights (`W_CORR`,
`W_SECTOR` in `config.py`) — never fit. A 60-day correlation on N names is
noisy; letting an optimizer pick how much to trust it vs. a coarse sector prior
would just be overfitting the combination step instead of the correlation
step.

Why Ledoit-Wolf at all: a raw sample correlation matrix on more names than
roughly `corr_window` observations is rank-deficient / numerically unstable,
and even well inside that regime sample correlation is a noisy estimate of the
true (slowly-varying) co-movement structure. Ledoit-Wolf shrinks the sample
covariance toward a structured target (a scaled identity) with an analytically
optimal shrinkage intensity — no manual tuning, no reimplementing a
well-studied estimator by hand.

Why sparsify: a dense correlation matrix on real equities is dominated by one
thing — the market factor. Every name is weakly positively correlated with
every other name through the tape, so a fully-connected diffusion mostly just
diffuses each name toward the cross-sectional average (the market return),
which is already captured by simpler means. Keeping only the strongest
TOP_K_EDGES per node forces the graph to encode *specific* relationships
(sector-mates, close economic substitutes/complements, historical pairs) that
carry more information than "the market."
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.covariance import LedoitWolf

from ..config import GraphConfig


@dataclass(frozen=True)
class GraphSources:
    """Every stage of graph construction, kept around for inspection."""

    tickers: list[str]
    corr_shrunk: np.ndarray     # (n,n) Ledoit-Wolf-shrunk correlation, signed
    sector_prior: np.ndarray    # (n,n) same-sector indicator * bonus
    combined: np.ndarray        # (n,n) fixed-weight combination, pre-sparsify
    sparse_weights: np.ndarray  # (n,n) combined, top-k-per-node sparsified


def shrunk_correlation(returns: pd.DataFrame) -> np.ndarray:
    """Ledoit-Wolf-shrunk correlation matrix of `returns` (rows=time,
    cols=names). Signed: -1..1, 1.0 on the diagonal."""
    x = returns.to_numpy(dtype=float)
    if np.any(~np.isfinite(x)):
        raise ValueError("returns must be finite (drop/fill NaNs before calling)")
    n_obs, n_names = x.shape
    if n_obs < 2:
        raise ValueError("need at least 2 observations to estimate a covariance")
    cov = LedoitWolf().fit(x).covariance_
    d = np.sqrt(np.clip(np.diag(cov), 1e-18, None))
    corr = cov / np.outer(d, d)
    corr = np.clip(corr, -1.0, 1.0)
    np.fill_diagonal(corr, 1.0)
    # Numerical symmetry (should already hold; guards float round-trip noise).
    return (corr + corr.T) / 2.0


def sector_prior_matrix(
    tickers: list[str], sector_of: dict[str, str], bonus: float
) -> np.ndarray:
    """1 (* bonus) for same-sector off-diagonal pairs, 0 elsewhere."""
    n = len(tickers)
    sectors = np.array([sector_of[t] for t in tickers], dtype=object)
    same = sectors[:, None] == sectors[None, :]
    m = same.astype(float) * bonus
    np.fill_diagonal(m, 0.0)
    return m


def combine_sources(
    corr_shrunk: np.ndarray, sector_prior: np.ndarray, cfg: GraphConfig
) -> np.ndarray:
    """Fixed-weight linear combination of the two edge sources. Signed
    (correlation keeps its sign; the sector prior is non-negative)."""
    combined = cfg.w_corr * corr_shrunk + cfg.w_sector * sector_prior
    np.fill_diagonal(combined, 0.0)
    return combined


def sparsify_top_k(weights: np.ndarray, k: int) -> np.ndarray:
    """Keep, per node, the `k` edges with the largest |weight|; symmetrize by
    UNION (an edge survives if either endpoint ranks it in its own top-k) —
    `weights` is symmetric going in, so the surviving value is unambiguous."""
    n = weights.shape[0]
    if k >= n - 1:
        mask = ~np.eye(n, dtype=bool)
        return weights * mask

    mask = np.zeros((n, n), dtype=bool)
    absw = np.abs(weights)
    for i in range(n):
        row = absw[i].copy()
        row[i] = -np.inf
        top_idx = np.argpartition(row, -k)[-k:]
        top_idx = top_idx[np.isfinite(row[top_idx]) & (row[top_idx] > 0)]
        mask[i, top_idx] = True
    mask = mask | mask.T
    np.fill_diagonal(mask, False)
    return weights * mask


def build_graph(
    returns: pd.DataFrame,
    sector_of: dict[str, str],
    cfg: GraphConfig = GraphConfig(),
) -> GraphSources:
    """Full construction pipeline for one as-of date's trailing return window.

    `returns` — DAILY returns, rows = trailing `cfg.corr_window` (or fewer at
    the start of history) bars, columns = tickers. `sector_of` — ticker ->
    sector label, must cover every column.
    """
    tickers = list(returns.columns)
    missing = [t for t in tickers if t not in sector_of]
    if missing:
        raise KeyError(f"sector_of missing tickers: {missing}")

    corr = shrunk_correlation(returns)
    sector = sector_prior_matrix(tickers, sector_of, cfg.sector_bonus)
    combined = combine_sources(corr, sector, cfg)
    sparse = sparsify_top_k(combined, cfg.top_k)
    return GraphSources(
        tickers=tickers,
        corr_shrunk=corr,
        sector_prior=sector,
        combined=combined,
        sparse_weights=sparse,
    )

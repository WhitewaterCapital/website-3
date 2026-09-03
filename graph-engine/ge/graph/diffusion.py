"""Spread each name's signal across the graph.

Two related but distinct objects live here:

1. `normalized_laplacian` — the classic, NON-negative-weight normalized graph
   Laplacian `L = I - D^{-1/2} A D^{-1/2}` built from the graph's edge
   *magnitudes* (`|sparse_weights|`). Its only job is a stability certificate:
   for any non-negative weighted graph, the symmetric normalized adjacency
   `A_sym = D^{-1/2} A D^{-1/2}` has eigenvalues confined to `[-1, 1]`
   (equivalently `L`'s eigenvalues sit in `[0, 2]`) — this is a textbook
   spectral-graph-theory fact, and it is what makes the diffusion below
   provably stable rather than "stable on the graphs we happened to try."
   `tests/test_diffusion.py::test_normalized_adjacency_eigenvalues_bounded`
   checks it directly on real (synthetic) graphs.

2. `diffuse` — the actual signal propagation. We deliberately do NOT diffuse
   with the (non-negative) symmetric-normalized adjacency above, because doing
   so would erase sign information: an anti-correlated neighbour running up
   should imply *this* name should have run down, not up. Instead we build a
   SIGNED, row-normalized operator `P` (`row_normalize_signed`, normalized by
   the L1 norm of each row so `sum_j |P[i,j]| == 1`) and iterate the
   personalized-diffusion recursion

        S_0     = P @ signal                       (one-hop neighbour view)
        S_{t+1} = alpha * (P @ S_t) + (1-alpha) * S_0

   entirely via SPARSE matrix-vector products (`scipy.sparse`), never by
   inverting `(I - alpha*P)` — inversion is O(n^3) and, more importantly,
   hides the "how many hops out did this information travel" structure that
   the iterative form makes explicit and cheap to reason about at scale.

   Stability of the iteration does NOT depend on knowing this operator's
   eigenvalues (P is not symmetric in general, so `normalized_laplacian`'s
   spectral argument doesn't directly apply to it). Instead it follows from a
   simpler, operator-norm argument that holds for ANY signed graph:
   `||P||_inf = max_i sum_j |P[i,j]| = 1` by construction, so
   `||alpha*P||_inf = alpha < 1`, which makes the recursion a contraction
   mapping in the infinity norm for every `alpha` in `[0, 1)` — Banach fixed
   point, no eigenvalue computation required. `test_diffusion.py` verifies
   this empirically: the iterate deltas shrink geometrically, and the
   per-step ratio stays bounded ABOVE by `alpha` (the true asymptotic rate is
   the spectral radius of `alpha*P`, which is <= alpha but often smaller in
   practice, as seen on the synthetic graphs in the tests).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import sparse

from ..config import DiffusionConfig


def normalized_laplacian(weights: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Symmetric normalized Laplacian and adjacency of a NON-negative
    weighted graph. `weights` may be signed (we take |weights|) since this is
    only used for the stability certificate on graph structure, not for
    signal propagation. Isolated nodes (degree 0) get a 0 row/col (standard
    convention) rather than dividing by zero."""
    a = np.abs(weights)
    deg = a.sum(axis=1)
    with np.errstate(divide="ignore"):
        d_inv_sqrt = np.where(deg > 0, 1.0 / np.sqrt(deg), 0.0)
    a_sym = (d_inv_sqrt[:, None] * a) * d_inv_sqrt[None, :]
    lap = np.eye(a.shape[0]) - a_sym
    return lap, a_sym


def row_normalize_signed(weights: np.ndarray) -> np.ndarray:
    """Row-normalize by the L1 norm of each row (sum of |weight|), preserving
    sign. A zero row (isolated node) stays zero. `sum_j |P[i,j]| == 1` for
    every non-isolated row — this is the property `diffuse` relies on for
    stability, independent of the graph's structure."""
    row_abs_sum = np.abs(weights).sum(axis=1)
    p = np.zeros_like(weights)
    nz = row_abs_sum > 0
    p[nz, :] = weights[nz, :] / row_abs_sum[nz, None]
    return p


def diffuse(
    signal: np.ndarray,
    weights: np.ndarray,
    cfg: DiffusionConfig = DiffusionConfig(),
) -> np.ndarray:
    """Diffuse `signal` (one value per node, same order as `weights`'s rows)
    across the signed graph `weights`. Returns each node's "neighbourhood
    implied" value — never includes the node's own signal directly (P has a
    zero diagonal by construction, since `sparsify_top_k`/`combine_sources`
    zero the diagonal), only via indirect (>=2-hop) paths through neighbours.

    Iterates via SPARSE matrix-vector products, never a matrix inverse.
    """
    if not 0.0 <= cfg.alpha < 1.0:
        raise ValueError(f"alpha must be in [0, 1) for the iteration to converge, got {cfg.alpha}")
    n = weights.shape[0]
    if signal.shape != (n,):
        raise ValueError(f"signal shape {signal.shape} != ({n},)")

    p = sparse.csr_matrix(row_normalize_signed(weights))
    s0 = p @ signal
    s = s0.copy()
    for _ in range(cfg.n_iters):
        s = cfg.alpha * (p @ s) + (1.0 - cfg.alpha) * s0
    return np.asarray(s)


@dataclass(frozen=True)
class ConvergenceTrace:
    """Diagnostics from `diffuse_with_trace` — used by tests to verify the
    contraction empirically rather than just trusting the algebra."""

    deltas: list[float]   # ||S_{t+1} - S_t||_inf at each step
    ratios: list[float]   # deltas[t+1] / deltas[t] -- bounded above by alpha
                          # (the actual asymptotic rate is the spectral radius
                          # of alpha*P, which is <= alpha but often smaller)
    final: np.ndarray


def diffuse_with_trace(
    signal: np.ndarray,
    weights: np.ndarray,
    cfg: DiffusionConfig = DiffusionConfig(),
) -> ConvergenceTrace:
    """Same recursion as `diffuse`, but records the per-step infinity-norm
    change so convergence can be checked empirically."""
    if not 0.0 <= cfg.alpha < 1.0:
        raise ValueError(f"alpha must be in [0, 1) for the iteration to converge, got {cfg.alpha}")
    p = sparse.csr_matrix(row_normalize_signed(weights))
    s0 = p @ signal
    s = s0.copy()
    deltas: list[float] = []
    for _ in range(cfg.n_iters):
        s_next = cfg.alpha * (p @ s) + (1.0 - cfg.alpha) * s0
        deltas.append(float(np.max(np.abs(s_next - s))) if s_next.size else 0.0)
        s = s_next
    ratios = [
        deltas[i + 1] / deltas[i] for i in range(len(deltas) - 1) if deltas[i] > 1e-14
    ]
    return ConvergenceTrace(deltas=deltas, ratios=ratios, final=np.asarray(s))

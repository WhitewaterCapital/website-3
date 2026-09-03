"""Central configuration for WW-GRAPH.

One place for every tunable constant. Mirrors the discipline of the other
engines' `config.py` but shares nothing with them — this engine is sealed.

Every constant below is *fixed and documented*, per the spec: combination
weights and the diffusion damping factor are picked once, justified in
comments/README, and never fit to data. The only thing that IS fit to data is
the Ledoit-Wolf shrinkage intensity (that's what the estimator is for) and the
per-name OU half-life (that's the whole point of `reversion.py`).
"""

from __future__ import annotations

from dataclasses import dataclass


# --- Graph construction -------------------------------------------------

# Trailing bars used for the rolling return-correlation estimate. Long enough
# to stabilize a correlation matrix on ~30-300 names, short enough that the
# graph reflects the *current* regime rather than the whole sample history.
CORR_WINDOW = 60

# Fixed combination weights for the two edge sources (correlation-shrunk,
# sector-prior). NOT learned — see README "Design choices". Correlation does
# almost all the work; the sector prior only nudges ties and thickens edges
# within a sector so within-sector pairs aren't starved by a noisy 60-day
# correlation estimate.
W_CORR = 0.85
W_SECTOR = 0.15

# Value written into the sector-prior matrix for an (i, j) pair in the same
# sector (0 for a different sector, 0 on the diagonal). On the same 0-1 scale
# as a correlation so W_CORR/W_SECTOR above are directly comparable weights.
SECTOR_PRIOR_BONUS = 1.0

# Sparsify to the strongest TOP_K edges per node (10-20 per the spec). A dense
# 60-name correlation matrix mostly diffuses every name toward the market
# average (see graph/construct.py docstring) — sparsification is what makes
# the diffusion step mean something more specific than "beta to the tape".
TOP_K_EDGES = 15


# --- Diffusion -----------------------------------------------------------

# Damping factor for the iterative personalized-diffusion recursion
#   S_{t+1} = alpha * P @ S_t + (1 - alpha) * S_0
# P is row-normalized by the L1 norm of each row (sum of |weight|), so
# ||P||_inf == 1 by construction; alpha < 1 is therefore *sufficient* for the
# iteration to be a contraction in the infinity norm for ANY graph — this is
# verified numerically in tests/test_diffusion.py (both by eigenvalue bound on
# the normalized Laplacian and by empirical convergence of the iterates).
DIFFUSION_ALPHA = 0.60

# Fixed iteration count. At alpha=0.60 the contraction factor per step is 0.60,
# so after 30 steps the iterate is within 0.60**30 ~ 2e-7 of the fixed point —
# far tighter than anything that matters at daily-signal precision.
DIFFUSION_ITERS = 30


# --- Signal ----------------------------------------------------------------

# The raw per-name "signal" diffused across the graph: a cross-sectionally
# z-scored trailing SIGNAL_WINDOW-day return. See features/signal.py for why.
SIGNAL_WINDOW = 5


# --- Half-life / reversion --------------------------------------------------

# Dickey-Fuller t-stat critical value for the AR(1)/OU significance gate.
# Identical constant and identical math to
# intra-exitus-engine/ie/levels/ou.py:DF_CRIT_5PCT — duplicated on purpose
# (this engine is sealed and shares no code), not re-derived.
OU_DF_CRIT_5PCT = -2.86


# --- Backtest ----------------------------------------------------------------

BACKTEST_HORIZONS = (1, 3, 5, 10)   # trading days; spec asks for 1-10d
BACKTEST_COST_BPS = 10.0            # round-trip-ish per-side cost, in bps
BACKTEST_QUANTILE = 0.2             # top/bottom 20% of names by fade score


@dataclass(frozen=True)
class GraphConfig:
    corr_window: int = CORR_WINDOW
    top_k: int = TOP_K_EDGES
    w_corr: float = W_CORR
    w_sector: float = W_SECTOR
    sector_bonus: float = SECTOR_PRIOR_BONUS


@dataclass(frozen=True)
class DiffusionConfig:
    alpha: float = DIFFUSION_ALPHA
    n_iters: int = DIFFUSION_ITERS


@dataclass(frozen=True)
class BacktestConfig:
    horizon: int = 5
    quantile: float = BACKTEST_QUANTILE
    cost_bps: float = BACKTEST_COST_BPS
    periods_per_year: int = 252

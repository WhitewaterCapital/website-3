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

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """Load this engine's own .env into the environment without overwriting
    anything already set. Keeps the Tiingo key out of code and shell history.
    Identical in behaviour to intra-exitus-engine/ie/config.py's loader
    (duplicated, not imported — this engine is sealed). No third-party
    dependency."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


_load_dotenv()


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


# --- Live universe (real tickers) ----------------------------------------
# Used ONLY when TIINGO_API_KEY is set (see ge/adapters/prices_tiingo.py and
# ge/export.py::build_live_export) — the synthetic demo path above (and
# ge/synthetic.py) never touches these. Nothing here is fit to data; it is a
# fixed, documented list, same discipline as the rest of this file.
#
# 48 liquid, large-cap US equities across 6 sectors (8 names per sector):
# technology, financials, healthcare, energy, consumer staples, industrials.
# Sizing rationale:
#   - TOP_K_EDGES=15 sparsifies to each node's strongest 15 neighbours; a
#     48-name universe (47 possible neighbours per node) is comfortably
#     larger than that, so top-15 is a real sparsification, not "keep nearly
#     everything."
#   - 8 names per sector gives `graph/construct.py`'s sector-prior edge
#     source a real same-sector peer group (7 candidates per name) to work
#     with, rather than 1-2 name "sectors" that the prior can't meaningfully
#     thicken.
#   - Large-cap, liquid, long-listed names were chosen specifically because
#     they minimize the odds of a Tiingo history gap or a recent IPO/listing
#     truncating the correlation window (see adapters/prices_tiingo.py's
#     `fetch_close_panel`, which drops any date where a name is missing).
# This is an illustrative universe, not survivorship-free or point-in-time —
# see the adapter module's own INTEGRITY NOTES for the same caveat carried by
# every Tiingo adapter in this repo.
UNIVERSE: list[str] = [
    # Technology
    "AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "ORCL", "CRM",
    # Financials
    "JPM", "BAC", "GS", "MS", "WFC", "C", "SCHW", "BLK",
    # Healthcare
    "JNJ", "PFE", "UNH", "MRK", "ABBV", "LLY", "TMO", "ABT",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY",
    # Consumer staples
    "KO", "PEP", "PG", "WMT", "COST", "CL", "MDLZ", "KMB",
    # Industrials
    "GE", "HON", "CAT", "UNP", "BA", "MMM", "LMT", "DE",
]

SECTOR_MAP: dict[str, str] = {
    **{t: "tech" for t in ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "ORCL", "CRM"]},
    **{t: "financials" for t in ["JPM", "BAC", "GS", "MS", "WFC", "C", "SCHW", "BLK"]},
    **{t: "healthcare" for t in ["JNJ", "PFE", "UNH", "MRK", "ABBV", "LLY", "TMO", "ABT"]},
    **{t: "energy" for t in ["XOM", "CVX", "COP", "SLB", "EOG", "PSX", "MPC", "OXY"]},
    **{t: "staples" for t in ["KO", "PEP", "PG", "WMT", "COST", "CL", "MDLZ", "KMB"]},
    **{t: "industrials" for t in ["GE", "HON", "CAT", "UNP", "BA", "MMM", "LMT", "DE"]},
}

assert len(UNIVERSE) == len(set(UNIVERSE)), "UNIVERSE has a duplicate ticker"
assert set(UNIVERSE) == set(SECTOR_MAP), "UNIVERSE/SECTOR_MAP have drifted apart"

# Calendar days of history requested from Tiingo for a live run. CORR_WINDOW
# (60) plus run_history's own warmup (+5) is the bare minimum for even one
# cross-section; reversion.py's OU fit additionally needs >= 20 residual
# observations per name (MIN_HISTORY_FOR_OU in export.py) built up AFTER that
# warmup. 600 calendar days is roughly 400-410 trading days — comfortably
# covering warmup + a real post-warmup history, with room to spare for the
# handful of rows `fetch_close_panel` may drop to holiday-calendar mismatches
# across 48 names.
LIVE_HISTORY_CALENDAR_DAYS = 600


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

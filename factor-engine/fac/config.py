"""Central configuration for WW-FACTOR.

One place for every tunable constant. Mirrors the discipline of
`graph-engine/ge/config.py` and `weekly-engine/wf/config.py` but shares
nothing with either — this engine is sealed. Every constant below is fixed
and documented, not fit to data (the only thing fit to data is the OLS
coefficients themselves — that's the whole point of `regression.py`).
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


# --- Regression window ----------------------------------------------------

# Trailing trading days used for the factor-exposure OLS. 252 is the
# standard "one calendar year" convention in equities (roughly
# 5 days/week * 50.4 weeks, net of ~9-10 US market holidays) — long enough
# to average out day-to-day noise in a 6-factor regression, short enough
# that the reported betas reflect the name's CURRENT factor loadings rather
# than a multi-year blend across very different regimes for that name
# (e.g. before/after a business-mix change). Same "current regime, not whole
# history" rationale as graph-engine's CORR_WINDOW (60d) and
# weekly-engine's momentum lookbacks — just longer, because a factor beta is
# a slower-moving property of a security than a 5-10 day mean-reversion
# residual.
WINDOW_TRADING_DAYS = 252

# Minimum overlapping (ticker return, factor return) observations required
# before ANY beta is reported. The regression fits 7 parameters (intercept +
# 6 factors: Mkt-RF, SMB, HML, RMW, CMA, Mom). A common rule of thumb for a
# trustworthy OLS is >= 10 observations per parameter (70 here); this picks
# a materially higher floor for two reasons documented explicitly rather
# than left implicit:
#   1. Daily equity returns are noisy and often weakly cross-correlated with
#      each other within a short window, so the effective sample size is
#      smaller than the raw observation count suggests.
#   2. 126 trading days is exactly half of WINDOW_TRADING_DAYS — a ticker
#      that has been trading for less than ~6 months gets an honest
#      "insufficient_history" abstain rather than a beta estimated mostly
#      from an incomplete window.
# This mirrors graph-engine/ge/export.py's MIN_HISTORY_FOR_OU gate: a fixed,
# documented floor below which the model abstains rather than invent a
# number, applied identically regardless of data provenance (see
# regression.py's `fit_factor_exposure`, the one place either export path
# runs this gate).
MIN_OBS = 126

# Number of fitted parameters (intercept + FACTOR_COLUMNS below). Used only
# to size the obs-per-parameter ratio reported alongside each fit's
# diagnostics — not itself a gate (MIN_OBS already fixes the floor).
N_PARAMS = 7

# Two-sided 5% critical t-value used to flag a factor's beta as
# "statistically distinguishable from zero at this window length", purely as
# an honest annotation next to the number — NOT a per-factor abstain gate.
# Unlike graph-engine's half-life (a single number that is either
# meaningfully estimated or not), a factor beta is a standard descriptive
# quantity that is reported alongside its own significance flag in every
# textbook factor-exposure table; hiding an insignificant beta would remove
# real information (e.g. "this name currently has ~zero measurable exposure
# to CMA") rather than protect against a fabricated one. 1.96 is the
# standard large-sample two-sided 5% critical value; with N_PARAMS=7 and
# MIN_OBS=126, residual degrees of freedom is always >= 119, comfortably in
# the range where the normal approximation to the t-distribution is fine
# (exact t critical values at that many df round to 1.96-1.98).
BETA_T_CRIT = 1.96

# Above this condition number (of the regression design matrix's X'X), the
# fit is treated as numerically degenerate — a factor is collinear with
# another over this specific window, or a factor is constant over the
# window (e.g. a data outage padded the panel with repeated values) — and
# the ticker abstains with confidence "degenerate" rather than publish a
# beta the arithmetic could not actually pin down. 1e10 is a standard
# numerical-linear-algebra rule of thumb for "this system is not reliably
# invertible in double precision" (double precision carries ~15-16 decimal
# digits; a condition number this large means fewer than ~6 reliable digits
# are left in the solution).
MAX_CONDITION_NUMBER = 1.0e10


# --- Kenneth French Data Library -------------------------------------------
# Free, no-signup, monthly-updated. URLs verified live (2026-09) by fetching
# https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html —
# see french_factors.py's module docstring for the exact CSV-format
# idiosyncrasies (header banner, percent units, table-boundary detection)
# these files carry, and for why this sandbox could not verify the fetch
# end-to-end (no outbound network access here at all).
FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
FRENCH_5_FACTOR_DAILY_URL = f"{FRENCH_BASE}/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
FRENCH_MOMENTUM_DAILY_URL = f"{FRENCH_BASE}/F-F_Momentum_Factor_daily_CSV.zip"

# The five factors from the 2x3 daily file, in the order the CSV publishes
# them, plus the momentum factor from the separate file — the six exposures
# this engine reports a beta for. RF (risk-free rate) is fetched from the
# same 5-factor file but consumed as the excess-return deflator, not
# reported as a factor beta.
FACTOR_COLUMNS = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
RF_COLUMN = "RF"

# Human-readable, one-line explanation of what a positive beta on each
# factor means — the raw material for the website panel's "explain this to
# a non-quant" sentences (see src/components/panels/FactorPanel.tsx). Kept
# here, next to the factor list itself, so the two never drift apart.
FACTOR_EXPLAINERS: dict[str, str] = {
    "Mkt-RF": "how much the stock swings relative to the overall stock market",
    "SMB": "small-cap tilt (Small Minus Big) — positive means it behaves more like a small company than a large one",
    "HML": "value tilt (High Minus Low book-to-market) — positive means it behaves more like a cheap/value stock than an expensive/growth one",
    "RMW": "profitability tilt (Robust Minus Weak) — positive means it behaves more like a highly profitable company",
    "CMA": "investment tilt (Conservative Minus Aggressive) — positive means it behaves more like a conservative, low-capex company",
    "Mom": "momentum tilt — positive means it behaves like stocks that have recently been trending up; negative means it currently moves against recent winners",
}

# How long a locally cached French factor file is trusted before this engine
# re-downloads it. Ken French's library updates roughly monthly (a new
# trading day's row is appended, occasionally with small revisions to the
# most recent few days as CRSP data settles) — daily re-fetching would just
# hammer a free, unauthenticated, no-rate-limit-published server for no
# benefit. 1 day is deliberately much shorter than the update cadence: it
# keeps a long-running/scheduled process fresh within a day of any revision
# without needing a smarter cache-invalidation signal.
FRENCH_CACHE_TTL_SECONDS = 24 * 60 * 60


def engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    # factor-engine/fac/config.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    d = engine_root() / "data" / "cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def exports_dir() -> Path:
    d = engine_root() / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --- Live universe (real tickers) ------------------------------------------
# A small, illustrative demo universe used by `fac/export.py`'s live path
# when no single ticker is requested via CLI/env — liquid, long-listed
# large caps chosen (same rationale as graph-engine's UNIVERSE) to minimize
# the odds of a Tiingo history gap truncating the regression window. This is
# NOT survivorship-free or point-in-time — see prices_tiingo.py's INTEGRITY
# NOTES, carried by every Tiingo adapter in this repo.
DEFAULT_LIVE_UNIVERSE: list[str] = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO"]

# Calendar days of history requested from Tiingo for a live run. Comfortably
# more than WINDOW_TRADING_DAYS (252) converted to calendar days (~365) to
# leave slack for weekends/holidays and the panel-alignment step.
LIVE_HISTORY_CALENDAR_DAYS = 420


@dataclass(frozen=True)
class RegressionConfig:
    window: int = WINDOW_TRADING_DAYS
    min_obs: int = MIN_OBS
    t_crit: float = BETA_T_CRIT
    max_condition_number: float = MAX_CONDITION_NUMBER

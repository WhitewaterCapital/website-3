"""Central configuration for WW-KALMAN — the adaptive-Kalman-filter pairs
trading / statistical-arbitrage engine.

Mirrors the discipline of every other engine in this repo (cascade-data-
engine/cde/config.py, chaos-engine/chaos/config.py, earnings-engine/ee/
config.py): one place for every tunable constant, a gitignored per-engine
.env loaded without a third-party dependency, and a fixed live-vs-synthetic
gate on named env vars. This engine is SEALED — nothing here is imported
from, or imports, any other engine's config; the two Alpaca env var names
below are typed out as the same literal strings chaos-engine/chaos/
config.py and cascade-data-engine/cde/adapters/alpaca_volume.py use,
intentionally, so one key pair configured once lights up every engine that
wants Alpaca — but that is a deliberate literal-string coincidence, not a
cross-engine dependency (see kf/adapters/alpaca_bars.py's own docstring).

## Why this engine exists, and what it deliberately is NOT

Philip asked for something built "in the spirit" of what Susquehanna (SIG)
publicly describes about its own philosophy — probabilistic decision-making
under uncertainty, Bayesian updating on incoming data, continuous real-time
iteration rather than a static thesis (see README.md's "On Susquehanna"
section for the actual public sources this is grounded in, and the explicit
statement that NOTHING about SIG's real proprietary models is public or
replicated here). This engine is NOT a claim to reproduce any real SIG
system. It is a real, standard piece of quantitative-finance theory — a
Kalman-filter pairs-trading / statistical-arbitrage model — built so that
its own noise-covariance parameters (Q, R) are estimated ONLINE, from the
filter's own innovation sequence, as new data arrives, rather than fixed by
a hand-picked hyperparameter. That online self-re-estimation is the
literal, cited mechanism behind "learns from itself" — see kf/filter.py's
module docstring for the specific published method this implements (Mehra/
Akhlaghi-style innovation-based adaptive covariance estimation) and what it
deliberately does NOT implement (EM-based batch noise-covariance learning —
a real, different method from the same literature, named honestly as a
considered-but-not-built alternative, not silently omitted).
"""

from __future__ import annotations

import itertools
import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_dotenv() -> None:
    """Load this engine's own .env into the environment without overwriting
    anything already set. Duplicated (not imported) from the identical
    loader in every other engine in this repo — this engine is sealed."""
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


def env(name: str) -> str | None:
    v = os.environ.get(name, "").strip()
    return v or None


# --- Live-data gate ----------------------------------------------------------
# Intentionally the same two literal env var names chaos-engine/chaos/
# config.py and cascade-data-engine/cde/adapters/alpaca_volume.py use — see
# kf/adapters/alpaca_bars.py's module docstring for why Alpaca (free
# "Basic" Market Data API plan, IEX feed, 1Day bars) is the vendor here too.
ALPACA_API_KEY_ID_VAR = "ALPACA_API_KEY_ID"
ALPACA_API_SECRET_KEY_VAR = "ALPACA_API_SECRET_KEY"

# The same fixed 6-name cross-sectional universe smart-money-momentum.ts /
# earnings-move.ts / earnings-engine / cascade-data-engine's synthetic
# fallback all already use — chosen for consistency with the rest of this
# session's cross-sectional work, not invented fresh for this engine.
UNIVERSE: list[str] = ["AAPL", "MSFT", "NVDA", "JPM", "XOM", "KO"]

# All unique unordered pairs from UNIVERSE — C(6,2) = 15 candidate pairs.
# Order within a pair is fixed by UNIVERSE's own order (itertools.combinations
# preserves input order), so "AAPL/MSFT" always means y1=AAPL, y2=MSFT, never
# both orderings tested separately — the Engle-Granger regression direction
# matters (regressing AAPL on MSFT vs. MSFT on AAPL gives different residuals
# in finite samples, a known asymmetry of the two-step method — see
# kf/cointegration.py's module docstring), and a fixed convention here means
# every run tests the same 15 directed regressions, not 30.
CANDIDATE_PAIRS: list[tuple[str, str]] = list(itertools.combinations(UNIVERSE, 2))

# --- Data window ---------------------------------------------------------------
# Calendar days of daily-bar history requested. ~400 calendar days comfortably
# clears MIN_OBSERVATIONS below even across holidays, and gives the ADF
# cointegration pretest real statistical power (power to detect a stationary
# residual rises with sample size; too short a window and a genuinely
# cointegrated pair can fail to reject the unit-root null purely from low
# power — an honest abstention for the wrong reason, which a longer window
# reduces without eliminating).
LOOKBACK_CALENDAR_DAYS = 400

# Below this many overlapping (both tickers, same trading day) daily closes,
# the Engle-Granger test is not run at all for that pair — both the OLS
# hedge-ratio estimate and the ADF test on its residuals are unreliable with
# too few points, and reporting a cointegration verdict either way would be
# a confident-sounding number built on a statistically thin foundation. This
# floor (60 ~ about 3 trading months) is a documented judgment call, not a
# textbook-derived constant — stated as such wherever it binds.
MIN_OBSERVATIONS = 60

# --- Engle-Granger cointegration test -----------------------------------------
# Significance level for the ADF test on the first-stage OLS residuals (see
# kf/cointegration.py). 0.05 (5%) is the conventional default threshold used
# throughout applied cointegration literature (e.g. Vidyamurthy, "Pairs
# Trading: Quantitative Methods and Analysis", 2004) and elsewhere in this
# repo's own statistical tests (e.g. the 95% two-sided t-critical convention
# factor-engine's FactorBeta.significant uses).
COINTEGRATION_SIGNIFICANCE = 0.05

# Maximum lag order tried in the augmented Dickey-Fuller regression's AIC
# search (kf/cointegration.py::adf_test_statistic). Schwert's (1989) rule of
# thumb, floor(12*(T/100)^0.25), is the standard heuristic statsmodels'
# adfuller() itself uses for its own default maxlag search — reimplemented
# here (not imported, statsmodels is not available in this environment —
# confirmed via `python3 -c "import statsmodels"` this pass, see README.md)
# but capped at a smaller absolute ceiling than Schwert's formula alone would
# give for our ~250-observation windows, because a long lag order relative to
# a few-hundred-observation sample starts eating meaningful degrees of
# freedom in the auxiliary regression — a documented, conservative choice,
# not a literature-derived exact figure.
ADF_MAX_LAG_CEILING = 8

# --- Adaptive Kalman filter ---------------------------------------------------
# See kf/filter.py's module docstring for the full citation and derivation of
# every constant below — this is just where the numbers live, following this
# repo's "one place for every tunable constant" convention.

# Initial guess for the diagonal of Q (process-noise covariance on
# [intercept, hedge_ratio]) before any online adaptation has occurred. Small
# and deliberately non-zero (a hard-zero Q would make the filter believe the
# hedge ratio literally cannot drift, collapsing it to a static OLS fit) —
# this value only matters for the first handful of observations; the whole
# point of the adaptive mechanism is that the filter stops depending on this
# guess as real innovations accumulate.
INITIAL_Q_DIAG = (1e-6, 1e-6)

# Initial guess for R (observation-noise variance on the spread residual),
# in LOG-PRICE units (see kf/filter.py for why log-prices, not raw prices).
# 1e-3 is a small-but-not-negligible starting point — roughly consistent
# with day-to-day idiosyncratic log-price noise for a liquid large-cap name
# net of a linear hedge, but explicitly a starting GUESS the online adaptive
# update (kf/filter.py::run_adaptive_kalman_filter) is expected to move away
# from, not a calibrated constant.
INITIAL_R = 1e-3

# Forgetting factor for the online Mehra/Akhlaghi-style covariance-matching
# update (kf/filter.py). Akhlaghi et al. (2017, arXiv:1702.00884) use
# alpha=0.3 in their own INS/GPS experiments, but that system samples at a
# very high rate (many observations per "regime") — this engine runs on
# ONE observation per trading day, so an effective averaging window of only
# ~1/(1-0.3) ~ 1.4 days would make Q/R chase single-day noise almost
# entirely, discarding the whole point of averaging. FORGETTING_FACTOR=0.9667
# gives an effective window of 1/(1-0.9667) ~= 30 observations (~a trading
# month) — long enough to average out day-to-day noise, short enough to
# track a real regime shift within a few weeks. This is THIS ENGINE's own
# documented judgment call, adapting Akhlaghi et al.'s general mechanism to a
# slower-sampled market, not a value taken from their paper.
FORGETTING_FACTOR = 0.9667

# Floors preventing Q or R from being adaptively driven to (numerically)
# zero, which would make the filter overconfident and brittle — see
# kf/filter.py's module docstring for exactly where these are applied.
Q_DIAG_FLOOR = 1e-10
R_FLOOR = 1e-8

# --- Signal thresholds on the standardized innovation (z-score) --------------
# The Kalman filter's own standardized innovation z_t = v_t / sqrt(S_t) (v_t
# the pre-fit innovation, S_t its predicted variance — see kf/filter.py) is
# the real statistical quantity a pairs-trading signal is conventionally
# built from (Vidyamurthy 2004; Chan, "Algorithmic Trading", 2013, ch. 5).
# These specific numeric bands are a stated, simple, NOT backtested
# convention — same honesty discipline as smart-money-momentum.ts's
# `clamp(mom.beta * 40, ...)` and earnings-move.ts's scaling choices: a
# reasonable reading of a standardized residual (|z|>2 is a ~2-sigma
# deviation under the filter's own noise model), not a fitted trading rule.
Z_ENTRY_THRESHOLD = 2.0     # |z| beyond this: signal a mean-reversion trade
Z_EXIT_THRESHOLD = 0.5      # |z| within this: spread judged back near fair value
Z_TO_SCORE_SCALE = 25.0     # score = clamp(-z * this, -100, 100)


@dataclass(frozen=True)
class AdaptiveFilterConfig:
    """Bundled adaptive-Kalman-filter constants, passed to
    kf/filter.py::run_adaptive_kalman_filter as one object rather than five
    positional args — same convention as chaos-engine's ComponentConfig /
    StateConfig dataclasses."""

    initial_q_diag: tuple[float, float] = INITIAL_Q_DIAG
    initial_r: float = INITIAL_R
    forgetting_factor: float = FORGETTING_FACTOR
    q_diag_floor: float = Q_DIAG_FLOOR
    r_floor: float = R_FLOOR

    def __post_init__(self):
        assert 0.0 < self.forgetting_factor < 1.0
        assert self.initial_r > 0.0
        assert all(q > 0.0 for q in self.initial_q_diag)


SCHEMA_VERSION = "1.0.0"
ENGINE_VERSION = "0.1.0"


def engine_root() -> Path:
    return Path(__file__).resolve().parent.parent


def repo_root() -> Path:
    # kalman-engine/kf/config.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def exports_dir() -> Path:
    d = engine_root() / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d

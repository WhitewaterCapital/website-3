"""Central configuration for the WW-CHAOS engine.

One place for every constant, threshold and path. Mirrors the discipline of
the other engines in this repo (`engine/incepta/config.py`,
`intra-exitus-engine/ie/config.py`) but shares nothing with them — this
engine is sealed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# --- Demo/synthetic watchlist -------------------------------------------------
# No live data access exists here. The export runs in synthetic-demo mode
# against a small illustrative watchlist so the JSON contract can be exercised
# end to end. Real deployment would replace the synthetic panel generator in
# export.py with a real intraday bar feed — nothing else changes.
WATCHLIST: list[str] = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ"]

BARS_PER_DAY = 390  # a standard 6.5h US cash session at 1-minute bars


@dataclass(frozen=True)
class StateConfig:
    """Thresholds and dwell times for the CHAOS-01 state machine.

    Hysteresis: entering a more severe state requires the index to cross an
    UPPER threshold; leaving it back to a calmer state requires dropping below
    a DISTINCTLY LOWER threshold (never the same value) so noise sitting near
    one number cannot flap the label back and forth. `min_dwell_bars` further
    forbids any state change (up OR down) until that many bars have elapsed
    since the last change, regardless of what the index does in between.
    """

    enter_stressed: float = 0.35
    exit_stressed: float = 0.25       # < enter_stressed: hysteresis gap
    enter_dislocated: float = 0.60
    exit_dislocated: float = 0.45     # < enter_dislocated: hysteresis gap
    enter_cascade: float = 0.85
    exit_cascade: float = 0.70        # < enter_cascade: hysteresis gap
    min_dwell_bars: int = 5

    def __post_init__(self):
        assert self.exit_stressed < self.enter_stressed
        assert self.exit_dislocated < self.enter_dislocated
        assert self.exit_cascade < self.enter_cascade
        assert self.enter_stressed < self.enter_dislocated < self.enter_cascade
        assert self.min_dwell_bars >= 1


@dataclass(frozen=True)
class ComponentConfig:
    """Windows for the eight CHAOS-01 components, in bars (default: 1-minute
    bars, so "60" means a trailing 60-minute window)."""

    fast_vol_window: int = 5          # "5-min bars" realised-vol window
    slow_vol_window: int = 60         # trailing 60-minute realised-vol window
    volume_lookback_sessions: int = 10  # trailing sessions for the vol z-score
    dispersion_window: int = 5
    corr_short_window: int = 15
    corr_trailing_window: int = 60
    jump_window: int = 60             # bipower-variation estimation window
    min_bars_for_component: int = 20  # below this, a component reports unavailable


@dataclass(frozen=True)
class ExecutionConfig:
    """CHAOS-03 cost-aware execution assumptions."""

    base_half_spread_bps: float = 2.0   # calm-state assumed half-spread
    # Multiplier applied to the base half-spread per chaos state — spreads are
    # WIDEST exactly when this model wants to trade, so cost must scale with it.
    state_spread_multiplier: dict = field(default_factory=lambda: {
        "calm": 1.0,
        "stressed": 1.8,
        "dislocated": 3.0,
        "cascade": 5.0,
    })
    impact_bps_per_unit_participation: float = 15.0  # linear impact model slope
    min_holding_bars: int = 3
    max_turnover_per_session: float = 4.0  # sum(|delta position|) cap per session


def repo_root() -> Path:
    # chaos-engine/chaos/config.py -> parents[2] == repo root
    return Path(__file__).resolve().parents[2]


def exports_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / "exports"
    d.mkdir(parents=True, exist_ok=True)
    return d

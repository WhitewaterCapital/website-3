"""Regime labels — the supervised target for the classifier.

Regimes are not observed, so we DEFINE them by what price did over a forward
horizon of H days, using two measurable, geometry-based quantities:

  * Efficiency ratio (Kaufman):  |net move| / path length  over the forward
    window. Near 1 => a clean directional move; near 0 => a choppy round-trip.
    This is the fundamental trend-vs-revert axis.
  * Volatility level:  forward realised vol, compared to the name's own history.
    When forward vol sits in the top band (a "dangerous vol" regime), we do NOT
    want to place level bets (=> abstain). Defining it on the *level* (a within-
    name percentile), not on expansion-vs-trailing, means a *sustained* high-vol
    chop stays high-vol instead of being relabelled once trailing vol catches up.

Mapping (high-vol wins, so the three classes are mutually exclusive):
    forward vol in top band  -> "high-vol"
    efficiency >= cutoff     -> "trend"
    otherwise                -> "mean-revert"

DIRECTION IS DELIBERATELY NOT A LABEL. Honest walk-forward evaluation showed the
10-day *sign* of a move is essentially unpredictable from price features (an
efficient-market result), and trying to learn it only buried the one thing the
classifier can learn — that volatility clusters. So the target is the *template*
question (fade a range / follow a trend / stand aside), and the long-vs-short
direction is decided by the level engine's geometry at decision time. We still
record a forward `direction` column here, but purely as a diagnostic — never as a
training target.

LOOK-AHEAD, STATED PLAINLY: the label at row t is computed from returns over
t+1..t+H — it deliberately uses the future. That is fine for a *training target*
and is the whole point of a predictive model, but it means:
  1. the last H rows cannot be labeled (no future yet) — they come back NaN, and
  2. training MUST use purged + embargoed cross-validation so a label's forward
     window never overlaps the test fold. That splitter is built with the
     classifier; this module only produces the honest labels + diagnostics.

The features, by contrast, remain strictly as-of (see features/price.py). Future
data touches the label and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

REGIMES: tuple[str, ...] = ("trend", "mean-revert", "high-vol")
DIRECTIONS: tuple[str, ...] = ("up", "down")  # diagnostic only, never a target


@dataclass(frozen=True)
class LabelConfig:
    """Horizon and thresholds. Defaults are reasonable starting points; the
    thresholds are meant to be *calibrated for class balance* (APM Ch 16), not
    treated as physical constants."""

    horizon: int = 10             # forward window H, in trading days (~2 weeks)
    er_trend: float = 0.40        # efficiency-ratio cutoff: >= is "directional"
    vol_pct: float = 0.85         # forward vol >= this within-name quantile => high-vol
    vol_min_periods: int = 252    # min history before the expanding vol threshold is defined
    trailing_vol_window: int = 21  # window for the trailing-vol diagnostic
    trading_days: int = 252


def make_labels(close: pd.Series, cfg: LabelConfig | None = None) -> pd.DataFrame:
    """Return a frame indexed like `close` with the regime label and the
    diagnostics used to derive it.

    Columns:
      label          : one of REGIMES, or NaN for the un-labelable tail (last H)
      direction      : "up"/"down" (sign of the forward move) — diagnostic only
      efficiency     : forward Kaufman efficiency ratio in [0, 1]
      net_move       : forward log return over the horizon
      fwd_vol        : forward annualised realised vol
      trailing_vol   : as-of trailing annualised vol
      vol_ratio      : fwd_vol / trailing_vol
    """
    cfg = cfg or LabelConfig()
    h = cfg.horizon
    if h < 2:
        raise ValueError("horizon must be >= 2")

    lr = np.log(close / close.shift(1))
    abs_lr = lr.abs()

    # Forward aggregates aligned to row t (they describe t+1 .. t+h):
    #   rolling(h).sum/std at index t+h summarises t+1..t+h, so shift(-h) aligns.
    net_move = np.log(close.shift(-h) / close)              # log(P_{t+h}/P_t)
    path_length = abs_lr.rolling(h).sum().shift(-h)         # sum |r| over t+1..t+h
    fwd_vol = lr.rolling(h).std(ddof=0).shift(-h) * np.sqrt(cfg.trading_days)

    # As-of trailing vol (strictly backward — no shift).
    trailing_vol = lr.rolling(cfg.trailing_vol_window).std(ddof=0) * np.sqrt(cfg.trading_days)

    efficiency = net_move.abs() / path_length.replace(0.0, np.nan)
    vol_ratio = fwd_vol / trailing_vol.replace(0.0, np.nan)  # diagnostic only

    # A row is labelable only when every forward quantity is defined.
    valid = net_move.notna() & path_length.notna() & fwd_vol.notna() & (path_length > 0)

    # High-vol = forward vol in the top band of the name's own history.
    # FIX #3 (2026-08): the threshold is now an EXPANDING (causal) within-name
    # quantile — at row t it uses only fwd_vol[0..t]. Appending future bars can no
    # longer change an earlier row's label, so the "out-of-sample" kappa isn't
    # contaminated by a threshold that peeked at the whole series. Rows before
    # vol_min_periods have no threshold yet and simply aren't eligible for high-vol.
    vol_hi = fwd_vol.expanding(min_periods=cfg.vol_min_periods).quantile(cfg.vol_pct)
    high_vol = valid & vol_hi.notna() & (fwd_vol >= vol_hi)
    directional = (efficiency >= cfg.er_trend).fillna(False)
    up = (net_move > 0).fillna(False)

    label = pd.Series(np.nan, index=close.index, dtype=object)
    label[high_vol] = "high-vol"
    calm = valid & ~high_vol
    label[calm & directional] = "trend"
    label[calm & ~directional] = "mean-revert"

    # Forward direction — diagnostic only, defined wherever a row is labelable.
    direction = pd.Series(np.nan, index=close.index, dtype=object)
    direction[valid & up] = "up"
    direction[valid & ~up] = "down"

    return pd.DataFrame(
        {
            "label": label,
            "direction": direction,
            "efficiency": efficiency,
            "net_move": net_move,
            "fwd_vol": fwd_vol,
            "trailing_vol": trailing_vol,
            "vol_ratio": vol_ratio,
        }
    )


def label_distribution(labels: pd.Series) -> pd.Series:
    """Class counts (labelled rows only) — the input to imbalance decisions."""
    return labels.dropna().value_counts()

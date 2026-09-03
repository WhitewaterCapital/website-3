"""WW-STATE — the market state vector (STATE-01).

"Produces one vector describing what kind of market this is right now so the
allocator can decide which strategies deserve capital in it."

Seven elements, each a pure function of PRICE/RETURN history handed in by the
caller (no I/O, no network, no hidden globals — same "pure function over
arrays/frames" discipline as `features/returns.py` and `models/scoring.py`):

  1. volatility   — realised vol of the index over several windows.
  2. dispersion   — cross-sectional std of constituent returns.
  3. correlation  — average pairwise correlation and its rate of change.
  4. breadth      — share of universe above its own moving average +
                    advance/decline balance.
  5. trend        — index momentum across several horizons with a
                    sign-consistency measure.
  6. slippage     — realised execution cost vs expected cost.
  7. liquidity    — depth/volume vs own history + spread level.

Two elements are usually **not observable** with the data this engine has
today, and this module is deliberately honest about that instead of guessing:

  - **Implied volatility / vol term structure** needs a live options/vendor
    feed this engine does not have. `volatility.raw["implied_vol"]` is always
    `None` with a `reason` string — never a fabricated number.
  - **Slippage** needs realised broker fills. Until execution data exists,
    `slippage.available` is `False` with a `reason` string, and `.value` is
    `None` — never inferred from a cost model pretending to be a fill.

Standardization discipline (the one the dossier explicitly warns against
getting wrong): every element is z-scored against its OWN FULL LONG HISTORY,
never against just the recent window it was computed over. Comparing "today's
63d realised vol" only to the last 60 days of 63d-vol readings tells you
nothing about whether today is actually high or low — if the whole recent
period has been elevated, that comparison reports "normal". `_own_history_stat`
is the one place this is done, and `test_state.py` proves it against the
naive (wrong) alternative.

The vector is versioned (`SCHEMA_VERSION` / `ELEMENT_ORDER`) so a length/order
change is a breaking, testable event — see `validate_schema`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from . import __version__
from .features import returns as R

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.0.0"
ELEMENT_ORDER: list[str] = [
    "volatility", "dispersion", "correlation", "breadth",
    "trend", "slippage", "liquidity",
]

DISCLAIMER = (
    "Research/paper output only. Describes market REGIME, not a trade signal. "
    "Two of seven elements (implied-vol term structure, slippage) require data "
    "this engine does not yet have and are reported as null with a stated "
    "reason rather than estimated."
)


class SchemaMismatchError(ValueError):
    """Raised by `validate_schema` when a vector's version or element order
    doesn't match what the caller expects — a length/order change IS a
    breaking change for anything downstream (allocator, dashboard)."""


@dataclass
class ElementReading:
    """One of the seven state-vector elements.

    `value` is the single standardized (z-score-like) number the allocator
    reads; it is `None` exactly when `available` is `False`. `raw` carries the
    element-specific numbers (levels, sub-scores, per-window breakdowns) for
    the dashboard and for debugging — never fabricated, only what was
    actually computed from the inputs given. `notes` documents partial gaps
    (e.g. volatility has realised vol but not implied vol) even when
    `available` is True; `reason` explains a full `available=False`.
    """

    available: bool
    value: Optional[float]
    raw: dict
    notes: list = field(default_factory=list)
    reason: Optional[str] = None


@dataclass
class StateVector:
    schema_version: str
    element_order: list[str]
    as_of: date
    volatility: ElementReading
    dispersion: ElementReading
    correlation: ElementReading
    breadth: ElementReading
    trend: ElementReading
    slippage: ElementReading
    liquidity: ElementReading


def validate_schema(vector: StateVector, expected_version: str = SCHEMA_VERSION) -> bool:
    """Raise `SchemaMismatchError` if `vector` doesn't match the expected
    schema version or element order/length. Returns True on success (so it
    reads naturally as `assert validate_schema(v, "1.0.0")` too)."""
    if vector.schema_version != expected_version:
        raise SchemaMismatchError(
            f"schema_version mismatch: vector has {vector.schema_version!r}, "
            f"expected {expected_version!r}"
        )
    if list(vector.element_order) != list(ELEMENT_ORDER):
        raise SchemaMismatchError(
            f"element_order mismatch: vector has {list(vector.element_order)!r}, "
            f"expected {list(ELEMENT_ORDER)!r} — a length or order change is a "
            "breaking change for every consumer keyed on position/order."
        )
    return True


# ---------------------------------------------------------------------------
# Own-long-history standardization (the discipline the dossier warns about)
# ---------------------------------------------------------------------------

@dataclass
class _HistStat:
    latest: Optional[float]
    history_mean: Optional[float]
    history_std: Optional[float]
    z: Optional[float]
    n_obs: int


def _own_history_stat(series: np.ndarray) -> _HistStat:
    """Standardize the LAST valid value of `series` against the mean/std of
    EVERY valid value in `series` — its own full history — not just a recent
    slice. This is deliberate: a value that looks unremarkable next to the
    last N readings of itself can still be far from normal once you look at
    the whole record (e.g. a vol regime that has been elevated for months —
    every recent reading agrees with every other recent reading, so a
    recent-window-only comparison reports "normal" when it is anything but).
    """
    s = np.asarray(series, dtype=float)
    valid = s[~np.isnan(s)]
    if valid.size < 2:
        return _HistStat(None, None, None, None, int(valid.size))
    latest = float(valid[-1])
    mean = float(np.mean(valid))
    std = float(np.std(valid, ddof=1))
    z = (latest - mean) / std if std > 0 else None
    return _HistStat(latest, mean, std, z, int(valid.size))


def _rolling_std(returns: np.ndarray, window: int, annualize: bool = True) -> np.ndarray:
    s = pd.Series(np.asarray(returns, dtype=float))
    v = s.rolling(window, min_periods=window).std(ddof=1)
    if annualize:
        v = v * math.sqrt(252)
    return v.to_numpy()


def _rolling_momentum(closes: np.ndarray, horizon: int) -> np.ndarray:
    """closes[t]/closes[t-horizon] - 1, vectorized (pandas pct_change)."""
    s = pd.Series(np.asarray(closes, dtype=float))
    return s.pct_change(periods=horizon).to_numpy()


def _rolling_avg_pairwise_corr(returns: pd.DataFrame, window: int) -> np.ndarray:
    """Average pairwise correlation across columns at each row `t`, using the
    window [t-window, t). Uses the "sum of standardized columns" identity
    (sum_ij corr_ij = ||sum_i z_i||^2 / (w-1)) so it's O(T * window * N)
    instead of O(T * N^2) from building a full correlation matrix per day.
    """
    R_ = returns.to_numpy(dtype=float)
    T, N = R_.shape
    out = np.full(T, np.nan)
    if N < 2:
        return out
    for t in range(window, T + 1):
        w = R_[t - window:t, :]
        valid_cols = ~np.isnan(w).any(axis=0)
        w = w[:, valid_cols]
        n = w.shape[1]
        if n < 2:
            continue
        mean = w.mean(axis=0)
        std = w.std(axis=0, ddof=1)
        std_safe = np.where(std == 0, np.nan, std)
        z = (w - mean) / std_safe
        z = np.nan_to_num(z, nan=0.0)
        s = z.sum(axis=1)
        sum_corr = float(np.dot(s, s)) / (window - 1)
        avg_corr = (sum_corr - n) / (n * n - n)
        out[t - 1] = avg_corr
    return out


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------

def _volatility(index_closes: np.ndarray, windows: tuple) -> ElementReading:
    rets = R.daily_returns(index_closes)
    if rets.size < min(windows) + 5:
        return ElementReading(
            available=False, value=None, raw={},
            reason="insufficient index price history to compute realised volatility",
        )
    per_window = {}
    zs = []
    for w in windows:
        series = _rolling_std(rets, w, annualize=True)
        stat = _own_history_stat(series)
        per_window[str(w)] = {
            "realized_vol": stat.latest,
            "history_mean": stat.history_mean,
            "history_std": stat.history_std,
            "z": stat.z,
            "n_obs": stat.n_obs,
        }
        if stat.z is not None:
            zs.append(stat.z)
    value = float(np.mean(zs)) if zs else None
    return ElementReading(
        available=value is not None,
        value=value,
        raw={
            "windows": per_window,
            "implied_vol": None,
            "implied_vol_term_structure": None,
        },
        notes=[
            "implied volatility / vol term structure not available: this engine "
            "has no live options/implied-vol feed wired in (would need a "
            "market-data vendor); reporting realised volatility only."
        ],
    )


def _dispersion(constituent_returns: pd.DataFrame) -> ElementReading:
    if constituent_returns.shape[1] < 2 or constituent_returns.shape[0] < 5:
        return ElementReading(
            available=False, value=None, raw={},
            reason="fewer than 2 constituents or 5 observations — cannot compute "
                   "cross-sectional dispersion",
        )
    series = constituent_returns.std(axis=1, ddof=1, skipna=True).to_numpy()
    stat = _own_history_stat(series)
    return ElementReading(
        available=stat.z is not None,
        value=stat.z,
        raw={
            "cross_sectional_std": stat.latest,
            "history_mean": stat.history_mean,
            "history_std": stat.history_std,
            "n_obs": stat.n_obs,
        },
        reason=None if stat.z is not None else "insufficient history to standardize",
    )


def _correlation(constituent_returns: pd.DataFrame, window: int, roc_lag: int) -> ElementReading:
    if constituent_returns.shape[1] < 2 or constituent_returns.shape[0] < window + roc_lag:
        return ElementReading(
            available=False, value=None, raw={},
            reason="fewer than 2 constituents or not enough history for the "
                   f"{window}-day correlation window plus a {roc_lag}-day "
                   "rate-of-change lag",
        )
    corr_series = _rolling_avg_pairwise_corr(constituent_returns, window)
    level_stat = _own_history_stat(corr_series)
    roc_series = pd.Series(corr_series).diff(periods=roc_lag).to_numpy()
    roc_stat = _own_history_stat(roc_series)
    zs = [z for z in (level_stat.z, roc_stat.z) if z is not None]
    value = float(np.mean(zs)) if zs else None
    return ElementReading(
        available=value is not None,
        value=value,
        raw={
            "avg_pairwise_corr": level_stat.latest,
            "z_level": level_stat.z,
            "rate_of_change": roc_stat.latest,
            "z_rate_of_change": roc_stat.z,
            "window": window,
            "roc_lag_days": roc_lag,
        },
        reason=None if value is not None else "insufficient history to standardize",
    )


def _breadth(
    constituent_returns: pd.DataFrame,
    constituent_closes: Optional[pd.DataFrame],
    ma_window: int,
) -> ElementReading:
    if constituent_closes is None:
        # Reconstruct a price level series from returns if the caller only has
        # returns; still genuinely computed, not fabricated.
        constituent_closes = (1.0 + constituent_returns.fillna(0.0)).cumprod()

    if constituent_closes.shape[1] < 2 or constituent_closes.shape[0] < ma_window + 5:
        return ElementReading(
            available=False, value=None, raw={},
            reason=f"fewer than 2 constituents or not enough history for a "
                   f"{ma_window}-day moving average",
        )

    ma = constituent_closes.rolling(ma_window, min_periods=ma_window).mean()
    above = (constituent_closes > ma)
    valid = ma.notna()
    share_above = (above & valid).sum(axis=1) / valid.sum(axis=1).replace(0, np.nan)
    share_stat = _own_history_stat(share_above.to_numpy())

    advancers = (constituent_returns > 0).sum(axis=1)
    decliners = (constituent_returns < 0).sum(axis=1)
    total = constituent_returns.notna().sum(axis=1).replace(0, np.nan)
    ad_balance = (advancers - decliners) / total
    ad_stat = _own_history_stat(ad_balance.to_numpy())

    zs = [z for z in (share_stat.z, ad_stat.z) if z is not None]
    value = float(np.mean(zs)) if zs else None
    return ElementReading(
        available=value is not None,
        value=value,
        raw={
            "share_above_own_ma": share_stat.latest,
            "z_share_above_own_ma": share_stat.z,
            "advance_decline_balance": ad_stat.latest,
            "z_advance_decline_balance": ad_stat.z,
            "ma_window": ma_window,
        },
        reason=None if value is not None else "insufficient history to standardize",
    )


def _trend(index_closes: np.ndarray, horizons: tuple) -> ElementReading:
    if len(index_closes) < max(horizons) + 5:
        return ElementReading(
            available=False, value=None, raw={},
            reason="insufficient index price history for the longest trend horizon",
        )
    per_horizon = {}
    zs = []
    latest_signs = []
    for h in horizons:
        series = _rolling_momentum(index_closes, h)
        stat = _own_history_stat(series)
        per_horizon[str(h)] = {
            "momentum": stat.latest,
            "z": stat.z,
            "n_obs": stat.n_obs,
        }
        if stat.z is not None:
            zs.append(stat.z)
        if stat.latest is not None and not math.isnan(stat.latest):
            latest_signs.append(1 if stat.latest > 0 else (-1 if stat.latest < 0 else 0))

    value = float(np.mean(zs)) if zs else None
    sign_consistency = None
    if latest_signs:
        pos = sum(1 for s in latest_signs if s > 0)
        neg = sum(1 for s in latest_signs if s < 0)
        sign_consistency = max(pos, neg) / len(latest_signs)

    return ElementReading(
        available=value is not None,
        value=value,
        raw={
            "horizons": per_horizon,
            "sign_consistency": sign_consistency,
        },
        reason=None if value is not None else "insufficient history to standardize",
    )


def _slippage(realized_fills: Optional[list]) -> ElementReading:
    if not realized_fills:
        return ElementReading(
            available=False,
            value=None,
            raw={},
            reason="no realised execution/fill data available — this engine does "
                   "not yet capture live broker fills, so realised-vs-expected "
                   "execution cost cannot be computed (would require fabricating "
                   "a number)",
        )
    slips = [
        float(f["realized_cost_bps"]) - float(f["expected_cost_bps"])
        for f in realized_fills
        if f.get("realized_cost_bps") is not None and f.get("expected_cost_bps") is not None
    ]
    if not slips:
        return ElementReading(
            available=False, value=None, raw={},
            reason="fill records present but none carry both expected and "
                   "realised cost — cannot compute slippage without fabricating it",
        )
    mean_slip = float(np.mean(slips))
    stat = _own_history_stat(np.array(slips))
    value = stat.z  # None if too few fills to standardize — but mean_slip is real
    notes = []
    if value is None:
        notes.append(
            "fewer than 2 fills — mean slippage is real but cannot yet be "
            "standardized against its own history"
        )
    return ElementReading(
        available=True,
        value=value,
        raw={
            "mean_slippage_bps": mean_slip,
            "n_fills": len(slips),
            "history_mean": stat.history_mean,
            "history_std": stat.history_std,
        },
        notes=notes,
    )


def _liquidity(
    index_highs: Optional[np.ndarray],
    index_lows: Optional[np.ndarray],
    volume_series: Optional[np.ndarray],
    spread_window: int,
) -> ElementReading:
    if index_highs is None and volume_series is None:
        return ElementReading(
            available=False, value=None, raw={},
            reason="no spread (high/low) or volume history supplied — Incepta "
                   "today only exposes a single-snapshot Corwin-Schultz spread "
                   "per security (models/scoring risk_snapshot), not an "
                   "aggregated liquidity time series, and no volume feed is "
                   "wired into this state vector yet",
        )

    zs = []
    raw: dict = {"spread_window": spread_window}

    if index_highs is not None and index_lows is not None:
        highs = np.asarray(index_highs, dtype=float)
        lows = np.asarray(index_lows, dtype=float)
        n = min(highs.size, lows.size)
        spread_series = np.full(n, np.nan)
        for t in range(spread_window, n + 1):
            spread_series[t - 1] = R.corwin_schultz_spread(
                highs[t - spread_window:t], lows[t - spread_window:t]
            )
        stat = _own_history_stat(spread_series)
        # higher spread = LESS liquid, so invert sign for the liquidity reading
        z_liq_from_spread = -stat.z if stat.z is not None else None
        raw["spread_bps"] = stat.latest * 1e4 if stat.latest is not None else None
        raw["z_liquidity_from_spread"] = z_liq_from_spread
        if z_liq_from_spread is not None:
            zs.append(z_liq_from_spread)

    if volume_series is not None:
        stat = _own_history_stat(np.asarray(volume_series, dtype=float))
        raw["volume"] = stat.latest
        raw["z_liquidity_from_volume"] = stat.z
        if stat.z is not None:
            zs.append(stat.z)

    value = float(np.mean(zs)) if zs else None
    return ElementReading(
        available=value is not None,
        value=value,
        raw=raw,
        reason=None if value is not None else "insufficient history to standardize",
    )


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def compute_state_vector(
    *,
    as_of: date,
    index_closes: np.ndarray,
    constituent_returns: pd.DataFrame,
    constituent_closes: Optional[pd.DataFrame] = None,
    index_highs: Optional[np.ndarray] = None,
    index_lows: Optional[np.ndarray] = None,
    volume_series: Optional[np.ndarray] = None,
    realized_fills: Optional[list] = None,
    vol_windows: tuple = (21, 63, 252),
    trend_horizons: tuple = (21, 63, 252),
    breadth_ma_window: int = 200,
    corr_window: int = 63,
    corr_roc_lag: int = 21,
    liquidity_spread_window: int = 21,
) -> StateVector:
    """Pure function: every input is data the caller hands in (index prices,
    a constituent-returns panel, optionally highs/lows/volume/fills). Nothing
    is read from disk or the network here — that's the caller's job (e.g. the
    store), keeping this module trivially unit-testable.

    `constituent_returns` is a (dates x tickers) DataFrame of daily simple
    returns, oldest row first, aligned to `index_closes`'s date axis.
    """
    return StateVector(
        schema_version=SCHEMA_VERSION,
        element_order=list(ELEMENT_ORDER),
        as_of=as_of,
        volatility=_volatility(index_closes, vol_windows),
        dispersion=_dispersion(constituent_returns),
        correlation=_correlation(constituent_returns, corr_window, corr_roc_lag),
        breadth=_breadth(constituent_returns, constituent_closes, breadth_ma_window),
        trend=_trend(index_closes, trend_horizons),
        slippage=_slippage(realized_fills),
        liquidity=_liquidity(index_highs, index_lows, volume_series, liquidity_spread_window),
    )


# ---------------------------------------------------------------------------
# Plain-language rendering (IMP-05)
# ---------------------------------------------------------------------------

def _phrase_volatility(e: ElementReading) -> str:
    if not e.available:
        return f"volatility: unavailable ({e.reason})"
    z = e.value
    base = "elevated" if z > 1.5 else ("subdued" if z < -1.5 else "normal")
    return f"volatility {base}"


def _phrase_dispersion(e: ElementReading) -> str:
    if not e.available:
        return f"dispersion: unavailable ({e.reason})"
    z = e.value
    if z > 1.0:
        return "dispersion rising"
    if z < -1.0:
        return "dispersion compressed"
    return "dispersion typical"


def _phrase_correlation(e: ElementReading) -> str:
    if not e.available:
        return f"correlation: unavailable ({e.reason})"
    z_level = e.raw.get("z_level")
    z_roc = e.raw.get("z_rate_of_change")
    if z_roc is not None and z_roc > 1.0:
        return "correlation fusing"  # rising fast — names moving together
    if z_level is not None and z_level < -1.0:
        return "correlation breaking down"
    return "correlation typical"


def _phrase_breadth(e: ElementReading) -> str:
    if not e.available:
        return f"breadth: unavailable ({e.reason})"
    z = e.value
    if z < -1.0:
        return "breadth narrow"
    if z > 1.0:
        return "breadth broad"
    return "breadth typical"


def _phrase_trend(e: ElementReading) -> str:
    if not e.available:
        return f"trend: unavailable ({e.reason})"
    z = e.value
    sc = e.raw.get("sign_consistency")
    direction = "up" if z > 0 else ("down" if z < 0 else "flat")
    if sc is not None and sc < 0.6:
        return "trend mixed across horizons"
    return f"trend {direction}, broadly confirmed across horizons"


def _phrase_slippage(e: ElementReading) -> str:
    if not e.available:
        return f"slippage: not measurable ({e.reason})"
    if e.value is None:
        return "slippage: measured but not yet standardized (too few fills)"
    return "slippage elevated vs own history" if e.value > 1.0 else "slippage in line with own history"


def _phrase_liquidity(e: ElementReading) -> str:
    if not e.available:
        return f"liquidity: unavailable ({e.reason})"
    z = e.value
    if z < -1.0:
        return "liquidity thin"
    if z > 1.0:
        return "liquidity ample"
    return "liquidity normal"


_PHRASE_FN = {
    "volatility": _phrase_volatility,
    "dispersion": _phrase_dispersion,
    "correlation": _phrase_correlation,
    "breadth": _phrase_breadth,
    "trend": _phrase_trend,
    "slippage": _phrase_slippage,
    "liquidity": _phrase_liquidity,
}


def plain_language(vector: StateVector) -> dict:
    """Map each of the seven elements to a short human phrase for the
    dashboard (IMP-05). Keys follow `ELEMENT_ORDER`."""
    out = {}
    for name in ELEMENT_ORDER:
        element: ElementReading = getattr(vector, name)
        out[name] = _PHRASE_FN[name](element)
    return out


# ---------------------------------------------------------------------------
# Export (mirrors export.py's `_clean` / build_*/write_* pattern)
# ---------------------------------------------------------------------------

def _clean(obj):
    """Make values JSON-safe: numpy scalars -> python, NaN/inf -> None."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    if hasattr(obj, "item"):  # numpy scalar
        obj = obj.item()
    if isinstance(obj, float) and (math.isnan(obj) or math.isinf(obj)):
        return None
    return obj


def build_state_export(vector: StateVector) -> dict:
    payload = {
        "schema_version": vector.schema_version,
        "engine_version": __version__,
        "generated_at": datetime.now().isoformat(),
        "as_of": vector.as_of,
        "state_vector": asdict(vector),
        "plain_language": plain_language(vector),
        "disclaimer": DISCLAIMER,
    }
    return _clean(payload)


def write_state_export(payload: dict, paths: list) -> list:
    import json

    written = []
    for p in paths:
        p = Path(p)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
        written.append(str(p))
    return written

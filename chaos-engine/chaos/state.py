"""CHAOS-01 — the dislocation state engine.

Eight components, each documented and unit-testable on its own, are combined
into a single chaos index in [0, 1] and fed through an explicit STATE MACHINE
with hysteresis (`run_state_machine`) that turns the index into one of four
labels: calm / stressed / dislocated / cascade.

Inputs are plain pandas OHLCV bar data — this module has no network access
and no live data dependency. Callers supply intraday bars (a DatetimeIndex at
whatever bar frequency the caller chose, documented per-function as "bars"
rather than a fixed wall-clock unit) plus, optionally, a cross-sectional
universe price panel (for the two components that are inherently
cross-sectional) and quote data (for the two components that are better
measured with quotes than with OHLCV alone).

HONESTY: several components degrade gracefully to `available=False` rather
than fabricate a number:
  * range/spread deterioration's spread half is null without bid/ask quotes;
  * order-flow imbalance falls back to a documented bar-level tick-rule
    APPROXIMATION when no quotes are supplied, and says so;
  * the novelty aggregate is external-input-only — there is no news pipeline
    in this repository, and this module will never invent one.

Everything below operates on data the caller provides; nothing here fetches
prices, news, or quotes from anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import ComponentConfig, StateConfig

STATE_LEVELS: tuple[str, ...] = ("calm", "stressed", "dislocated", "cascade")

# Combination weights for the eight components. A component that is
# unavailable for a given bar is dropped from BOTH numerator and denominator
# (see `compute_chaos_index`) rather than being imputed with a neutral value —
# an unavailable component contributes nothing, not a fabricated "average".
DEFAULT_WEIGHTS: dict[str, float] = {
    "vol_ratio": 0.22,
    "volume_z": 0.15,
    "range_ratio": 0.08,
    "dispersion": 0.15,
    "corr_shift": 0.15,
    "flow_imbalance": 0.10,
    "jump": 0.15,
    "novelty": 0.05,
}


def _clip01(x):
    return np.clip(x, 0.0, 1.0)


def _rolling_zscore(x: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """z-score of `x` against its own trailing history. Used for components
    (dispersion, correlation shift, jump statistic) that have no fixed
    physical scale and so are judged against what is normal for THIS series,
    not an absolute number."""
    mp = min_periods or window
    m = x.rolling(window, min_periods=mp).mean()
    s = x.rolling(window, min_periods=mp).std(ddof=0)
    return (x - m) / s.replace(0.0, np.nan)


# ---------------------------------------------------------------------------
# 1. Volatility ratio — realised vol over fast bars vs trailing slower window.
# ---------------------------------------------------------------------------


def realized_vol(log_returns: pd.Series, window: int) -> pd.Series:
    """Trailing realised volatility (raw, un-annualised standard deviation of
    log returns over `window` bars)."""
    return log_returns.rolling(window, min_periods=window).std(ddof=0)


def volatility_ratio(bars: pd.DataFrame, cfg: ComponentConfig | None = None) -> pd.Series:
    """Realised vol over `fast_vol_window` bars divided by realised vol over
    the trailing `slow_vol_window` bars. ~1.0 in calm markets; rises sharply
    when short-horizon volatility detaches from its own recent trailing
    level — the textbook first sign of a dislocation."""
    cfg = cfg or ComponentConfig()
    logret = np.log(bars["close"] / bars["close"].shift(1))
    fast = realized_vol(logret, cfg.fast_vol_window)
    slow = realized_vol(logret, cfg.slow_vol_window)
    return fast / slow.replace(0.0, np.nan)


def _score_vol_ratio(x: pd.Series) -> pd.Series:
    # calm: ratio ~1.0 -> score 0. Score saturates at 1.0 once ratio reaches 3x.
    return _clip01((x - 1.0) / 2.0)


# ---------------------------------------------------------------------------
# 2. Volume surprise — z-score against the SAME minute-of-day across trailing
#    sessions, so the normal intraday U-shaped volume curve is controlled for.
# ---------------------------------------------------------------------------


def volume_surprise(bars: pd.DataFrame, cfg: ComponentConfig | None = None) -> pd.Series:
    """Volume z-score vs the trailing `volume_lookback_sessions` sessions AT
    THE SAME MINUTE-OF-DAY. Naively z-scoring raw volume against its own
    recent trailing bars would flag the normal open/close volume spike as
    "surprising" every single day; comparing minute-of-day to minute-of-day
    across sessions removes that seasonal shape and leaves only genuine
    surprise."""
    cfg = cfg or ComponentConfig()
    idx = bars.index
    session = pd.Series(idx.normalize(), index=idx)
    minute = pd.Series(idx.hour * 60 + idx.minute, index=idx)
    vol = bars["volume"].astype(float)

    frame = pd.DataFrame({"session": session, "minute": minute, "volume": vol})
    pivot = frame.pivot_table(index="session", columns="minute", values="volume", aggfunc="mean")

    n = cfg.volume_lookback_sessions
    trailing_mean = pivot.shift(1).rolling(n, min_periods=n).mean()
    trailing_std = pivot.shift(1).rolling(n, min_periods=n).std(ddof=0)
    z = (pivot - trailing_mean) / trailing_std.replace(0.0, np.nan)

    # Avoid DataFrame.stack() here: pandas versions disagree on whether/how
    # `dropna` is accepted (removed entirely in pandas >= 3.0), so look values
    # up via a plain nested dict instead — behaviourally identical (including
    # NaN pass-through) and stable across pandas versions.
    row_lookup = z.to_dict(orient="index")  # {session: {minute: value}}
    out = np.array(
        [row_lookup.get(s, {}).get(m, np.nan) for s, m in zip(frame["session"], frame["minute"])],
        dtype=float,
    )
    return pd.Series(out, index=idx)


def _score_volume_z(z: pd.Series) -> pd.Series:
    # 0 at z<=0 (volume at or below normal for this minute-of-day); saturates
    # at a 6-sigma surprise.
    return _clip01(z / 6.0)


# ---------------------------------------------------------------------------
# 3. Range/spread deterioration — high-low range vs close-to-close move.
#    Spread is optional/null when no quote data is supplied (documented).
# ---------------------------------------------------------------------------


def range_deterioration(
    bars: pd.DataFrame, quotes: pd.DataFrame | None = None
) -> tuple[pd.Series, pd.Series | None]:
    """Returns (range_close_ratio, spread_bps_or_None).

    range_close_ratio = (high - low) / |close - prev_close|. A ratio that
    balloons relative to its own history means intrabar range is expanding
    faster than the net move — noisy, two-way, indecisive price action, one
    hallmark of a dislocating market.

    spread_bps requires bid/ask QUOTE data, which does not exist in synthetic
    OHLCV bars and is not available from any live feed wired into this repo.
    When `quotes` (a DataFrame with 'bid'/'ask' columns, indexed like `bars`)
    is supplied, spread is computed for real; otherwise this function returns
    None for the second element and the caller must mark that component
    unavailable rather than invent a spread."""
    rng = bars["high"] - bars["low"]
    close_move = (bars["close"] - bars["close"].shift(1)).abs()
    ratio = rng / close_move.replace(0.0, np.nan)

    spread_bps = None
    if quotes is not None and {"bid", "ask"}.issubset(quotes.columns):
        q = quotes.reindex(bars.index)
        mid = (q["ask"] + q["bid"]) / 2.0
        spread_bps = ((q["ask"] - q["bid"]) / mid.replace(0.0, np.nan)) * 1e4
    return ratio, spread_bps


def _score_range_ratio(x: pd.Series) -> pd.Series:
    # A ratio near 1-2 is ordinary; score saturates by ~5x.
    return _clip01((x - 1.0) / 4.0)


# ---------------------------------------------------------------------------
# 4. Cross-sectional dispersion — std of returns across a universe.
# ---------------------------------------------------------------------------


def cross_sectional_dispersion(prices_panel: pd.DataFrame, window: int) -> pd.Series:
    """Std, across tickers (columns), of each ticker's trailing `window`-bar
    log return. `prices_panel` is a wide DataFrame: rows = time, columns =
    tickers, values = price. Requires >= 2 tickers; a single-column panel
    returns all-NaN (dispersion is undefined for a universe of one)."""
    if prices_panel.shape[1] < 2:
        return pd.Series(np.nan, index=prices_panel.index)
    interval_ret = np.log(prices_panel / prices_panel.shift(window))
    return interval_ret.std(axis=1, ddof=0)


def _score_dispersion(x: pd.Series, cfg: ComponentConfig) -> pd.Series:
    z = _rolling_zscore(x, max(cfg.corr_trailing_window, 30))
    return _clip01(z / 3.0)


# ---------------------------------------------------------------------------
# 5. Correlation shift — change in average pairwise correlation, short window
#    vs its own trailing level.
# ---------------------------------------------------------------------------


def _avg_pairwise_corr(logret: pd.DataFrame, window: int) -> pd.Series:
    """Average OFF-DIAGONAL pairwise correlation across all ticker pairs, at
    each point in time, over a trailing `window`-bar rolling correlation."""
    n = logret.shape[1]
    if n < 2:
        return pd.Series(np.nan, index=logret.index)
    roll = logret.rolling(window, min_periods=window).corr()
    iu = np.triu_indices(n, k=1)
    out = np.full(len(logret.index), np.nan)
    for i, t in enumerate(logret.index):
        try:
            block = roll.loc[t].to_numpy()
        except KeyError:
            continue
        offdiag = block[iu]
        if np.isfinite(offdiag).any():
            out[i] = np.nanmean(offdiag)
    return pd.Series(out, index=logret.index)


def correlation_shift(
    prices_panel: pd.DataFrame, cfg: ComponentConfig | None = None
) -> pd.Series:
    """Average pairwise correlation over a SHORT window minus average pairwise
    correlation over its own TRAILING (longer) window. Positive => names are
    suddenly moving together more than their recent norm — a classic
    correlation-breakdown / everything-sells-together signature of stress."""
    cfg = cfg or ComponentConfig()
    logret = np.log(prices_panel / prices_panel.shift(1))
    short = _avg_pairwise_corr(logret, cfg.corr_short_window)
    trailing = _avg_pairwise_corr(logret, cfg.corr_trailing_window)
    return short - trailing


def _score_corr_shift(x: pd.Series) -> pd.Series:
    # Correlation shift lives in [-2, 2] in principle, [-0.5, 0.5] in
    # practice. Only a RISE in correlation is treated as stress-like.
    return _clip01(x / 0.5)


# ---------------------------------------------------------------------------
# 6. Order flow imbalance — signed volume from an approximate tick rule, or
#    quote-midpoint comparison where quotes exist.
# ---------------------------------------------------------------------------


def order_flow_imbalance(
    bars: pd.DataFrame, cfg: ComponentConfig | None = None, quotes: pd.DataFrame | None = None
) -> tuple[pd.Series, str]:
    """Returns (imbalance, method).

    imbalance in [-1, 1]: rolling sum of signed volume / rolling sum of
    volume, over `dispersion_window` bars (reused as the flow window — both
    are "short interval" measures).

    APPROXIMATION, documented: a true tick rule (Lee & Ready 1991) classifies
    individual TRADES against the prevailing quote midpoint. This repo has no
    trade-level tape. Two fallbacks, in order of preference:
      * quote-midpoint comparison: if `quotes` (bid/ask, indexed like `bars`)
        is supplied, each bar's close is classified vs. that bar's own quote
        midpoint (buy-like if close > mid, sell-like if close < mid) —
        `method="quote_midpoint"`.
      * bar-level tick-rule approximation: otherwise, each bar's direction is
        the sign of close vs. the PRIOR bar's close (a coarse, bar-granularity
        stand-in for the tick rule; a zero-return bar carries forward the
        previous bar's sign, matching the classic tick-rule convention for
        ties) — `method="tick_rule_bar_close"`. This is a real approximation,
        not a measurement, and is reported as such via `method`."""
    cfg = cfg or ComponentConfig()
    vol = bars["volume"].astype(float)

    if quotes is not None and {"bid", "ask"}.issubset(quotes.columns):
        q = quotes.reindex(bars.index)
        mid = (q["ask"] + q["bid"]) / 2.0
        sign = np.sign(bars["close"] - mid)
        method = "quote_midpoint"
    else:
        raw_sign = np.sign(bars["close"] - bars["close"].shift(1))
        sign = raw_sign.replace(0.0, np.nan).ffill().fillna(0.0)
        method = "tick_rule_bar_close"

    signed_vol = sign * vol
    w = cfg.dispersion_window
    num = signed_vol.rolling(w, min_periods=w).sum()
    den = vol.rolling(w, min_periods=w).sum()
    imbalance = num / den.replace(0.0, np.nan)
    return imbalance, method


def _score_flow_imbalance(x: pd.Series) -> pd.Series:
    return _clip01(x.abs())


# ---------------------------------------------------------------------------
# 7. Jump indicator — bipower variation vs realised variance (Barndorff-
#    Nielsen & Shephard).
# ---------------------------------------------------------------------------


def bipower_variation(log_returns) -> float:
    """Bipower variation, the standard jump-robust estimator of integrated
    variance.

        BV = mu1^-2 * sum_{i=2}^{n} |r_i| * |r_{i-1}|,   mu1 = E|Z| = sqrt(2/pi)
           = (pi/2) * sum_{i=2}^{n} |r_i| * |r_{i-1}|

    Unlike realised variance (sum r_i^2), a single large |r_i| enters BV only
    once, multiplied by its (typically ordinary-sized) neighbour, rather than
    being squared — so BV stays a consistent estimator of the DIFFUSIVE part
    of variance even when the path contains jumps, while RV does not. The gap
    (RV - BV) is therefore attributable to jump activity.

    Source: Barndorff-Nielsen, O.E. and Shephard, N. (2004), "Power and
    Bipower Variation with Stochastic Volatility and Jumps", Journal of
    Financial Econometrics 2(1), 1-37; and Barndorff-Nielsen & Shephard
    (2006), "Econometrics of Testing for Jumps in Financial Economics Using
    Bipower Variation", Journal of Financial Econometrics 4(1), 1-30."""
    r = np.asarray(log_returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size < 2:
        return float("nan")
    return float((np.pi / 2.0) * np.sum(np.abs(r[1:]) * np.abs(r[:-1])))


def realized_variance(log_returns) -> float:
    r = np.asarray(log_returns, dtype=float)
    r = r[np.isfinite(r)]
    if r.size == 0:
        return float("nan")
    return float(np.sum(r ** 2))


def tripower_quarticity(log_returns) -> float:
    """Tripower quarticity — the jump-robust quarticity estimator used to
    scale the BNS jump test statistic (see `jump_test_statistic`). Same
    source as `bipower_variation`."""
    r = np.asarray(log_returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 3:
        return float("nan")
    from scipy.special import gamma

    mu43 = 2.0 ** (2.0 / 3.0) * gamma(7.0 / 6.0) / gamma(0.5)
    mu43_inv3 = mu43 ** (-3.0)
    terms = (
        np.abs(r[2:]) ** (4.0 / 3.0)
        * np.abs(r[1:-1]) ** (4.0 / 3.0)
        * np.abs(r[:-2]) ** (4.0 / 3.0)
    )
    return float(n * mu43_inv3 * np.sum(terms))


# BNS ratio-statistic scaling constant: (pi/2)^2 + pi - 5.
_BNS_THETA = (np.pi / 2.0) ** 2 + np.pi - 5.0


def jump_test_statistic(log_returns) -> tuple[float, float]:
    """Ratio-adjusted Barndorff-Nielsen & Shephard jump test.

    Returns (relative_jump, z_stat):
      relative_jump = (RV - BV) / RV,  in [~0, 1) — the fraction of measured
        variance attributable to jumps rather than continuous diffusion.
      z_stat: asymptotically N(0,1) under the null of NO jumps (Barndorff-
        Nielsen & Shephard 2006, eq. for the ratio statistic); large |z_stat|
        rejects the null, i.e. says the discontinuity is unlikely to be
        elevated-but-continuous diffusion."""
    r = np.asarray(log_returns, dtype=float)
    r = r[np.isfinite(r)]
    n = r.size
    if n < 3:
        return float("nan"), float("nan")
    rv = realized_variance(r)
    bv = bipower_variation(r)
    if not np.isfinite(rv) or rv <= 0:
        return float("nan"), float("nan")
    rj = (rv - bv) / rv
    tq = tripower_quarticity(r)
    if not np.isfinite(tq) or bv <= 0:
        return float(rj), float("nan")
    denom = np.sqrt(_BNS_THETA * (1.0 / n) * max(1.0, tq / (bv ** 2)))
    z = rj / denom if denom > 0 else float("nan")
    return float(rj), float(z)


def jump_indicator(
    bars: pd.DataFrame, cfg: ComponentConfig | None = None
) -> tuple[pd.Series, pd.Series]:
    """Rolling BNS jump test over the trailing `jump_window` log returns.
    Returns (relative_jump, z_stat) series, NaN until `min_bars_for_component`
    finite returns are available in the window."""
    cfg = cfg or ComponentConfig()
    logret = np.log(bars["close"] / bars["close"].shift(1)).to_numpy()
    n = len(bars)
    rj_out = np.full(n, np.nan)
    z_out = np.full(n, np.nan)
    w = cfg.jump_window
    minb = cfg.min_bars_for_component
    for i in range(n):
        lo = max(0, i - w + 1)
        window = logret[lo : i + 1]
        window = window[np.isfinite(window)]
        if window.size >= minb:
            rj, z = jump_test_statistic(window)
            rj_out[i] = rj
            z_out[i] = z
    return pd.Series(rj_out, index=bars.index), pd.Series(z_out, index=bars.index)


def _score_jump(z: pd.Series) -> pd.Series:
    # |z| >= ~2 starts to reject "no jump" at conventional significance;
    # saturate the score by |z| = 6.
    return _clip01(z.abs() / 6.0)


# ---------------------------------------------------------------------------
# 8. Novelty aggregate — external input ONLY. No news pipeline exists here.
# ---------------------------------------------------------------------------


def novelty_aggregate(
    external: pd.Series | None, index: pd.Index
) -> tuple[pd.Series, bool]:
    """Returns (novelty_value_in_[0,1]_or_NaN, available).

    There is no real news/novelty pipeline anywhere in this repository. This
    function NEVER fabricates a value. If the caller has one (e.g. a proper
    news-clustering novelty score from elsewhere), pass it as `external`
    (a Series aligned/reindexable to `index`, values expected in [0, 1]) and
    it is used as-is (clipped to [0, 1] defensively). Otherwise this returns
    an all-NaN series and `available=False`, and downstream consumers
    (the chaos index combination, the export) must treat that as "no
    information", not as "neutral" — it is simply excluded from the weighted
    combination rather than injected as a 0.5 guess."""
    if external is None:
        return pd.Series(np.nan, index=index), False
    aligned = external.reindex(index)
    return aligned.clip(0.0, 1.0), True


# ---------------------------------------------------------------------------
# Combination — components -> single chaos index in [0, 1].
# ---------------------------------------------------------------------------


def compute_chaos_index(
    scores: pd.DataFrame, available: pd.DataFrame, weights: dict[str, float] | None = None
) -> pd.Series:
    """Weighted average of per-component scores (each already mapped into
    [0, 1] by that component's `_score_*` transform), where an unavailable
    component is dropped from BOTH numerator and denominator (weights are
    renormalised over whatever is actually available at that bar) rather than
    being imputed with a neutral fill value."""
    weights = weights or DEFAULT_WEIGHTS
    w = pd.Series(weights).reindex(scores.columns).fillna(0.0)

    avail_mask = available.astype(bool) & scores.notna()
    eff_scores = scores.where(avail_mask)

    weighted = eff_scores.mul(w, axis=1)
    denom = avail_mask.astype(float).mul(w, axis=1).sum(axis=1)
    numer = weighted.sum(axis=1, skipna=True)
    return numer / denom.replace(0.0, np.nan)


# ---------------------------------------------------------------------------
# State machine — hysteresis + minimum dwell time.
# ---------------------------------------------------------------------------


def run_state_machine(chaos_index: pd.Series, cfg: StateConfig | None = None) -> pd.Series:
    """Turn a chaos-index series into a sequence of {calm, stressed,
    dislocated, cascade} labels via an explicit state machine:

      * ESCALATING (calm -> stressed -> dislocated -> cascade) requires the
        index to cross that level's UPPER "enter" threshold.
      * DE-ESCALATING requires the index to drop below a DISTINCTLY LOWER
        "exit" threshold for the level being left — never the same value as
        the entry threshold. This is what makes it hysteresis rather than a
        threshold snapshot: a value sitting between a level's exit and the
        next level's enter threshold changes nothing.
      * A minimum of `min_dwell_bars` bars must elapse since the last actual
        state change before another one is allowed, regardless of what the
        index does in between. A transition that is "due" but blocked by the
        dwell timer is simply re-evaluated (and may or may not still apply)
        on each subsequent bar.

    NaN chaos-index bars (warm-up) hold the current state and do not count
    toward escalation, but DO count toward the dwell timer.

    Deterministic: this is a pure function of the input series and config —
    replaying the same series always produces the same label sequence
    (see tests/test_state.py::test_determinism)."""
    cfg = cfg or StateConfig()
    enter = [-np.inf, cfg.enter_stressed, cfg.enter_dislocated, cfg.enter_cascade]
    exit_ = [-np.inf, cfg.exit_stressed, cfg.exit_dislocated, cfg.exit_cascade]

    values = chaos_index.to_numpy()
    labels: list[str] = []
    cur_rank = 0
    # Start "ready" so an early, clearly-warranted transition isn't blocked by
    # an artificial startup lockout.
    bars_since_change = cfg.min_dwell_bars

    for x in values:
        if np.isfinite(x):
            r_up = max(r for r in range(4) if x >= enter[r])
            r_down = max(r for r in range(4) if x >= exit_[r])
            target = cur_rank
            if cur_rank < r_up:
                target = r_up
            elif cur_rank > r_down:
                target = r_down
            if target != cur_rank and bars_since_change >= cfg.min_dwell_bars:
                cur_rank = target
                bars_since_change = 0
        labels.append(STATE_LEVELS[cur_rank])
        bars_since_change += 1

    return pd.Series(labels, index=chaos_index.index, name="state_label")


# ---------------------------------------------------------------------------
# Orchestration — compute all eight components + the index + the state label
# in one call, over a single ticker's bars.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StateResult:
    frame: pd.DataFrame  # every raw value, availability flag, score, and the index/label

    @property
    def chaos_index(self) -> pd.Series:
        return self.frame["chaos_index"]

    @property
    def state_label(self) -> pd.Series:
        return self.frame["state_label"]

    def latest(self) -> pd.Series:
        return self.frame.iloc[-1]


def compute_state(
    bars: pd.DataFrame,
    comp_cfg: ComponentConfig | None = None,
    state_cfg: StateConfig | None = None,
    universe_prices: pd.DataFrame | None = None,
    quotes: pd.DataFrame | None = None,
    novelty: pd.Series | None = None,
    weights: dict[str, float] | None = None,
) -> StateResult:
    """Compute all eight CHAOS-01 components for one ticker's bars, combine
    into a chaos index, and run it through the hysteresis state machine.

    `universe_prices` (wide, columns = tickers, values = close) is required
    for the two genuinely cross-sectional components (dispersion, correlation
    shift); if omitted they report unavailable rather than being silently
    computed on a universe of one."""
    comp_cfg = comp_cfg or ComponentConfig()
    state_cfg = state_cfg or StateConfig()
    idx = bars.index
    minb = comp_cfg.min_bars_for_component

    vol_ratio = volatility_ratio(bars, comp_cfg)
    vol_ratio_avail = vol_ratio.notna()

    volume_z = volume_surprise(bars, comp_cfg)
    volume_z_avail = volume_z.notna()

    range_ratio, spread_bps = range_deterioration(bars, quotes)
    range_ratio_avail = range_ratio.notna()
    spread_avail = spread_bps is not None
    if spread_bps is None:
        spread_bps = pd.Series(np.nan, index=idx)

    if universe_prices is not None and universe_prices.shape[1] >= 2:
        dispersion = cross_sectional_dispersion(
            universe_prices.reindex(idx), comp_cfg.dispersion_window
        )
        corr_shift = correlation_shift(universe_prices.reindex(idx), comp_cfg)
    else:
        dispersion = pd.Series(np.nan, index=idx)
        corr_shift = pd.Series(np.nan, index=idx)
    dispersion_avail = dispersion.notna()
    corr_shift_avail = corr_shift.notna()

    flow_imbalance, flow_method = order_flow_imbalance(bars, comp_cfg, quotes)
    flow_avail = flow_imbalance.notna()

    jump_rj, jump_z = jump_indicator(bars, comp_cfg)
    jump_avail = jump_z.notna()

    novelty_value, novelty_available_flag = novelty_aggregate(novelty, idx)
    novelty_avail = pd.Series(novelty_available_flag, index=idx) & novelty_value.notna()

    scores = pd.DataFrame(
        {
            "vol_ratio": _score_vol_ratio(vol_ratio),
            "volume_z": _score_volume_z(volume_z),
            "range_ratio": _score_range_ratio(range_ratio),
            "dispersion": _score_dispersion(dispersion, comp_cfg),
            "corr_shift": _score_corr_shift(corr_shift),
            "flow_imbalance": _score_flow_imbalance(flow_imbalance),
            "jump": _score_jump(jump_z),
            "novelty": novelty_value,
        },
        index=idx,
    )
    available = pd.DataFrame(
        {
            "vol_ratio": vol_ratio_avail,
            "volume_z": volume_z_avail,
            "range_ratio": range_ratio_avail,
            "dispersion": dispersion_avail,
            "corr_shift": corr_shift_avail,
            "flow_imbalance": flow_avail,
            "jump": jump_avail,
            "novelty": novelty_avail,
        },
        index=idx,
    )

    chaos_index = compute_chaos_index(scores, available, weights)
    state_label = run_state_machine(chaos_index, state_cfg)

    frame = pd.DataFrame(
        {
            "vol_ratio": vol_ratio,
            "vol_ratio_available": vol_ratio_avail,
            "volume_z": volume_z,
            "volume_z_available": volume_z_avail,
            "range_ratio": range_ratio,
            "range_ratio_available": range_ratio_avail,
            "spread_bps": spread_bps,
            "spread_available": spread_avail,
            "dispersion": dispersion,
            "dispersion_available": dispersion_avail,
            "corr_shift": corr_shift,
            "corr_shift_available": corr_shift_avail,
            "flow_imbalance": flow_imbalance,
            "flow_imbalance_available": flow_avail,
            "flow_method": flow_method,
            "jump_rj": jump_rj,
            "jump_z": jump_z,
            "jump_available": jump_avail,
            "novelty_value": novelty_value,
            "novelty_available": novelty_avail,
            "chaos_index": chaos_index,
            "state_label": state_label,
        },
        index=idx,
    )
    return StateResult(frame=frame)

"""Tests for CHAOS-01 — the eight components, their combination, and the
hysteresis state machine.

The two headline tests are `test_determinism` (replaying a known volatile
synthetic session reproduces the exact same state sequence every time) and
`test_hysteresis_prevents_flapping` (a fixture that hovers right at a
threshold does NOT oscillate faster than the configured minimum dwell time).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from chaos.config import ComponentConfig, StateConfig
from chaos.state import (
    bipower_variation,
    compute_chaos_index,
    compute_state,
    correlation_shift,
    cross_sectional_dispersion,
    jump_indicator,
    jump_test_statistic,
    novelty_aggregate,
    order_flow_imbalance,
    range_deterioration,
    realized_variance,
    run_state_machine,
    volatility_ratio,
    volume_surprise,
)


# --- synthetic fixtures ------------------------------------------------------


def make_minute_bars(n_sessions: int = 6, bars_per_session: int = 60, seed: int = 3) -> pd.DataFrame:
    """A repeating-intraday-volume-curve, multi-session 1-minute panel."""
    rng = np.random.default_rng(seed)
    n = n_sessions * bars_per_session
    minute = np.tile(np.arange(bars_per_session), n_sessions)
    u_shape = 1.0 + 1.5 * np.exp(-((minute) ** 2) / (2 * 10.0 ** 2)) + \
        1.5 * np.exp(-((minute - (bars_per_session - 1)) ** 2) / (2 * 10.0 ** 2))
    volume = np.maximum(20_000.0 * u_shape * (1.0 + rng.normal(0, 0.05, n)), 100.0)

    logret = rng.normal(0.0, 0.0004, n)
    close = 100.0 * np.exp(np.cumsum(logret))
    open_ = np.roll(close, 1)
    open_[0] = 100.0
    span = np.abs(rng.normal(0, 0.05, n)) + 0.01
    high = np.maximum(open_, close) + span
    low = np.minimum(open_, close) - span

    start = pd.Timestamp("2026-01-05 09:30")
    idx = []
    for s in range(n_sessions):
        day = start + pd.Timedelta(days=s)
        idx.extend(pd.date_range(day, periods=bars_per_session, freq="min"))
    idx = pd.DatetimeIndex(idx[:n])
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )


def make_universe_panel(n: int = 300, n_tickers: int = 4, seed: int = 5) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-05 09:30", periods=n, freq="min")
    common = rng.normal(0, 0.0006, n)
    cols = {}
    for k in range(n_tickers):
        idio = rng.normal(0, 0.0006, n)
        logret = 0.3 * common + 0.7 * idio
        cols[f"T{k}"] = 100.0 * (1 + k * 0.1) * np.exp(np.cumsum(logret))
    return pd.DataFrame(cols, index=idx)


# --- component 1: volatility ratio ------------------------------------------


def test_volatility_ratio_near_one_for_stable_vol():
    df = make_minute_bars(n_sessions=3, bars_per_session=120, seed=1)
    cfg = ComponentConfig()
    ratio = volatility_ratio(df, cfg)
    tail = ratio.dropna()
    assert len(tail) > 0
    # Stable-vol synthetic series: ratio should hover near 1, not blow up.
    assert tail.median() == pytest.approx(1.0, abs=0.6)


def test_volatility_ratio_spikes_on_vol_expansion():
    rng = np.random.default_rng(9)
    n = 200
    logret = rng.normal(0, 0.0003, n)
    logret[-5:] = rng.normal(0, 0.01, 5)  # sudden vol expansion in the last 5 bars
    close = 100.0 * np.exp(np.cumsum(logret))
    idx = pd.date_range("2026-01-05 09:30", periods=n, freq="min")
    df = pd.DataFrame(
        {"open": close, "high": close + 0.01, "low": close - 0.01, "close": close, "volume": 1000.0},
        index=idx,
    )
    ratio = volatility_ratio(df, ComponentConfig())
    assert ratio.iloc[-1] > 2.0


# --- component 2: volume surprise -------------------------------------------


def test_volume_surprise_controls_for_intraday_shape():
    """A normal day's U-shaped curve should NOT register as a surprise; a
    genuine spike at one minute-of-day on one day should."""
    df = make_minute_bars(n_sessions=8, bars_per_session=60, seed=11)
    cfg = ComponentConfig(volume_lookback_sessions=5)

    # Inject one real anomaly: 5x volume at minute 30 on the LAST session only.
    last_session_start = df.index[-60]
    spike_ts = last_session_start + pd.Timedelta(minutes=30)
    df.loc[spike_ts, "volume"] *= 6.0

    z = volume_surprise(df, cfg)
    # The spike bar should be a clear outlier.
    assert z.loc[spike_ts] > 3.0
    # Ordinary bars late in the series (fully warmed up) should mostly be mild.
    warm = z.iloc[-60:].drop(index=spike_ts)
    assert warm.dropna().abs().median() < 2.0


# --- component 3: range/spread deterioration --------------------------------


def test_range_deterioration_without_quotes_marks_spread_unavailable():
    df = make_minute_bars(n_sessions=2, bars_per_session=50, seed=2)
    ratio, spread_bps = range_deterioration(df, quotes=None)
    assert spread_bps is None
    assert ratio.dropna().gt(0).all()


def test_range_deterioration_with_quotes_computes_spread():
    df = make_minute_bars(n_sessions=1, bars_per_session=10, seed=2)
    mid = df["close"]
    quotes = pd.DataFrame({"bid": mid - 0.05, "ask": mid + 0.05}, index=df.index)
    ratio, spread_bps = range_deterioration(df, quotes=quotes)
    assert spread_bps is not None
    expected = (0.10 / mid) * 1e4
    pd.testing.assert_series_equal(spread_bps, expected, check_names=False)


# --- component 4/5: cross-sectional dispersion & correlation shift ---------


def test_dispersion_zero_for_identical_tickers():
    idx = pd.date_range("2026-01-05 09:30", periods=100, freq="min")
    rng = np.random.default_rng(1)
    logret = rng.normal(0, 0.001, 100)
    close = 100.0 * np.exp(np.cumsum(logret))
    panel = pd.DataFrame({"A": close, "B": close, "C": close}, index=idx)
    disp = cross_sectional_dispersion(panel, window=5)
    assert disp.dropna().abs().max() < 1e-9


def test_dispersion_single_ticker_is_nan():
    idx = pd.date_range("2026-01-05 09:30", periods=50, freq="min")
    panel = pd.DataFrame({"A": np.linspace(100, 101, 50)}, index=idx)
    disp = cross_sectional_dispersion(panel, window=5)
    assert disp.isna().all()


def test_correlation_shift_detects_regime_change():
    """Independent returns for the first half, then a common shock added to
    all tickers for the second half: average pairwise correlation should
    rise, and the shift (short vs trailing) should turn positive soon after
    the regime change."""
    rng = np.random.default_rng(4)
    n = 400
    idx = pd.date_range("2026-01-05 09:30", periods=n, freq="min")
    idio = rng.normal(0, 0.001, (n, 4))
    common = np.zeros(n)
    common[200:] = rng.normal(0, 0.002, n - 200)
    logret = idio + common[:, None]
    prices = 100.0 * np.exp(np.cumsum(logret, axis=0))
    panel = pd.DataFrame(prices, index=idx, columns=[f"T{k}" for k in range(4)])

    cfg = ComponentConfig(corr_short_window=15, corr_trailing_window=60)
    shift = correlation_shift(panel, cfg)
    late = shift.iloc[250:300].dropna()
    early = shift.iloc[70:120].dropna()
    assert late.mean() > early.mean()


# --- component 6: order flow imbalance --------------------------------------


def test_order_flow_imbalance_all_up_is_positive():
    idx = pd.date_range("2026-01-05 09:30", periods=30, freq="min")
    close = np.linspace(100, 110, 30)
    df = pd.DataFrame(
        {"open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 1000.0},
        index=idx,
    )
    imbalance, method = order_flow_imbalance(df, ComponentConfig(dispersion_window=5))
    assert method == "tick_rule_bar_close"
    assert imbalance.dropna().iloc[-1] == pytest.approx(1.0, abs=1e-9)


def test_order_flow_imbalance_uses_quotes_when_available():
    idx = pd.date_range("2026-01-05 09:30", periods=30, freq="min")
    close = np.full(30, 100.5)
    df = pd.DataFrame(
        {"open": close, "high": close + 0.1, "low": close - 0.1, "close": close, "volume": 1000.0},
        index=idx,
    )
    quotes = pd.DataFrame({"bid": 99.9, "ask": 100.1}, index=idx)  # mid=100.0, close above mid
    imbalance, method = order_flow_imbalance(df, ComponentConfig(dispersion_window=5), quotes=quotes)
    assert method == "quote_midpoint"
    assert imbalance.dropna().iloc[-1] == pytest.approx(1.0, abs=1e-9)


# --- component 7: jump indicator (bipower variation) ------------------------


def test_bipower_variation_known_value():
    r = np.array([1.0, 2.0, 3.0])
    assert bipower_variation(r) == pytest.approx(4 * np.pi)
    assert realized_variance(r) == pytest.approx(14.0)


def test_jump_test_statistic_flags_genuine_discontinuity():
    rng = np.random.default_rng(0)
    calm = rng.normal(0, 0.001, 200)
    rj_calm, z_calm = jump_test_statistic(calm)

    jumpy = calm.copy()
    jumpy[100] += 0.05
    rj_jump, z_jump = jump_test_statistic(jumpy)

    assert abs(z_jump) > abs(z_calm)
    assert abs(z_jump) > 5.0  # a clear rejection of the no-jump null
    assert rj_jump > rj_calm


def test_jump_indicator_rolling_series_shape():
    df = make_minute_bars(n_sessions=2, bars_per_session=80, seed=6)
    cfg = ComponentConfig(jump_window=30, min_bars_for_component=20)
    rj, z = jump_indicator(df, cfg)
    assert len(rj) == len(df)
    assert rj.iloc[: cfg.min_bars_for_component - 1].isna().all()
    assert rj.dropna().shape[0] > 0


# --- component 8: novelty (external input only) -----------------------------


def test_novelty_unavailable_when_not_supplied():
    idx = pd.date_range("2026-01-05", periods=10, freq="min")
    value, available = novelty_aggregate(None, idx)
    assert available is False
    assert value.isna().all()


def test_novelty_passthrough_when_supplied():
    idx = pd.date_range("2026-01-05", periods=5, freq="min")
    external = pd.Series([0.1, 1.5, -0.2, 0.5, np.nan], index=idx)
    value, available = novelty_aggregate(external, idx)
    assert available is True
    assert value.iloc[0] == pytest.approx(0.1)
    assert value.iloc[1] == pytest.approx(1.0)  # clipped
    assert value.iloc[2] == pytest.approx(0.0)  # clipped
    assert np.isnan(value.iloc[4])


# --- combination: chaos index ------------------------------------------------


def test_compute_chaos_index_renormalizes_over_available_only():
    idx = pd.RangeIndex(3)
    scores = pd.DataFrame({"a": [1.0, 1.0, np.nan], "b": [0.0, 0.0, 0.0]}, index=idx)
    available = pd.DataFrame({"a": [True, False, True], "b": [True, True, True]}, index=idx)
    weights = {"a": 0.8, "b": 0.2}
    idx_out = compute_chaos_index(scores, available, weights)
    # Row 0: both available -> 0.8*1 + 0.2*0 = 0.8
    assert idx_out.iloc[0] == pytest.approx(0.8)
    # Row 1: a unavailable -> renormalised to just b -> 0.0
    assert idx_out.iloc[1] == pytest.approx(0.0)
    # Row 2: a is NaN despite "available" True -> excluded too -> just b -> 0.0
    assert idx_out.iloc[2] == pytest.approx(0.0)


# --- the state machine: hysteresis + minimum dwell time ---------------------


def test_determinism():
    """Replaying a known volatile synthetic session reproduces the exact same
    state sequence every time."""
    rng = np.random.default_rng(21)
    n = 300
    idx = pd.RangeIndex(n)
    index_vals = pd.Series(np.clip(rng.normal(0.4, 0.25, n), 0.0, 1.0), index=idx)
    cfg = StateConfig()

    run1 = run_state_machine(index_vals, cfg)
    run2 = run_state_machine(index_vals, cfg)
    run3 = run_state_machine(index_vals.copy(), cfg)
    assert (run1 == run2).all()
    assert (run1 == run3).all()
    assert list(run1) == list(run2) == list(run3)


def test_determinism_full_pipeline_on_synthetic_session():
    """Same property, exercised through the full compute_state pipeline on a
    realistic multi-component synthetic session."""
    df = make_minute_bars(n_sessions=5, bars_per_session=90, seed=77)
    panel = make_universe_panel(n=len(df), n_tickers=3, seed=78)
    panel = panel.set_axis(df.index)

    r1 = compute_state(df, universe_prices=panel)
    r2 = compute_state(df, universe_prices=panel)
    assert list(r1.state_label) == list(r2.state_label)
    pd.testing.assert_series_equal(r1.chaos_index, r2.chaos_index)


def test_hysteresis_prevents_flapping():
    """A fixture that repeatedly crosses back and forth over the SAME
    threshold (which, under a bare threshold snapshot, would flip the label
    every single bar) must not change state faster than `min_dwell_bars`."""
    cfg = StateConfig(min_dwell_bars=5)
    n = 40
    # Alternates far below exit_stressed and far above enter_stressed.
    vals = [0.10 if i % 2 == 0 else 0.50 for i in range(n)]
    idx = pd.RangeIndex(n)
    chaos_index = pd.Series(vals, index=idx)

    labels = run_state_machine(chaos_index, cfg)
    change_points = [i for i in range(1, n) if labels.iloc[i] != labels.iloc[i - 1]]

    assert len(change_points) > 1, "fixture should provoke more than one transition over 40 bars"
    gaps = [b - a for a, b in zip(change_points, change_points[1:])]
    assert all(g >= cfg.min_dwell_bars for g in gaps), (
        f"state changed faster than min_dwell_bars={cfg.min_dwell_bars}: gaps={gaps}"
    )
    # Sanity: without the alternation ever settling into the hysteresis dead
    # zone, changes should occur roughly once per dwell window, not less.
    assert len(change_points) >= n // (2 * cfg.min_dwell_bars)


def test_hysteresis_dead_zone_holds_state_even_without_dwell_limit():
    """With NO dwell restriction, a value oscillating strictly BETWEEN a
    level's exit and enter threshold (the hysteresis dead zone) still must
    not flap, because neither an escalate nor a de-escalate condition is
    ever triggered."""
    cfg = StateConfig(min_dwell_bars=1)
    # exit_stressed=0.25, enter_stressed=0.35 by default: 0.28/0.32 both sit
    # inside the dead zone once "stressed" has been entered.
    vals = [0.40] + [0.28, 0.32] * 20  # first bar enters "stressed"
    idx = pd.RangeIndex(len(vals))
    labels = run_state_machine(pd.Series(vals, index=idx), cfg)
    assert labels.iloc[0] == "stressed"
    assert (labels.iloc[1:] == "stressed").all()


def test_state_machine_escalates_through_all_levels():
    cfg = StateConfig(min_dwell_bars=1)
    vals = [0.0, 0.40, 0.65, 0.90, 0.20, 0.0]
    labels = run_state_machine(pd.Series(vals), cfg)
    assert list(labels) == ["calm", "stressed", "dislocated", "cascade", "calm", "calm"]


def test_state_machine_holds_through_nan_bars():
    cfg = StateConfig(min_dwell_bars=2)
    vals = [0.40, np.nan, np.nan, 0.10]
    labels = run_state_machine(pd.Series(vals), cfg)
    assert labels.iloc[1] == "stressed"
    assert labels.iloc[2] == "stressed"

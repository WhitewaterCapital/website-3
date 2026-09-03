"""Technical indicators are computed locally from bars, never taken from a
vendor's own indicator endpoint (`router/adapters/alpha_vantage.py`'s
docstring names this rule explicitly). These tests exercise the pure
close-price functions directly and via `Bar` records."""

from datetime import date, datetime, timezone

import pytest

from router.indicators import ema, ema_from_bars, macd, rsi, sma, sma_from_bars
from router.schema import Bar

_NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def _bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(
            ticker="X", open=c, high=c, low=c, close=c, volume=100,
            observation_date=date(2024, 1, 1 + i), source_publication_time=_NOW,
            ingestion_time=_NOW, vendor="local-file-fixture", vendor_field_name="close",
        )
        for i, c in enumerate(closes)
    ]


# --- SMA ---------------------------------------------------------------


def test_sma_basic_window():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = sma(closes, window=3)
    assert result == [None, None, pytest.approx(2.0), pytest.approx(3.0), pytest.approx(4.0)]


def test_sma_same_length_as_input():
    closes = [1.0] * 10
    assert len(sma(closes, window=4)) == 10


def test_sma_constant_series_equals_the_constant():
    closes = [7.0] * 5
    result = sma(closes, window=3)
    assert result[2:] == [pytest.approx(7.0)] * 3


def test_sma_rejects_non_positive_window():
    with pytest.raises(ValueError):
        sma([1.0, 2.0], window=0)


def test_sma_from_bars_matches_sma_of_closes():
    closes = [10.0, 11.0, 12.0, 13.0]
    bars = _bars(closes)
    assert sma_from_bars(bars, window=2) == sma(closes, window=2)


# --- EMA ---------------------------------------------------------------


def test_ema_basic_window_matches_hand_computed_values():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    result = ema(closes, window=3)
    expected = [None, None, 2.0, 3.0, 4.0]  # linear series: EMA tracks SMA exactly
    for r, e in zip(result, expected):
        if e is None:
            assert r is None
        else:
            assert r == pytest.approx(e)


def test_ema_not_enough_data_returns_all_none():
    result = ema([1.0, 2.0], window=5)
    assert result == [None, None]


def test_ema_rejects_non_positive_window():
    with pytest.raises(ValueError):
        ema([1.0, 2.0], window=0)


def test_ema_from_bars_matches_ema_of_closes():
    closes = [1.0, 2.0, 3.0, 4.0]
    bars = _bars(closes)
    assert ema_from_bars(bars, window=2) == ema(closes, window=2)


# --- RSI -----------------------------------------------------------------


def test_rsi_all_gains_is_one_hundred():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]
    result = rsi(closes, window=3)
    assert result[:3] == [None, None, None]
    assert all(v == pytest.approx(100.0) for v in result[3:])


def test_rsi_all_losses_is_zero():
    closes = [10.0, 9.0, 8.0, 7.0, 6.0, 5.0]
    result = rsi(closes, window=3)
    assert all(v == pytest.approx(0.0) for v in result[3:])


def test_rsi_flat_series_defaults_to_one_hundred_when_no_losses():
    closes = [5.0] * 10
    result = rsi(closes, window=3)
    # No gains and no losses -> avg_loss == 0 -> defined as 100 by convention.
    assert all(v == pytest.approx(100.0) for v in result[3:])


def test_rsi_not_enough_data_returns_all_none():
    result = rsi([1.0, 2.0], window=14)
    assert result == [None, None]


def test_rsi_rejects_non_positive_window():
    with pytest.raises(ValueError):
        rsi([1.0, 2.0, 3.0], window=0)


def test_rsi_bounded_between_zero_and_hundred():
    closes = [10, 9, 11, 10, 12, 9, 13, 8, 14, 15, 7, 16]
    closes = [float(c) for c in closes]
    result = rsi(closes, window=4)
    for v in result:
        if v is not None:
            assert 0.0 <= v <= 100.0


# --- MACD ------------------------------------------------------------------


def test_macd_matches_hand_computed_values_for_linear_series():
    closes = [float(i) for i in range(1, 11)]  # 1..10
    result = macd(closes, fast=2, slow=3, signal=2)

    expected_macd = [None, None, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    expected_signal = [None, None, None, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5]
    expected_hist = [None, None, None, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    for got, exp in zip(result["macd"], expected_macd):
        assert got is None if exp is None else got == pytest.approx(exp)
    for got, exp in zip(result["signal"], expected_signal):
        assert got is None if exp is None else got == pytest.approx(exp)
    for got, exp in zip(result["histogram"], expected_hist):
        assert got is None if exp is None else got == pytest.approx(exp)


def test_macd_all_series_same_length_as_input():
    closes = [float(i) for i in range(20)]
    result = macd(closes, fast=3, slow=6, signal=3)
    assert len(result["macd"]) == len(closes)
    assert len(result["signal"]) == len(closes)
    assert len(result["histogram"]) == len(closes)


def test_macd_histogram_equals_macd_minus_signal_wherever_both_defined():
    closes = [float(i) * 1.3 % 7 + i for i in range(30)]
    result = macd(closes, fast=4, slow=9, signal=5)
    for m, s, h in zip(result["macd"], result["signal"], result["histogram"]):
        if m is not None and s is not None:
            assert h == pytest.approx(m - s)
        else:
            assert h is None


def test_macd_rejects_non_positive_windows():
    with pytest.raises(ValueError):
        macd([1.0, 2.0, 3.0], fast=0)

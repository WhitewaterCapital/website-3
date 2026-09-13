"""Unit tests for wf/adapters/prices_tiingo.py against MOCKED Tiingo HTTP
responses -- this sandbox has no outbound network access, so every request
here is intercepted at `TiingoClient._get` and answered with realistic rows
matching Tiingo's real, documented JSON shape (date, adjOpen/adjHigh/adjLow/
adjClose/adjVolume plus the raw open/high/low/close/volume fallbacks) -- the
exact fields the adapter parses. No real network call is made or attempted.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from wf.adapters.prices_tiingo import (
    TiingoClient,
    fetch_universe_weekly_prices,
    fetch_weekly_ohlcv,
    tiingo_key,
)


def _row(d: str, o: float, h: float, l: float, c: float, v: float) -> dict:
    """One Tiingo daily-prices JSON row, exactly the documented response shape."""
    return {
        "date": f"{d}T00:00:00.000Z",
        "open": o, "high": h, "low": l, "close": c, "volume": v,
        "adjOpen": o, "adjHigh": h, "adjLow": l, "adjClose": c, "adjVolume": v,
        "divCash": 0.0, "splitFactor": 1.0,
    }


@pytest.fixture
def tiingo_key_env(monkeypatch):
    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")


def test_tiingo_key_missing_raises(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="TIINGO_API_KEY"):
        tiingo_key()


def test_fetch_prices_parses_realistic_response(monkeypatch, tiingo_key_env):
    rows = [
        _row("2026-08-03", 100.0, 101.0, 99.0, 100.5, 1_000_000),
        _row("2026-08-04", 100.5, 102.0, 100.0, 101.5, 1_100_000),
    ]
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    bars = client.fetch_prices("aapl")
    assert len(bars) == 2
    assert bars[0].ticker == "AAPL"
    assert bars[0].close == 100.5
    assert bars[0].source == "tiingo" and bars[0].adjusted is True


def test_fetch_prices_prefers_adjusted_fields_over_raw(monkeypatch, tiingo_key_env):
    row = _row("2026-08-03", 100.0, 101.0, 99.0, 100.5, 1_000_000)
    row["adjClose"] = 50.25
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: [row])
    client = TiingoClient()
    bars = client.fetch_prices("aapl")
    assert bars[0].close == 50.25


def test_fetch_prices_drops_unsettled_bar_dated_today(monkeypatch, tiingo_key_env):
    today = date.today()
    rows = [
        _row("2026-08-03", 100.0, 101.0, 99.0, 100.5, 1_000_000),
        _row(today.isoformat(), 100.5, 102.0, 100.0, 101.5, 1_100_000),
    ]
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    bars = client.fetch_prices("aapl")
    assert len(bars) == 1 and bars[0].date.isoformat() == "2026-08-03"


def test_fetch_prices_skips_malformed_rows(monkeypatch, tiingo_key_env):
    """Matches the reference adapter's `except (KeyError, ValueError,
    TypeError): continue` behaviour."""
    good = _row("2026-08-03", 100.0, 101.0, 99.0, 100.5, 1_000_000)
    missing_date = {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}
    bad_date_type = _row("2026-08-04", 100, 101, 99, 100.5, 1_000_000)
    bad_date_type["date"] = None
    non_numeric_close = _row("2026-08-05", 100, 101, 99, 100.0, 1_000_000)
    non_numeric_close["adjClose"] = "not-a-number"
    rows = [good, missing_date, bad_date_type, non_numeric_close]
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    bars = client.fetch_prices("aapl")
    assert len(bars) == 1 and bars[0].date.isoformat() == "2026-08-03"


def test_fetch_weekly_ohlcv_resamples_to_friday_and_drops_partial_week(monkeypatch, tiingo_key_env):
    # 2026-07-06 is a Monday (asserted below rather than assumed) -- 13
    # sequential business days from there is exactly two full Mon-Fri weeks
    # plus a partial third week (Mon/Tue/Wed only). The partial week must be
    # dropped, not published as if it were a real week-end close.
    assert pd.Timestamp("2026-07-06").weekday() == 0
    dates = pd.bdate_range("2026-07-06", periods=13)
    closes = [100, 101, 102, 103, 104,  # week 1, Mon-Fri
              105, 104, 106, 107, 108,  # week 2, Mon-Fri
              109, 110, 111]            # week 3, Mon-Wed only (partial)
    rows = [_row(d.date().isoformat(), c, c + 1, c - 1, c, 1_000_000) for d, c in zip(dates, closes)]

    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    weekly = fetch_weekly_ohlcv("aapl", client=client)

    assert list(weekly.columns) == ["open", "high", "low", "close", "volume"]
    assert len(weekly) == 2  # partial 3rd week dropped
    assert all(ts.weekday() == 4 for ts in weekly.index)  # every bucket ends Friday
    assert weekly["close"].iloc[0] == 104  # last close of week 1
    assert weekly["close"].iloc[1] == 108  # last close of week 2
    assert weekly["open"].iloc[0] == 100  # first open of week 1
    assert weekly["volume"].iloc[0] == 5_000_000  # summed across the 5-day week


def test_fetch_weekly_ohlcv_empty_when_no_bars(monkeypatch, tiingo_key_env):
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: [])
    client = TiingoClient()
    weekly = fetch_weekly_ohlcv("aapl", client=client)
    assert weekly.empty
    assert list(weekly.columns) == ["open", "high", "low", "close", "volume"]


def test_fetch_universe_weekly_prices_returns_one_frame_per_ticker(monkeypatch, tiingo_key_env):
    dates = pd.bdate_range("2026-07-06", periods=10)
    rows = [_row(d.date().isoformat(), 100, 101, 99, 100.0, 1_000_000) for d in dates]
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    out = fetch_universe_weekly_prices(["AAPL", "MSFT"], client=client)
    assert set(out) == {"AAPL", "MSFT"}
    for df in out.values():
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert len(df) == 2

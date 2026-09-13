"""Unit tests for fac/adapters/prices_tiingo.py against MOCKED Tiingo HTTP
responses -- this sandbox has no outbound network access, so every request
here is intercepted at `TiingoClient._get` and answered with realistic rows
matching Tiingo's real, documented JSON shape (date, adjOpen/adjHigh/adjLow/
adjClose/adjVolume plus the raw open/high/low/close/volume fallbacks) -- the
exact fields the adapter parses. No real network call is made or attempted.
"""

from __future__ import annotations

from datetime import date

import pytest

from fac.adapters.prices_tiingo import TiingoClient, fetch_daily_returns, tiingo_key


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
        _row("2026-08-05", 101.5, 103.0, 101.0, 102.5, 1_200_000),
    ]
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    bars = client.fetch_prices("aapl", start=date(2026, 8, 1))

    assert [b.date.isoformat() for b in bars] == ["2026-08-03", "2026-08-04", "2026-08-05"]
    assert all(b.ticker == "AAPL" for b in bars)
    assert all(b.source == "tiingo" and b.adjusted is True for b in bars)
    assert bars[0].close == 100.5


def test_fetch_prices_prefers_adjusted_fields_over_raw(monkeypatch, tiingo_key_env):
    row = _row("2026-08-03", 100.0, 101.0, 99.0, 100.5, 1_000_000)
    row["adjClose"] = 50.25  # e.g. a 2:1 split retroactively applied
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
    assert len(bars) == 1
    assert bars[0].date.isoformat() == "2026-08-03"


def test_fetch_prices_skips_malformed_rows(monkeypatch, tiingo_key_env):
    good = _row("2026-08-03", 100.0, 101.0, 99.0, 100.5, 1_000_000)
    missing_date = {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}  # KeyError
    non_numeric_close = _row("2026-08-05", 100, 101, 99, 100.0, 1_000_000)
    non_numeric_close["adjClose"] = "not-a-number"  # ValueError
    rows = [good, missing_date, non_numeric_close]
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    bars = client.fetch_prices("aapl")
    assert len(bars) == 1
    assert bars[0].date.isoformat() == "2026-08-03"


def test_fetch_daily_returns_computes_pct_change_and_drops_first_row(monkeypatch, tiingo_key_env):
    rows = [
        _row("2026-08-03", 100, 101, 99, 100.0, 1_000_000),
        _row("2026-08-04", 100, 101, 99, 101.0, 1_000_000),  # +1%
        _row("2026-08-05", 100, 101, 99, 99.99, 1_000_000),  # -1% (approx)
    ]
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    returns = fetch_daily_returns("aapl", client=client)

    assert returns.name == "AAPL"
    assert len(returns) == 2  # first row's return is undefined and dropped
    assert returns.iloc[0] == pytest.approx(0.01)
    assert returns.iloc[1] == pytest.approx(-0.01, abs=1e-6)  # 99.99 / 101.0 - 1 == -0.01 exactly


def test_fetch_daily_returns_empty_when_no_bars(tiingo_key_env, monkeypatch):
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: [])
    client = TiingoClient()
    returns = fetch_daily_returns("aapl", client=client)
    assert returns.empty

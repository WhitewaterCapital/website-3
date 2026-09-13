"""Unit tests for ge/adapters/prices_tiingo.py against MOCKED Tiingo HTTP
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

from ge.adapters.prices_tiingo import TiingoClient, fetch_close_panel, tiingo_key


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
    assert bars[-1].volume == 1_200_000


def test_fetch_prices_prefers_adjusted_fields_over_raw(monkeypatch, tiingo_key_env):
    # adjClose differs from close -- a real split/dividend adjustment. The
    # adapter must prefer the adjusted fields, not the raw ones.
    row = _row("2026-08-03", 100.0, 101.0, 99.0, 100.5, 1_000_000)
    row["adjClose"] = 50.25  # e.g. a 2:1 split retroactively applied
    row["adjOpen"] = 50.0
    row["adjHigh"] = 50.5
    row["adjLow"] = 49.5
    row["adjVolume"] = 2_000_000
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: [row])
    client = TiingoClient()
    bars = client.fetch_prices("aapl")
    assert bars[0].close == 50.25
    assert bars[0].open == 50.0
    assert bars[0].volume == 2_000_000


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
    """Matches the reference adapter's `except (KeyError, ValueError,
    TypeError): continue` behaviour -- a malformed row is dropped, not
    raised, and never corrupts the rest of the series."""
    good = _row("2026-08-03", 100.0, 101.0, 99.0, 100.5, 1_000_000)
    missing_date = {"open": 1, "high": 1, "low": 1, "close": 1, "volume": 1}  # KeyError
    bad_date_type = _row("2026-08-04", 100, 101, 99, 100.5, 1_000_000)
    bad_date_type["date"] = None  # TypeError (None[:10])
    non_numeric_close = _row("2026-08-05", 100, 101, 99, 100.0, 1_000_000)
    non_numeric_close["adjClose"] = "not-a-number"  # ValueError (float(...))
    rows = [good, missing_date, bad_date_type, non_numeric_close]
    monkeypatch.setattr(TiingoClient, "_get", lambda self, url, params: rows)
    client = TiingoClient()
    bars = client.fetch_prices("aapl")
    assert len(bars) == 1
    assert bars[0].date.isoformat() == "2026-08-03"


def test_fetch_close_panel_aligns_multiple_tickers_and_drops_mismatched_dates(monkeypatch, tiingo_key_env):
    aapl_rows = [
        _row("2026-08-03", 100, 101, 99, 100.0, 1_000_000),
        _row("2026-08-04", 100, 101, 99, 101.0, 1_000_000),
        _row("2026-08-05", 100, 101, 99, 102.0, 1_000_000),
    ]
    # MSFT is missing 2026-08-04 (e.g. a data gap / holiday-calendar
    # mismatch) -- that date must be dropped from the combined panel
    # entirely, never forward-filled or left as a NaN.
    msft_rows = [
        _row("2026-08-03", 300, 301, 299, 300.0, 500_000),
        _row("2026-08-05", 300, 301, 299, 303.0, 500_000),
    ]

    def fake_get(self, url, params):
        return aapl_rows if "/aapl/" in url else msft_rows

    monkeypatch.setattr(TiingoClient, "_get", fake_get)
    client = TiingoClient()
    panel = fetch_close_panel(["AAPL", "MSFT"], client=client)

    assert list(panel.columns) == ["AAPL", "MSFT"]
    assert list(panel.index.strftime("%Y-%m-%d")) == ["2026-08-03", "2026-08-05"]
    assert panel.loc["2026-08-03", "AAPL"] == 100.0
    assert panel.loc["2026-08-05", "MSFT"] == 303.0
    assert not panel.isna().any().any()


def test_fetch_close_panel_empty_universe_returns_empty_frame(tiingo_key_env):
    client = TiingoClient()
    panel = fetch_close_panel([], client=client)
    assert panel.empty

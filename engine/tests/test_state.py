"""Tests for WW-STATE (STATE-01): the market state vector.

Covers: standardization against a value's OWN FULL LONG HISTORY (never just
the recent window — the mistake the dossier explicitly warns about), the
schema-version/order breaking-change guard, the plain-language mapping, and
an honesty test proving slippage and implied-vol truly come back `None` (not
fabricated) when the underlying data doesn't exist.
"""

from __future__ import annotations

import dataclasses
import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from incepta.state import (
    ELEMENT_ORDER,
    SCHEMA_VERSION,
    ElementReading,
    SchemaMismatchError,
    StateVector,
    build_state_export,
    compute_state_vector,
    plain_language,
    validate_schema,
    write_state_export,
    _own_history_stat,
)


# ---------------------------------------------------------------------------
# Synthetic fixtures (mirrors the rng-based synthetic style used elsewhere in
# engine/tests, e.g. test_validation_and_backtest.py's `_panel`)
# ---------------------------------------------------------------------------

def _synthetic_universe(n_days=900, n_tickers=20, seed=1, target_corr=0.2):
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0003, 0.01, n_days)
    idio = rng.normal(0.0, 0.015, (n_days, n_tickers))
    beta = math.sqrt(target_corr)
    rets = beta * market[:, None] + math.sqrt(1 - target_corr) * idio

    tickers = [f"T{i}" for i in range(n_tickers)]
    dates = pd.bdate_range("2020-01-02", periods=n_days)
    constituent_returns = pd.DataFrame(rets, index=dates, columns=tickers)
    constituent_closes = 100.0 * (1.0 + constituent_returns).cumprod()

    index_closes = np.concatenate([[100.0], 100.0 * np.cumprod(1.0 + market)])
    highs = index_closes * (1.0 + rng.uniform(0.001, 0.01, index_closes.size))
    lows = index_closes * (1.0 - rng.uniform(0.001, 0.01, index_closes.size))
    volume = rng.uniform(1e6, 2e6, index_closes.size)
    return index_closes, constituent_returns, constituent_closes, highs, lows, volume


def _regime_shift_closes(n_quiet=750, n_elevated=100, quiet_vol=0.005, elevated_vol=0.03, seed=0):
    """A long quiet regime followed by a recent, internally-consistent elevated
    regime. If volatility were standardized against only the recent window
    (the wrong way), the elevated regime would look "normal" relative to
    itself. Standardized against the FULL history (the right way), it should
    look clearly elevated."""
    rng = np.random.default_rng(seed)
    r_quiet = rng.normal(0.0, quiet_vol, n_quiet)
    r_elevated = rng.normal(0.0, elevated_vol, n_elevated)
    rets = np.concatenate([r_quiet, r_elevated])
    closes = np.concatenate([[100.0], 100.0 * np.cumprod(1.0 + rets)])
    return closes


def _minimal_vector(**overrides) -> StateVector:
    blank = ElementReading(available=False, value=None, raw={})
    fields = dict(
        schema_version=SCHEMA_VERSION,
        element_order=list(ELEMENT_ORDER),
        as_of=date(2024, 1, 1),
        volatility=blank, dispersion=blank, correlation=blank, breadth=blank,
        trend=blank, slippage=blank, liquidity=blank,
    )
    fields.update(overrides)
    return StateVector(**fields)


# ---------------------------------------------------------------------------
# Standardization against OWN FULL HISTORY, not the recent window
# ---------------------------------------------------------------------------

def test_own_history_stat_uses_full_history_not_recent_window():
    # A long quiet regime, then a constant-ish elevated regime.
    rng = np.random.default_rng(2)
    quiet = 0.10 + rng.normal(0, 0.005, 500)
    elevated = 0.50 + rng.normal(0, 0.005, 60)
    series = np.concatenate([quiet, elevated])

    correct = _own_history_stat(series)             # standardized vs ALL of it
    wrong_recent_only = _own_history_stat(series[-60:])  # the mistake: recent-window-only

    assert correct.z is not None and correct.z > 2.0        # clearly elevated
    assert wrong_recent_only.z is not None
    assert abs(wrong_recent_only.z) < 1.0                    # looks "normal" to itself


def test_volatility_element_flags_regime_shift_via_full_history():
    closes = _regime_shift_closes()
    vector = compute_state_vector(
        as_of=date(2024, 1, 1),
        index_closes=closes,
        constituent_returns=pd.DataFrame(
            np.random.default_rng(3).normal(0, 0.01, (len(closes) - 1, 10))
        ),
        vol_windows=(21, 63),
        trend_horizons=(21, 63),
    )
    assert vector.volatility.available
    # Recent vol is ~6x the long-run vol; standardizing against the FULL
    # history should show this as strongly elevated, not "normal".
    assert vector.volatility.value > 2.0
    for w in ("21", "63"):
        assert vector.volatility.raw["windows"][w]["z"] > 1.5


# ---------------------------------------------------------------------------
# Schema versioning / breaking-change detection
# ---------------------------------------------------------------------------

def test_validate_schema_passes_for_current_vector():
    v = _minimal_vector()
    assert validate_schema(v, SCHEMA_VERSION) is True


def test_validate_schema_fails_on_version_change():
    v = dataclasses.replace(_minimal_vector(), schema_version="9.9.9")
    with pytest.raises(SchemaMismatchError):
        validate_schema(v, SCHEMA_VERSION)


def test_validate_schema_fails_on_element_length_change():
    v = dataclasses.replace(_minimal_vector(), element_order=list(ELEMENT_ORDER)[:-1])
    with pytest.raises(SchemaMismatchError):
        validate_schema(v, SCHEMA_VERSION)


def test_validate_schema_fails_on_element_order_change():
    swapped = list(ELEMENT_ORDER)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    v = dataclasses.replace(_minimal_vector(), element_order=swapped)
    with pytest.raises(SchemaMismatchError):
        validate_schema(v, SCHEMA_VERSION)


# ---------------------------------------------------------------------------
# Plain-language mapping (IMP-05)
# ---------------------------------------------------------------------------

def _er(available, value, raw=None, reason=None):
    return ElementReading(available=available, value=value, raw=raw or {}, reason=reason)


def test_plain_language_maps_thresholds_correctly():
    v = _minimal_vector(
        volatility=_er(True, 2.0),
        dispersion=_er(True, 1.5),
        correlation=_er(True, 0.2, raw={"z_level": 0.2, "z_rate_of_change": 1.6}),
        breadth=_er(True, -1.5),
        trend=_er(True, 1.0, raw={"sign_consistency": 1.0}),
        slippage=_er(False, None, reason="no fills"),
        liquidity=_er(True, -2.0),
    )
    phrases = plain_language(v)
    assert set(phrases.keys()) == set(ELEMENT_ORDER)
    assert phrases["volatility"] == "volatility elevated"
    assert phrases["dispersion"] == "dispersion rising"
    assert phrases["correlation"] == "correlation fusing"
    assert phrases["breadth"] == "breadth narrow"
    assert phrases["trend"] == "trend up, broadly confirmed across horizons"
    assert phrases["slippage"].startswith("slippage: not measurable")
    assert phrases["liquidity"] == "liquidity thin"


def test_plain_language_flags_mixed_trend_and_subdued_vol():
    v = _minimal_vector(
        volatility=_er(True, -2.0),
        trend=_er(True, 1.0, raw={"sign_consistency": 0.33}),
    )
    phrases = plain_language(v)
    assert phrases["volatility"] == "volatility subdued"
    assert phrases["trend"] == "trend mixed across horizons"


# ---------------------------------------------------------------------------
# Honesty: slippage and implied-vol are NEVER fabricated
# ---------------------------------------------------------------------------

def test_slippage_is_null_with_reason_when_no_fills():
    index_closes, cret, _, _, _, _ = _synthetic_universe()
    vector = compute_state_vector(
        as_of=date(2024, 1, 1),
        index_closes=index_closes,
        constituent_returns=cret,
        realized_fills=None,
    )
    assert vector.slippage.available is False
    assert vector.slippage.value is None
    assert vector.slippage.reason and "fill" in vector.slippage.reason.lower()


def test_implied_vol_is_null_with_reason_even_when_realized_vol_available():
    index_closes, cret, _, _, _, _ = _synthetic_universe()
    vector = compute_state_vector(
        as_of=date(2024, 1, 1),
        index_closes=index_closes,
        constituent_returns=cret,
    )
    assert vector.volatility.available is True          # realised vol IS available
    assert vector.volatility.raw["implied_vol"] is None  # but implied vol is NOT
    assert vector.volatility.raw["implied_vol_term_structure"] is None
    assert any("implied" in n.lower() for n in vector.volatility.notes)


def test_slippage_reports_real_value_when_fills_genuinely_given():
    fills = [
        {"expected_cost_bps": 5.0, "realized_cost_bps": 6.0},
        {"expected_cost_bps": 5.0, "realized_cost_bps": 5.5},
        {"expected_cost_bps": 5.0, "realized_cost_bps": 8.0},
    ]
    index_closes, cret, _, _, _, _ = _synthetic_universe()
    vector = compute_state_vector(
        as_of=date(2024, 1, 1),
        index_closes=index_closes,
        constituent_returns=cret,
        realized_fills=fills,
    )
    assert vector.slippage.available is True
    assert vector.slippage.raw["n_fills"] == 3
    assert abs(vector.slippage.raw["mean_slippage_bps"] - ((1.0 + 0.5 + 3.0) / 3)) < 1e-9


def test_liquidity_is_null_with_reason_when_nothing_supplied():
    index_closes, cret, _, _, _, _ = _synthetic_universe()
    vector = compute_state_vector(
        as_of=date(2024, 1, 1),
        index_closes=index_closes,
        constituent_returns=cret,
        index_highs=None, index_lows=None, volume_series=None,
    )
    assert vector.liquidity.available is False
    assert vector.liquidity.value is None
    assert vector.liquidity.reason


# ---------------------------------------------------------------------------
# End-to-end with a full synthetic universe
# ---------------------------------------------------------------------------

def test_compute_state_vector_end_to_end_and_schema_valid():
    index_closes, cret, cclose, highs, lows, vol = _synthetic_universe()
    vector = compute_state_vector(
        as_of=date(2024, 6, 1),
        index_closes=index_closes,
        constituent_returns=cret,
        constituent_closes=cclose,
        index_highs=highs,
        index_lows=lows,
        volume_series=vol,
        realized_fills=None,
    )
    assert validate_schema(vector, SCHEMA_VERSION) is True
    for name in ELEMENT_ORDER:
        assert hasattr(vector, name)

    assert vector.volatility.available
    assert vector.dispersion.available
    assert vector.correlation.available
    assert vector.breadth.available
    assert vector.trend.available
    assert vector.liquidity.available
    assert vector.slippage.available is False  # honest null, no fills given

    phrases = plain_language(vector)
    assert all(isinstance(p, str) and p for p in phrases.values())


def test_build_and_write_state_export_roundtrip(tmp_path=None):
    import json
    import tempfile
    from pathlib import Path

    index_closes, cret, cclose, highs, lows, vol = _synthetic_universe()
    vector = compute_state_vector(
        as_of=date(2024, 6, 1),
        index_closes=index_closes,
        constituent_returns=cret,
        constituent_closes=cclose,
        index_highs=highs,
        index_lows=lows,
        volume_series=vol,
    )
    payload = build_state_export(vector)
    assert payload["schema_version"] == SCHEMA_VERSION
    assert set(payload["state_vector"].keys()) >= set(ELEMENT_ORDER)
    assert payload["as_of"] == "2024-06-01"

    d = Path(tempfile.mkdtemp())
    out = d / "latest.json"
    written = write_state_export(payload, [out])
    assert written == [str(out)]
    reloaded = json.loads(out.read_text())
    assert reloaded["schema_version"] == SCHEMA_VERSION
    assert reloaded["state_vector"]["slippage"]["available"] is False

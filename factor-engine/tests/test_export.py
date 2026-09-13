"""Export schema conformance and honesty rules (betas populated only when
confidence == "ok"; the two data provenances are never mixed).

Also covers the TIINGO_API_KEY-gated live/synthetic-demo dispatch in
build_export()/build_live_export() -- the live path is exercised against
MOCKED `fac.adapters.prices_tiingo.fetch_daily_returns` and
`fac.adapters.french_factors.fetch_factor_panel` (this sandbox has no
outbound network access), never a real Tiingo or French Data Library call.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from fac import __version__ as ENGINE_VERSION
from fac.config import DEFAULT_LIVE_UNIVERSE, FACTOR_COLUMNS
from fac.export import SCHEMA_VERSION, build_export, build_synthetic_export
from fac.synthetic import DEFAULT_TICKERS, make_synthetic_universe

REQUIRED_ROW_FIELDS = {
    "ticker", "n_obs", "confidence", "abstain_reason", "alpha_daily",
    "alpha_annualized", "r2", "condition_number", "betas",
}


def test_build_synthetic_export_schema_shape():
    payload = build_synthetic_export(n_days=400, seed=1)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["data_provenance"] == "synthetic-demo"
    assert payload["universe"] == DEFAULT_TICKERS
    assert payload["factors"] == FACTOR_COLUMNS
    assert payload["disclaimer"]
    assert payload["as_of"]
    assert set(payload["factor_explainers"].keys()) == set(FACTOR_COLUMNS)

    assert len(payload["exposures"]) == len(payload["universe"])
    for row in payload["exposures"]:
        assert REQUIRED_ROW_FIELDS <= set(row.keys())
        assert row["confidence"] in {"ok", "insufficient_history", "degenerate"}


def test_synthetic_export_is_json_serializable_and_honest_about_betas():
    payload = build_synthetic_export(n_days=400, seed=2)
    raw = json.dumps(payload)  # must not raise (no NaN/inf/numpy scalars)
    reloaded = json.loads(raw)
    assert reloaded["schema_version"] == SCHEMA_VERSION

    for row in reloaded["exposures"]:
        if row["confidence"] == "ok":
            assert row["betas"] is not None
            assert row["alpha_daily"] is not None
            assert row["r2"] is not None
            assert len(row["betas"]) == len(FACTOR_COLUMNS)
            for b in row["betas"]:
                assert set(b.keys()) == {"factor", "beta", "se", "t_stat", "significant"}
        else:
            assert row["betas"] is None
            assert row["alpha_daily"] is None
            assert row["r2"] is None
            assert row["abstain_reason"]


def test_synthetic_export_400_days_clears_min_obs_and_reports_ok_for_every_demo_ticker():
    # 400 synthetic trading days is comfortably above MIN_OBS (126) and the
    # regression window (252) for every DEMO_TRUE_BETAS ticker -- this is a
    # positive control that the whole pipeline (synthetic data generation ->
    # alignment -> OLS -> gate) produces a real, non-abstained read end to
    # end, not just that abstains are formatted correctly.
    payload = build_synthetic_export(n_days=400, seed=7)
    for row in payload["exposures"]:
        assert row["confidence"] == "ok", row


def test_write_export_creates_both_copies():
    import tempfile
    from pathlib import Path

    from fac.export import write_export

    payload = build_synthetic_export(n_days=200, seed=3)
    # IMPORTANT: pass explicit temp paths -- write_export's default paths are
    # the REAL public/data/factor/latest.json handoff file; a test must
    # never overwrite that with a throwaway payload.
    with tempfile.TemporaryDirectory() as tmp:
        paths = [Path(tmp) / "a" / "latest.json", Path(tmp) / "b" / "latest.json"]
        written = write_export(payload, paths=paths)
        assert len(written) == 2
        for p in written:
            assert p.exists()
            on_disk = json.loads(p.read_text())
            assert on_disk["as_of"] == payload["as_of"]
            assert on_disk["data_provenance"] == "synthetic-demo"


def test_write_export_default_paths_point_at_the_real_handoff_locations():
    from fac.export import default_export_paths

    paths = default_export_paths()
    names = {str(p) for p in paths}
    assert any(n.endswith("public/data/factor/latest.json") for n in names)
    assert any(n.endswith("factor-engine/exports/latest.json") for n in names)


def test_build_export_falls_back_to_synthetic_when_key_unset(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    payload = build_export(n_days_synthetic=200, seed=5)
    assert payload["data_provenance"] == "synthetic-demo"


def _fake_factor_panel(n_days=300, seed=42) -> pd.DataFrame:
    from fac.synthetic import simulate_factor_panel

    return simulate_factor_panel(n_days, seed=seed)


def test_build_export_dispatches_to_live_when_key_set(monkeypatch):
    """The TIINGO_API_KEY gate itself: build_export() -- the same function
    the CLI (`python -m fac.export`) calls -- must route to the real
    Tiingo+French path the instant the key is set, exactly like
    src/app/api/whitewatch/predictions/route.js's ANTHROPIC_API_KEY check."""
    import fac.adapters.french_factors as french_adapter
    import fac.adapters.prices_tiingo as tiingo_adapter
    from fac.synthetic import DEMO_TRUE_BETAS, simulate_ticker_returns

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    panel = _fake_factor_panel()
    monkeypatch.setattr(french_adapter, "fetch_factor_panel", lambda **kw: panel)

    def fake_fetch_daily_returns(ticker, start=None, end=None, client=None):
        betas = DEMO_TRUE_BETAS.get(ticker, {"Mkt-RF": 1.0})
        return simulate_ticker_returns(panel, betas, seed=hash(ticker) % 1000)

    monkeypatch.setattr(tiingo_adapter, "fetch_daily_returns", fake_fetch_daily_returns)

    payload = build_export()
    assert payload["data_provenance"] == "live"
    assert payload["universe"] == DEFAULT_LIVE_UNIVERSE


def test_build_live_export_schema_and_honesty_gate_on_mocked_data(monkeypatch):
    """Full shape + honesty check on the live path: same required fields and
    same betas-only-when-confidence-ok rule as the synthetic-demo path (both
    go through the shared `regression.fit_factor_exposure` gate)."""
    import fac.adapters.french_factors as french_adapter
    import fac.adapters.prices_tiingo as tiingo_adapter
    from fac.export import build_live_export
    from fac.synthetic import DEMO_TRUE_BETAS, simulate_ticker_returns

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    panel = _fake_factor_panel(n_days=350)
    monkeypatch.setattr(french_adapter, "fetch_factor_panel", lambda **kw: panel)

    def fake_fetch_daily_returns(ticker, start=None, end=None, client=None):
        betas = DEMO_TRUE_BETAS.get(ticker, {"Mkt-RF": 1.0})
        return simulate_ticker_returns(panel, betas, seed=hash(ticker) % 1000)

    monkeypatch.setattr(tiingo_adapter, "fetch_daily_returns", fake_fetch_daily_returns)

    payload = build_live_export()
    assert payload["data_provenance"] == "live"
    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["universe"] == DEFAULT_LIVE_UNIVERSE
    assert len(payload["exposures"]) == len(DEFAULT_LIVE_UNIVERSE)

    raw = json.dumps(payload)  # must not raise (no NaN/inf/numpy scalars)
    reloaded = json.loads(raw)
    for row in reloaded["exposures"]:
        assert REQUIRED_ROW_FIELDS <= set(row.keys())
        assert row["confidence"] in {"ok", "insufficient_history", "degenerate"}
        if row["confidence"] == "ok":
            assert row["betas"] is not None and len(row["betas"]) == len(FACTOR_COLUMNS)
        else:
            assert row["betas"] is None


def test_build_live_export_raises_loudly_on_missing_tickers_rather_than_partial_export(monkeypatch):
    """A broken/partial Tiingo fetch must fail loudly, never silently ship a
    live export missing names or mix live with synthetic filler."""
    import fac.adapters.french_factors as french_adapter
    import fac.adapters.prices_tiingo as tiingo_adapter
    from fac.export import build_live_export

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    panel = _fake_factor_panel()
    monkeypatch.setattr(french_adapter, "fetch_factor_panel", lambda **kw: panel)

    def fake_fetch_daily_returns(ticker, start=None, end=None, client=None):
        if ticker == DEFAULT_LIVE_UNIVERSE[0]:
            return pd.Series(dtype=float, name=ticker)  # simulate no Tiingo coverage
        return pd.Series([0.001] * 200, index=panel.index[-200:], name=ticker)

    monkeypatch.setattr(tiingo_adapter, "fetch_daily_returns", fake_fetch_daily_returns)

    with pytest.raises(RuntimeError, match="no usable price history"):
        build_live_export()


def test_build_live_export_propagates_french_data_error_loudly(monkeypatch):
    """A broken French Data Library fetch/parse must also fail loudly, never
    silently fall back to synthetic factors inside a "live" export."""
    import fac.adapters.french_factors as french_adapter
    from fac.adapters.french_factors import FrenchDataError
    from fac.export import build_live_export

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")

    def boom(**kw):
        raise FrenchDataError("simulated French Data Library outage")

    monkeypatch.setattr(french_adapter, "fetch_factor_panel", boom)

    with pytest.raises(FrenchDataError, match="simulated"):
        build_live_export()

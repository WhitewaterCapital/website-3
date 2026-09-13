"""Export schema conformance and honesty rules (half_life_days populated only
when half_life_significant is true; confidence reflects data sufficiency).

Also covers the TIINGO_API_KEY-gated live/synthetic-demo dispatch in
build_export()/build_live_export() -- the live path is exercised against a
MOCKED `ge.adapters.prices_tiingo.fetch_close_panel` (this sandbox has no
outbound network access), never a real Tiingo call."""

from __future__ import annotations

import json

import pytest

from ge import __version__ as ENGINE_VERSION
from ge.export import SCHEMA_VERSION, build_export


def test_build_export_schema_shape():
    payload = build_export(n_sectors=2, per_sector=5, n_days=200, seed=1)

    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["data_provenance"] == "synthetic-demo"
    assert isinstance(payload["universe"], list) and len(payload["universe"]) == 10
    assert payload["disclaimer"]
    assert payload["as_of"]

    assert len(payload["residuals"]) == len(payload["universe"])
    required = {
        "ticker", "diffused_value", "residual", "residual_z",
        "half_life_days", "half_life_significant", "confidence",
    }
    for row in payload["residuals"]:
        assert required <= set(row.keys())
        assert row["confidence"] in {"insufficient", "significant", "not_significant"}


def test_export_is_json_serializable_and_honest_about_half_life():
    payload = build_export(n_sectors=2, per_sector=5, n_days=200, seed=2)
    raw = json.dumps(payload)  # must not raise (no NaN/inf/numpy scalars)
    reloaded = json.loads(raw)
    assert reloaded["schema_version"] == SCHEMA_VERSION

    for row in reloaded["residuals"]:
        if not row["half_life_significant"]:
            assert row["half_life_days"] is None
        else:
            assert row["half_life_days"] is not None
            assert row["half_life_days"] > 0
        if row["confidence"] == "insufficient":
            assert row["half_life_days"] is None
            assert row["half_life_significant"] is False


def test_write_export_creates_both_copies():
    import tempfile
    from pathlib import Path

    from ge.export import write_export

    payload = build_export(n_sectors=1, per_sector=4, n_days=150, seed=3)
    # IMPORTANT: pass explicit temp paths -- write_export's default paths are
    # the REAL public/data/graph/latest.json handoff file; a test must never
    # overwrite that with a throwaway 4-name payload.
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
    from ge.export import default_export_paths

    paths = default_export_paths()
    names = {str(p) for p in paths}
    assert any(n.endswith("public/data/graph/latest.json") for n in names)
    assert any(n.endswith("graph-engine/exports/latest.json") for n in names)


def test_build_export_falls_back_to_synthetic_when_key_unset(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    payload = build_export(n_sectors=2, per_sector=3, n_days=150, seed=5)
    assert payload["data_provenance"] == "synthetic-demo"


def test_build_export_dispatches_to_live_when_key_set(monkeypatch):
    """The TIINGO_API_KEY gate itself: build_export() -- the same function
    the CLI (`python -m ge.export`) calls -- must route to the real Tiingo
    path the instant the key is set, exactly like
    src/app/api/whitewatch/predictions/route.js's ANTHROPIC_API_KEY check."""
    import ge.adapters.prices_tiingo as tiingo_adapter
    from ge.config import SECTOR_MAP, UNIVERSE
    from ge.synthetic import returns_to_prices, simulate_returns

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    fake_prices = returns_to_prices(simulate_returns(UNIVERSE, SECTOR_MAP, n_days=300, seed=99))

    def fake_fetch_close_panel(tickers, start=None, end=None, client=None):
        assert set(tickers) == set(UNIVERSE)
        return fake_prices

    monkeypatch.setattr(tiingo_adapter, "fetch_close_panel", fake_fetch_close_panel)

    payload = build_export()
    assert payload["data_provenance"] == "live"


def test_build_live_export_schema_and_honesty_gate_on_mocked_tiingo_data(monkeypatch):
    """Full shape + honesty check on the live path: same required fields and
    same half_life_days-only-when-significant rule as the synthetic-demo
    path (both go through the shared `_residuals_for_universe` helper)."""
    import ge.adapters.prices_tiingo as tiingo_adapter
    from ge.config import SECTOR_MAP, UNIVERSE
    from ge.export import build_live_export
    from ge.synthetic import returns_to_prices, simulate_returns

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    fake_prices = returns_to_prices(simulate_returns(UNIVERSE, SECTOR_MAP, n_days=300, seed=11))
    monkeypatch.setattr(
        tiingo_adapter, "fetch_close_panel",
        lambda tickers, start=None, end=None, client=None: fake_prices,
    )

    payload = build_live_export()
    assert payload["data_provenance"] == "live"
    assert payload["engine_version"] == ENGINE_VERSION
    assert set(payload["universe"]) == set(UNIVERSE)
    assert len(payload["residuals"]) == len(UNIVERSE)

    required = {
        "ticker", "diffused_value", "residual", "residual_z",
        "half_life_days", "half_life_significant", "confidence",
    }
    raw = json.dumps(payload)  # must not raise (no NaN/inf/numpy scalars)
    reloaded = json.loads(raw)
    for row in reloaded["residuals"]:
        assert required <= set(row.keys())
        assert row["confidence"] in {"insufficient", "significant", "not_significant"}
        if not row["half_life_significant"]:
            assert row["half_life_days"] is None
        else:
            assert row["half_life_days"] is not None and row["half_life_days"] > 0


def test_build_live_export_raises_loudly_on_missing_tickers_rather_than_partial_export(monkeypatch):
    """A broken/partial Tiingo fetch must fail loudly, never silently ship a
    live export missing names or mix live with synthetic filler."""
    import ge.adapters.prices_tiingo as tiingo_adapter
    from ge.config import SECTOR_MAP, UNIVERSE
    from ge.export import build_live_export
    from ge.synthetic import returns_to_prices, simulate_returns

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    partial = UNIVERSE[:-3]
    partial_sectors = {t: SECTOR_MAP[t] for t in partial}
    partial_prices = returns_to_prices(simulate_returns(partial, partial_sectors, n_days=300, seed=3))
    monkeypatch.setattr(
        tiingo_adapter, "fetch_close_panel",
        lambda tickers, start=None, end=None, client=None: partial_prices,
    )

    with pytest.raises(RuntimeError, match="no usable price history"):
        build_live_export()

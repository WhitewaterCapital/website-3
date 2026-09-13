"""Export schema + write-path tests. Runs the real (synthetic-mode)
build_export()/write_export() and checks the resulting JSON is well-formed
and honest about its own provenance.

Also covers the TIINGO_API_KEY-gated live/synthetic-demo dispatch in
build_export() -- the live path is exercised against a MOCKED
`wf.adapters.prices_tiingo.fetch_universe_weekly_prices` (this sandbox has no
outbound network access), never a real Tiingo call."""

from __future__ import annotations

import json

import pytest

from wf import __version__ as ENGINE_VERSION
from wf.export import MIN_LIVE_WEEKS, build_export, write_export
from wf.config import UNIVERSE


def test_build_export_schema(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)  # pin this test to the synthetic path
    payload = build_export()
    for key in (
        "schema_version",
        "engine_version",
        "generated_at",
        "as_of",
        "universe",
        "disclaimer",
        "forecasts",
        "provenance",
        "validation",
    ):
        assert key in payload

    assert payload["engine_version"] == ENGINE_VERSION
    assert set(payload["universe"]) == set(UNIVERSE)
    assert "low-predictability" in payload["disclaimer"] or "not a set of price targets" in payload["disclaimer"]
    assert payload["provenance"]["kind"] == "synthetic-demo"

    assert len(payload["forecasts"]) == len(UNIVERSE)
    tickers_seen = set()
    for fc in payload["forecasts"]:
        for key in (
            "ticker",
            "expected_relative_return",
            "quantile_p10",
            "quantile_p50",
            "quantile_p90",
            "decile",
            "model_version",
            "feature_manifest_hash",
            "confidence",
            "rank_ic_oos",
            "provisional",
        ):
            assert key in fc
        assert fc["provisional"] is True
        assert fc["confidence"] == "research-grade"
        if fc["decile"] is not None:
            assert 1 <= fc["decile"] <= 10
        if fc["quantile_p10"] is not None and fc["quantile_p90"] is not None:
            assert fc["quantile_p10"] <= fc["quantile_p90"] + 1e-9
        tickers_seen.add(fc["ticker"])
    assert tickers_seen == set(UNIVERSE)


def test_build_export_validation_summary_is_honest_about_the_verdict(monkeypatch):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    payload = build_export()
    v = payload["validation"]
    assert v["n_folds"] >= 3
    assert v["model_version_published"] in ("ridge-1.0", "gbm-1.0")
    if v["model_version_published"] == "gbm-1.0":
        assert v["gbm_beats_baseline"] is True
    else:
        assert v["gbm_beats_baseline"] is False
    # Every published forecast should cite the model that actually won validation.
    assert all(fc["model_version"] == v["model_version_published"] for fc in payload["forecasts"])


def test_write_export_writes_both_copies(monkeypatch, tmp_path_dummy=None):
    monkeypatch.delenv("TIINGO_API_KEY", raising=False)
    payload = build_export()
    written = write_export(payload)
    assert len(written) == 2
    for p in written:
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["schema_version"] == payload["schema_version"]
        assert len(data["forecasts"]) == len(payload["forecasts"])


def _fake_live_weekly_prices(seed=42, n_weeks=200, signal_strength=0.3):
    from wf.synthetic import generate_synthetic_weekly_prices

    # Reuses the synthetic GENERATOR only as a stand-in Tiingo response shape
    # for this mocked test (this sandbox has no outbound network access) --
    # the point of the test is that build_export()'s LIVE branch runs this
    # data through the unmodified real pipeline and labels it "live", not
    # that the numbers themselves are real.
    return generate_synthetic_weekly_prices(UNIVERSE, n_weeks=n_weeks, seed=seed, signal_strength=signal_strength)


def test_build_export_dispatches_to_live_when_key_set(monkeypatch):
    """The TIINGO_API_KEY gate itself: build_export() must route to the real
    Tiingo path the instant the key is set, exactly like
    src/app/api/whitewatch/predictions/route.js's ANTHROPIC_API_KEY check."""
    import wf.adapters.prices_tiingo as tiingo_adapter

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    fake_prices = _fake_live_weekly_prices()
    monkeypatch.setattr(
        tiingo_adapter, "fetch_universe_weekly_prices",
        lambda tickers, start=None, end=None, client=None: fake_prices,
    )

    payload = build_export()
    assert payload["provenance"]["kind"] == "live"


def test_build_export_live_schema_and_honesty_on_mocked_tiingo_data(monkeypatch):
    """Full shape check on the live path -- same required forecast fields,
    same 'the published model cites the model that actually won validation'
    rule, run through the unmodified real feature/label/model/validation
    pipeline (only `weekly_prices`'s source differs from the synthetic
    tests above)."""
    import wf.adapters.prices_tiingo as tiingo_adapter

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    fake_prices = _fake_live_weekly_prices(seed=7)
    monkeypatch.setattr(
        tiingo_adapter, "fetch_universe_weekly_prices",
        lambda tickers, start=None, end=None, client=None: fake_prices,
    )

    payload = build_export()
    assert payload["engine_version"] == ENGINE_VERSION
    assert payload["provenance"]["kind"] == "live"
    assert payload["provenance"]["n_weeks"] == 200
    assert set(payload["universe"]) == set(UNIVERSE)
    assert len(payload["forecasts"]) == len(UNIVERSE)

    raw = json.dumps(payload)  # must not raise (no NaN/inf/numpy scalars)
    reloaded = json.loads(raw)
    v = reloaded["validation"]
    for fc in reloaded["forecasts"]:
        for key in (
            "ticker", "expected_relative_return", "quantile_p10", "quantile_p50",
            "quantile_p90", "decile", "model_version", "feature_manifest_hash",
            "confidence", "rank_ic_oos", "provisional",
        ):
            assert key in fc
        assert fc["model_version"] == v["model_version_published"]
        if fc["decile"] is not None:
            assert 1 <= fc["decile"] <= 10


def test_build_export_live_raises_loudly_on_too_little_history(monkeypatch):
    """A broken/thin Tiingo fetch must fail loudly, never silently ship a
    live export built on too little history to validate anything."""
    import wf.adapters.prices_tiingo as tiingo_adapter

    monkeypatch.setenv("TIINGO_API_KEY", "test-token-123")
    fake_prices = _fake_live_weekly_prices(n_weeks=MIN_LIVE_WEEKS - 1)
    monkeypatch.setattr(
        tiingo_adapter, "fetch_universe_weekly_prices",
        lambda tickers, start=None, end=None, client=None: fake_prices,
    )

    with pytest.raises(RuntimeError, match="too little weekly history"):
        build_export()

"""Export schema + write-path tests. Runs the real (synthetic-mode)
build_export()/write_export() and checks the resulting JSON is well-formed
and honest about its own provenance."""

from __future__ import annotations

import json

from wf import __version__ as ENGINE_VERSION
from wf.export import build_export, write_export
from wf.config import UNIVERSE


def test_build_export_schema():
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


def test_build_export_validation_summary_is_honest_about_the_verdict():
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


def test_write_export_writes_both_copies(tmp_path_dummy=None):
    payload = build_export()
    written = write_export(payload)
    assert len(written) == 2
    for p in written:
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["schema_version"] == payload["schema_version"]
        assert len(data["forecasts"]) == len(payload["forecasts"])

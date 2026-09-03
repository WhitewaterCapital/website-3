"""Export schema conformance and honesty rules (half_life_days populated only
when half_life_significant is true; confidence reflects data sufficiency)."""

from __future__ import annotations

import json

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

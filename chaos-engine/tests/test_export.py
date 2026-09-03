"""Tests for the website handoff export: schema shape, honesty fields present
on every reading, and that `main()` actually writes both output paths.

Speed note: the real demo export (`DEMO_N_SESSIONS` x `DEMO_BARS_PER_SESSION`
x 5 tickers) is deliberately large enough to be a realistic multi-session
panel, which makes it slow to call several times in a test run. Every test
here shrinks those constants via monkeypatch (as the module's own comment
invites) rather than exercising the full-size panel repeatedly — the
full-size panel is exercised for real exactly once, by
`chaos/export.py`'s own `python -m chaos.export` run that produced the
committed `exports/latest.json` / `public/data/chaos/latest.json`."""

from __future__ import annotations

import json

import chaos.export as export_mod
from chaos.export import DISCLAIMER, build_export, write_export


def _shrink(monkeypatch):
    """Shrink the synthetic-demo panel so tests run in well under a second
    each instead of tens of seconds, without touching production behaviour
    (nothing about `main()` / the real committed export uses this)."""
    monkeypatch.setattr(export_mod, "DEMO_N_SESSIONS", 3)
    monkeypatch.setattr(export_mod, "DEMO_BARS_PER_SESSION", 40)
    monkeypatch.setattr(export_mod, "WATCHLIST", ["AAPL", "MSFT"])


def test_build_export_schema_shape(monkeypatch):
    _shrink(monkeypatch)
    payload = build_export()
    for key in (
        "schema_version",
        "engine_version",
        "generated_at",
        "as_of",
        "watchlist",
        "provenance",
        "disclaimer",
        "readings",
    ):
        assert key in payload

    assert payload["provenance"] == "synthetic-demo"
    assert "not high frequency trading" in payload["disclaimer"]
    assert "1 to 15 minute" in payload["disclaimer"]
    assert payload["disclaimer"] == DISCLAIMER
    assert len(payload["readings"]) == len(payload["watchlist"])


def test_every_reading_has_required_fields_and_eight_components(monkeypatch):
    _shrink(monkeypatch)
    payload = build_export()
    expected_components = {
        "volatility_ratio",
        "volume_surprise",
        "range_spread_deterioration",
        "cross_sectional_dispersion",
        "correlation_shift",
        "order_flow_imbalance",
        "jump_indicator",
        "novelty",
    }
    for r in payload["readings"]:
        for key in (
            "ticker",
            "chaos_index",
            "state_label",
            "components",
            "directional_probability",
            "calibrated",
            "abstain",
            "as_of",
        ):
            assert key in r, f"missing {key} in reading {r.get('ticker')}"
        assert r["calibrated"] is True
        assert set(r["components"].keys()) == expected_components
        for name, comp in r["components"].items():
            assert "available" in comp, f"{name} missing available flag"
        assert r["state_label"] in ("calm", "stressed", "dislocated", "cascade")


def test_write_export_writes_both_paths(monkeypatch):
    _shrink(monkeypatch)
    payload = build_export()
    written = write_export(payload)
    assert len(written) == 2
    for p in written:
        assert p.exists()
        loaded = json.loads(p.read_text())
        assert loaded["schema_version"] == payload["schema_version"]
        assert loaded["provenance"] == "synthetic-demo"

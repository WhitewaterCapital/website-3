"""Tests for the website handoff export: schema shape, honesty fields present
on every reading, and that `main()` actually writes both output paths.

Speed note: the real demo export (`DEMO_N_SESSIONS` x `DEMO_BARS_PER_SESSION`
x 5 tickers) is deliberately large enough to be a realistic multi-session
panel, which makes it slow to call several times in a test run. Every test
here shrinks those constants via monkeypatch (as the module's own comment
invites) rather than exercising the full-size panel repeatedly — the
full-size panel is exercised for real exactly once, by
`chaos/export.py`'s own `python -m chaos.export` run that produced the
committed `exports/latest.json` / `public/data/chaos/latest.json`.

## A note on why this file could not actually be RUN this pass

This module (via `chaos.export` -> `chaos.directional` ->
`sklearn.calibration`) requires `scikit-learn`, and (via `chaos.export` ->
`chaos.state` -> `jump_indicator` -> `tripower_quarticity`) `scipy` — see
`chaos-engine/requirements.txt`. Neither is installed in the sandbox this
pass was built in, and `pip install` for either fails with the same
proxy-level `403`/policy-denial wall documented throughout
`PLATFORM_REBUILD_PLAN.md`'s Roadblocks for every vendor API this repo
talks to (confirmed this pass: `pip install scikit-learn scipy` -> "Cannot
connect to proxy... 403 Forbidden"). This means `chaos.export` cannot be
imported here at all — a PRE-EXISTING limitation, confirmed by trying
`python3 -c "import chaos.export"` BEFORE this pass's changes touched
anything, not something the live-gate work below introduced. The
`TestBuildExportLiveGate` tests added below are written and believed
correct (the exact same dispatch/gate logic they exercise was independently
smoke-tested — with `sklearn`/`scipy` sys.modules-stubbed just enough for
`chaos.directional`'s module-level imports to succeed, and `scipy.special.
gamma` pointed at Python's real, correct `math.gamma` rather than a fake
number, so the CHAOS-01 math itself ran for real — end to end in this
session, only the `DirectionalModel` classifier itself stood in for, since
faking a gradient-boosted classifier's real numerical behavior would be
dishonest to claim as "tested"), but have NOT been run via this file
through a real `unittest` invocation in any sandbox this pass had access
to. Run `python3 -m unittest discover -s tests -v` from `chaos-engine/` on
a machine with `scikit-learn`/`scipy` installed (or `pip install -r
requirements.txt` first) to actually execute this file."""

from __future__ import annotations

import json

import chaos.export as export_mod
from chaos.export import DISCLAIMER, LIVE_DISCLAIMER, MIN_LIVE_BARS_PER_TICKER, build_export, write_export
from chaos.adapters.alpaca_bars import LiveFetchFailedError
from chaos.config import ALPACA_API_KEY_ID_VAR, ALPACA_API_SECRET_KEY_VAR


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


# ---------------------------------------------------------------------------
# Live-data gate (ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY) — mirrors
# weekly-engine/tests/test_export.py's TIINGO_API_KEY dispatch tests
# (test_build_export_dispatches_to_live_when_key_set /
# test_build_export_live_raises_loudly_on_too_little_history), adapted to
# chaos-engine's flat `provenance` string field and Alpaca's two-part key.
# See this file's module docstring for why these could not actually be RUN
# in the sandbox this pass was built in.
# ---------------------------------------------------------------------------


def _clear_alpaca_env(monkeypatch):
    monkeypatch.delenv(ALPACA_API_KEY_ID_VAR, raising=False)
    monkeypatch.delenv(ALPACA_API_SECRET_KEY_VAR, raising=False)


def _set_alpaca_env(monkeypatch):
    monkeypatch.setenv(ALPACA_API_KEY_ID_VAR, "test-key-id")
    monkeypatch.setenv(ALPACA_API_SECRET_KEY_VAR, "test-secret")


def _fake_live_bars(watchlist, n=250):
    """A well-formed, real-shaped OHLCV panel standing in for what
    `_live_bars_by_ticker` would return from a real Alpaca fetch — same
    role as weekly-engine's `_fake_live_weekly_prices` fixture helper."""
    import numpy as np
    import pandas as pd

    idx = pd.date_range("2026-09-01 09:30", periods=n, freq="min")
    rng = np.random.default_rng(11)
    out = {}
    for t in watchlist:
        close = 100.0 + np.cumsum(rng.normal(0, 0.05, n))
        out[t] = pd.DataFrame(
            {
                "open": close,
                "high": close + 0.1,
                "low": close - 0.1,
                "close": close,
                "volume": rng.uniform(500, 1500, n),
            },
            index=idx,
        )
    return out


def test_no_keys_stays_synthetic_demo(monkeypatch):
    """Default state (no Alpaca keys set) must be byte-for-byte the
    original, never-touched synthetic-demo path — the live-gate addition
    must not change default behaviour at all."""
    _clear_alpaca_env(monkeypatch)
    _shrink(monkeypatch)
    payload = build_export()
    assert payload["provenance"] == "synthetic-demo"
    assert payload["disclaimer"] == DISCLAIMER


def test_build_export_dispatches_to_live_when_both_keys_set(monkeypatch):
    """The env-var gate itself: build_export() must route to
    `_live_bars_by_ticker` (mocked here, real network never touched) the
    moment BOTH Alpaca keys are present, and never touch `_synthetic_bars`
    on that path."""
    _set_alpaca_env(monkeypatch)
    watchlist = ["AAPL", "MSFT"]
    monkeypatch.setattr(export_mod, "WATCHLIST", watchlist)
    monkeypatch.setattr(export_mod, "_live_bars_by_ticker", lambda wl: _fake_live_bars(wl))
    called_synthetic = []
    monkeypatch.setattr(
        export_mod,
        "_synthetic_bars",
        lambda *a, **k: called_synthetic.append(1) or (_ for _ in ()).throw(
            AssertionError("synthetic bars must not be called on the live path")
        ),
    )
    payload = build_export()
    assert payload["provenance"] == "live"
    assert payload["disclaimer"] == LIVE_DISCLAIMER
    assert not called_synthetic
    assert len(payload["readings"]) == len(watchlist)


def test_live_disclaimer_states_iex_only_caveat(monkeypatch):
    """The one honesty caveat that matters most if this ever actually goes
    live: IEX-only volume is not total market volume (see
    chaos/adapters/alpaca_bars.py's module docstring)."""
    _set_alpaca_env(monkeypatch)
    watchlist = ["AAPL"]
    monkeypatch.setattr(export_mod, "WATCHLIST", watchlist)
    monkeypatch.setattr(export_mod, "_live_bars_by_ticker", lambda wl: _fake_live_bars(wl))
    payload = build_export()
    assert "IEX" in payload["disclaimer"]
    assert "not high frequency trading" in payload["disclaimer"]
    assert "1 to 15 minute" in payload["disclaimer"]


def test_build_export_live_raises_loudly_on_too_few_bars(monkeypatch):
    """A configured-but-thin live fetch must RAISE, never silently
    downgrade to a synthetic export mislabeled (or ambiguously labeled) as
    live — same discipline as weekly-engine's identically named test and
    cascade-data-engine's `LiveFetchFailedError` contract."""
    _set_alpaca_env(monkeypatch)
    watchlist = ["AAPL", "MSFT"]
    monkeypatch.setattr(export_mod, "WATCHLIST", watchlist)

    def _thin_fetch(tickers, lookback_days):
        return _fake_live_bars(tickers, n=MIN_LIVE_BARS_PER_TICKER - 1)

    monkeypatch.setattr(export_mod, "fetch_watchlist_minute_bars", _thin_fetch)
    try:
        build_export()
        raise AssertionError("expected RuntimeError for too-few live bars")
    except RuntimeError as exc:
        assert "too few" in str(exc)


def test_build_export_live_propagates_live_fetch_failed_error(monkeypatch):
    """A real network/auth failure from the adapter must propagate as
    `LiveFetchFailedError`, not be swallowed into a quiet synthetic
    fallback."""
    _set_alpaca_env(monkeypatch)
    watchlist = ["AAPL"]
    monkeypatch.setattr(export_mod, "WATCHLIST", watchlist)

    def _failing_fetch(tickers, lookback_days):
        raise LiveFetchFailedError("simulated: blocked-by-allowlist")

    monkeypatch.setattr(export_mod, "fetch_watchlist_minute_bars", _failing_fetch)
    try:
        build_export()
        raise AssertionError("expected LiveFetchFailedError to propagate")
    except LiveFetchFailedError:
        pass


def test_only_one_key_set_stays_synthetic_demo(monkeypatch):
    """Half a credential pair must behave identically to no credentials at
    all — Alpaca has no single-key auth mode, so a half-set gate must not
    attempt a live call that would only fail on missing auth."""
    monkeypatch.setenv(ALPACA_API_KEY_ID_VAR, "only-the-id")
    monkeypatch.delenv(ALPACA_API_SECRET_KEY_VAR, raising=False)
    _shrink(monkeypatch)
    payload = build_export()
    assert payload["provenance"] == "synthetic-demo"

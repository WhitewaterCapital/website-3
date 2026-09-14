"""Website handoff export — the one JSON the site reads.

Runs the full CHAOS-01 -> CHAOS-02 pipeline over a small illustrative
watchlist and writes a contract-compliant JSON to:

  * <repo>/public/data/chaos/latest.json   (web-servable)
  * <chaos-engine>/exports/latest.json     (engine-side copy)

Run:  python -m chaos.export

## Live-data gate

Gated exactly like `weekly-engine/wf/export.py`'s `TIINGO_API_KEY` check,
adapted to Alpaca's two-part key: `build_export()` looks for BOTH
`ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` in `os.environ` (see
`chaos/adapters/alpaca_bars.py` for the adapter and, in its module
docstring, the full research trail on why Alpaca's free "Basic" Market Data
API plan was chosen over Twelve Data/Finnhub/Polygon-Massive/unofficial
Yahoo Finance endpoints — the open item `PLATFORM_REBUILD_PLAN.md`'s
Roadblocks left as "WW-Chaos cannot go live... a genuinely bigger, separate
build").

  * BOTH KEYS SET   -> `_live_bars_by_ticker()` fetches REAL 1-minute OHLCV
    bars for `chaos.config.WATCHLIST` from Alpaca's IEX feed. That feeds the
    SAME, unmodified CHAOS-01/CHAOS-02 pipeline below — no model-math
    changes, only the data source — and the export's `provenance` is
    `"live"`. A live fetch that fails (network refused, bad credentials, too
    little history returned) RAISES rather than silently falling back to
    synthetic data wearing a live-adjacent label — see
    `_live_bars_by_ticker`'s docstring.
  * EITHER KEY UNSET -> exactly the prior, never-touched behaviour: a
    deterministic synthetic intraday panel from `_synthetic_bars`,
    `provenance` `"synthetic-demo"`. This is the default in every sandbox
    this repo has been built in, since no live keys are, or can be,
    configured there (see the adapter module's docstring for the confirmed
    network-wall evidence).

The two provenances are never mixed within one export: `build_export()`
picks exactly one bar source and runs the whole pipeline on it, same
discipline as `weekly-engine/wf/export.py::build_export`.

Honesty:
  * `provenance` is stamped `"synthetic-demo"` or `"live"` depending on the
    gate above — never a fixed constant regardless of what actually ran.
  * `disclaimer` states the "not HFT" framing verbatim, plus (live mode
    only) the IEX-only-volume caveat from the adapter's docstring.
  * every component carries its own `available: bool` — an unavailable
    component (no quote data, no news feed) is reported as unavailable, never
    silently filled with a fabricated number.
  * `calibrated: true` reflects that `directional_probability` comes out of
    `CalibratedClassifierCV`, not a raw score.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__ as ENGINE_VERSION
from .adapters.alpaca_bars import LiveFetchFailedError, fetch_watchlist_minute_bars
from .config import (
    ALPACA_API_KEY_ID_VAR,
    ALPACA_API_SECRET_KEY_VAR,
    ComponentConfig,
    ExecutionConfig,
    StateConfig,
    WATCHLIST,
    env,
    exports_dir,
    repo_root,
)
from .directional import DirectionalConfig, DirectionalModel, build_features, make_direction_labels
from .state import compute_state

SCHEMA_VERSION = "0.1.0"

# Synthetic-demo panel size. Pulled out as module constants (rather than
# hardcoded call-site literals) so tests can shrink them for speed without
# touching the generator itself.
DEMO_N_SESSIONS = 40
DEMO_BARS_PER_SESSION = 120

DISCLAIMER = (
    "WW-CHAOS is a research model, not investment advice or an order. "
    "This is not high frequency trading: there is no colocated infrastructure "
    "and no microsecond order-book access. What is reachable is intraday "
    "dislocation capture on a 1 to 15 minute horizon. The directional "
    "probability is produced by a calibrated gradient-boosted classifier, an "
    "explicitly simplified stand-in for the design's causal dilated-TCN (no "
    "local deep-learning framework is available and there is no network "
    "access to install one). This export runs in synthetic-demo mode: every "
    "figure below comes from a locally generated synthetic intraday panel, "
    "not a live market feed."
)

# Live-mode counterpart of DISCLAIMER above — same "not HFT" framing, minus
# the synthetic-panel sentence (replaced with what IS true in live mode: a
# real feed, plus the one honesty caveat that feed brings with it). See
# chaos/adapters/alpaca_bars.py's module docstring for the full IEX-only-
# volume writeup this sentence summarizes.
LIVE_DISCLAIMER = (
    "WW-CHAOS is a research model, not investment advice or an order. "
    "This is not high frequency trading: there is no colocated infrastructure "
    "and no microsecond order-book access. What is reachable is intraday "
    "dislocation capture on a 1 to 15 minute horizon. The directional "
    "probability is produced by a calibrated gradient-boosted classifier, an "
    "explicitly simplified stand-in for the design's causal dilated-TCN (no "
    "local deep-learning framework is available and there is no network "
    "access to install one). This export runs on REAL 1-minute bars fetched "
    "live from Alpaca's Market Data API (free 'Basic' plan, IEX feed only — "
    "not the consolidated SIP tape, so volume-derived components reflect "
    "IEX's share of volume, not total market volume; see "
    "chaos/adapters/alpaca_bars.py for the full caveat)."
)

# How far back to request live 1-minute bars. 16 calendar days comfortably
# covers >= 10 trading sessions even across a long weekend, meeting
# ComponentConfig's volume_lookback_sessions=10 requirement for
# volume_surprise to actually report `available=True` rather than just
# warming up; also comfortably clears every other component's much shorter
# window (jump_window=60 bars, min_bars_for_component=20) and
# DirectionalConfig's "need >= 40 labelled, fully-featured rows" floor.
LIVE_LOOKBACK_DAYS = 16

# Below this many real bars for any one watchlist ticker, a "live" export
# would be technically well-formed JSON but not a meaningfully computed one
# (most components still warming up, the directional classifier under- or
# un-trained) — refuse to publish it as `provenance: "live"` rather than let
# a thin real fetch masquerade as a fully-functioning live read. Comfortably
# below one full session's 390 bars (so a fetch made shortly after a single
# session opens doesn't spuriously fail) but well above every component's
# warm-up floor.
MIN_LIVE_BARS_PER_TICKER = 200


def _synthetic_bars(
    ticker: str, n_sessions: int = 40, bars_per_session: int = 120, seed: int = 0
) -> pd.DataFrame:
    """A deterministic synthetic 1-minute intraday panel: a repeating
    intraday volume curve (so volume_surprise has real seasonal shape to
    control for) plus a mean-reverting-with-occasional-jump price path (so
    the jump indicator and the state machine have something real to find).
    NOT live data — synthetic-demo mode only."""
    rng = np.random.default_rng(abs(hash(ticker)) % (2**32) ^ seed)
    n = n_sessions * bars_per_session
    minute_of_day = np.tile(np.arange(bars_per_session), n_sessions)
    # U-shaped intraday volume curve, repeated every session.
    u_shape = 1.0 + 2.0 * np.exp(-((minute_of_day - 0) ** 2) / (2 * 15.0 ** 2)) + \
        2.0 * np.exp(-((minute_of_day - (bars_per_session - 1)) ** 2) / (2 * 15.0 ** 2))
    base_volume = 50_000.0 * u_shape
    volume = np.maximum(base_volume * (1.0 + rng.normal(0, 0.15, n)), 100.0)

    logret = rng.normal(0.0, 0.0006, n)
    # Sprinkle a few genuine jumps so the BNS test and state machine have
    # something real to detect in the demo output.
    jump_positions = rng.choice(n, size=max(1, n // 400), replace=False)
    logret[jump_positions] += rng.choice([-1, 1], size=len(jump_positions)) * rng.uniform(0.01, 0.03, len(jump_positions))
    # Volume spikes alongside jumps (a dislocation looks like both at once).
    volume[jump_positions] *= rng.uniform(3.0, 6.0, len(jump_positions))

    price0 = 100.0 + (abs(hash(ticker)) % 50)
    close = price0 * np.exp(np.cumsum(logret))
    open_ = np.roll(close, 1)
    open_[0] = price0
    span = np.abs(rng.normal(0, 0.15, n)) * close / 100.0 + 0.01
    high = np.maximum(open_, close) + span
    low = np.minimum(open_, close) - span

    start = pd.Timestamp("2026-06-01 09:30")
    idx = []
    for s in range(n_sessions):
        day = start + pd.Timedelta(days=s)
        idx.extend(pd.date_range(day, periods=bars_per_session, freq="min"))
    idx = pd.DatetimeIndex(idx[:n])

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx
    )


def _live_data_configured() -> bool:
    """True only when BOTH Alpaca env vars are set — matches
    `AlpacaBarsAdapter.is_configured()` exactly (duplicated rather than
    imported so this check needs no network-capable object constructed just
    to ask the question; `chaos/adapters/alpaca_bars.py::
    AlpacaBarsAdapter.__init__` reads the same two vars the same way)."""
    return bool(env(ALPACA_API_KEY_ID_VAR)) and bool(env(ALPACA_API_SECRET_KEY_VAR))


def _live_bars_by_ticker(watchlist: list[str]) -> dict[str, pd.DataFrame]:
    """Real per-ticker 1-minute OHLCV over the trailing `LIVE_LOOKBACK_DAYS`
    calendar days, fetched from Alpaca (see
    `chaos/adapters/alpaca_bars.py::fetch_watchlist_minute_bars`, and that
    module's docstring for the full research trail on the provider and the
    IEX-only-volume caveat).

    Raises `LiveFetchFailedError` (propagated from the adapter, unchanged)
    if the real HTTP call itself fails, and a plain `RuntimeError` if the
    call succeeds but returns too little history for any watchlist ticker
    to run the pipeline meaningfully — NEVER falls back to synthetic data
    in either case. Same discipline as
    `weekly-engine/wf/export.py::_live_weekly_prices`: a broken or thin live
    fetch must be a loud failure, not a silently partial or
    mixed-provenance export wearing `provenance: "live"` it did not earn."""
    bars_by_ticker = fetch_watchlist_minute_bars(watchlist, lookback_days=LIVE_LOOKBACK_DAYS)
    too_short = {t: len(df) for t, df in bars_by_ticker.items() if len(df) < MIN_LIVE_BARS_PER_TICKER}
    if too_short:
        raise RuntimeError(
            "Alpaca returned too few 1-minute bars to run the live pipeline "
            f"meaningfully (need >= {MIN_LIVE_BARS_PER_TICKER} bars/ticker over the "
            f"trailing {LIVE_LOOKBACK_DAYS} days): {too_short}. Refusing to publish a "
            "partial/mixed-provenance live export — see chaos/export.py's module "
            "docstring."
        )
    return bars_by_ticker


def _component_payload(latest: pd.Series) -> dict:
    return {
        "volatility_ratio": {
            "available": bool(latest["vol_ratio_available"]),
            "value": None if pd.isna(latest["vol_ratio"]) else round(float(latest["vol_ratio"]), 4),
        },
        "volume_surprise": {
            "available": bool(latest["volume_z_available"]),
            "value": None if pd.isna(latest["volume_z"]) else round(float(latest["volume_z"]), 4),
        },
        "range_spread_deterioration": {
            "available": bool(latest["range_ratio_available"]),
            "value": None if pd.isna(latest["range_ratio"]) else round(float(latest["range_ratio"]), 4),
            "spread_bps": {
                "available": bool(latest["spread_available"]),
                "value": None if pd.isna(latest["spread_bps"]) else round(float(latest["spread_bps"]), 4),
            },
        },
        "cross_sectional_dispersion": {
            "available": bool(latest["dispersion_available"]),
            "value": None if pd.isna(latest["dispersion"]) else round(float(latest["dispersion"]), 6),
        },
        "correlation_shift": {
            "available": bool(latest["corr_shift_available"]),
            "value": None if pd.isna(latest["corr_shift"]) else round(float(latest["corr_shift"]), 4),
        },
        "order_flow_imbalance": {
            "available": bool(latest["flow_imbalance_available"]),
            "value": None if pd.isna(latest["flow_imbalance"]) else round(float(latest["flow_imbalance"]), 4),
            "method": str(latest["flow_method"]),
        },
        "jump_indicator": {
            "available": bool(latest["jump_available"]),
            "relative_jump": None if pd.isna(latest["jump_rj"]) else round(float(latest["jump_rj"]), 4),
            "z_stat": None if pd.isna(latest["jump_z"]) else round(float(latest["jump_z"]), 4),
        },
        "novelty": {
            "available": bool(latest["novelty_available"]),
            "value": None if pd.isna(latest["novelty_value"]) else round(float(latest["novelty_value"]), 4),
        },
    }


def build_export() -> dict:
    """Gated exactly as described in this module's docstring: real live
    bars when both Alpaca env vars are set (never mixed with synthetic
    data on partial failure — see `_live_bars_by_ticker`), the original
    deterministic synthetic panel otherwise."""
    watchlist = list(WATCHLIST)
    if _live_data_configured():
        bars_by_ticker = _live_bars_by_ticker(watchlist)
        provenance = "live"
        disclaimer = LIVE_DISCLAIMER
    else:
        bars_by_ticker = {
            t: _synthetic_bars(t, n_sessions=DEMO_N_SESSIONS, bars_per_session=DEMO_BARS_PER_SESSION)
            for t in watchlist
        }
        provenance = "synthetic-demo"
        disclaimer = DISCLAIMER
    close_panel = pd.DataFrame({t: df["close"] for t, df in bars_by_ticker.items()})

    comp_cfg = ComponentConfig()
    state_cfg = StateConfig()
    dcfg = DirectionalConfig()

    readings = []
    as_of = None
    for t in watchlist:
        bars = bars_by_ticker[t]
        result = compute_state(
            bars,
            comp_cfg=comp_cfg,
            state_cfg=state_cfg,
            universe_prices=close_panel,
        )
        latest = result.latest()

        X = build_features(bars, dcfg)
        y = make_direction_labels(bars, dcfg.horizon)
        model = DirectionalModel(dcfg).fit(X, y)
        pred = model.predict(X).iloc[-1]

        ts = bars.index[-1]
        as_of = max(as_of, ts) if as_of is not None else ts

        readings.append(
            {
                "ticker": t,
                "chaos_index": None if pd.isna(latest["chaos_index"]) else round(float(latest["chaos_index"]), 4),
                "state_label": str(latest["state_label"]),
                "components": _component_payload(latest),
                "directional_probability": None if pd.isna(pred["probability"]) else round(float(pred["probability"]), 4),
                "calibrated": True,
                "abstain": bool(pred["abstain"]),
                "uncertainty": None if pd.isna(pred["uncertainty"]) else round(float(pred["uncertainty"]), 4),
                "as_of": ts.isoformat(),
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.isoformat() if as_of is not None else None,
        "watchlist": watchlist,
        "provenance": provenance,
        "disclaimer": disclaimer,
        "readings": readings,
    }


def write_export(payload: dict) -> list[Path]:
    engine_dir = Path(__file__).resolve().parent.parent
    root = repo_root()
    paths = [
        root / "public" / "data" / "chaos" / "latest.json",
        engine_dir / "exports" / "latest.json",
    ]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    return paths


def main() -> int:
    payload = build_export()
    written = write_export(payload)
    states: dict[str, int] = {}
    for r in payload["readings"]:
        states[r["state_label"]] = states.get(r["state_label"], 0) + 1
    print(f"Exported {len(payload['readings'])} readings (as of {payload['as_of']}).")
    print(f"  state distribution: {states}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

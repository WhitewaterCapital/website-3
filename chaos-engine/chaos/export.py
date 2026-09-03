"""Website handoff export — the one JSON the site reads.

Runs the full CHAOS-01 -> CHAOS-02 pipeline in SYNTHETIC-DEMO mode (there is
no live intraday data feed wired into this repository) over a small
illustrative watchlist, and writes a contract-compliant JSON to:

  * <repo>/public/data/chaos/latest.json   (web-servable)
  * <chaos-engine>/exports/latest.json     (engine-side copy)

Run:  python -m chaos.export

Honesty:
  * `provenance` is stamped "synthetic-demo" — every number in this export
    comes from a locally generated synthetic intraday panel, NOT a live
    market feed. Swapping in a real feed only touches `_synthetic_bars`.
  * `disclaimer` states the "not HFT" framing verbatim.
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
from .config import ComponentConfig, ExecutionConfig, StateConfig, WATCHLIST, exports_dir, repo_root
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
    watchlist = list(WATCHLIST)
    bars_by_ticker = {
        t: _synthetic_bars(t, n_sessions=DEMO_N_SESSIONS, bars_per_session=DEMO_BARS_PER_SESSION)
        for t in watchlist
    }
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
        "provenance": "synthetic-demo",
        "disclaimer": DISCLAIMER,
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

"""WW-STATE export — CLI entry point that actually RUNS `state.compute_state_vector`.

Website handoff export — the one JSON the site reads.

Same pattern as `export.py` (the equity-security exporter already in this
package) and as `weekly-engine/wf/export.py` / `graph-engine/ge/export.py` /
`chaos-engine/chaos/export.py`: a `build_export()`-shaped function does the
work and returns a dict, `write_export()`-shaped function writes it to both
the web-servable path and an engine-side copy, `main()` is the CLI entry
point.

Until this file existed, `state.py` had real, tested math
(`compute_state_vector`, `build_state_export`, `write_state_export`) but NO
CLI entry point anywhere — `public/data/state/latest.json` was a hand-typed
fixture, never produced by running code. This module closes that gap.

NO REAL UNIVERSE/INDEX FEED IN THIS SANDBOX: there is no live index or
constituent price feed wired into this engine (see README "Current status"),
so this always runs in synthetic-demo mode — a deterministic, seeded
synthetic market (one shared factor + idiosyncratic noise per name, same
"single market factor" construction `engine/tests/test_state.py`'s own
`_synthetic_universe` fixture uses to exercise `compute_state_vector`)
standing in for a real index + constituent panel. `universe_note` in the
export says so explicitly, exactly the wording already used in the
previously hand-authored fixture this replaces, so nothing downstream can
mistake it for a real market read.

Two of the seven elements are honestly reported as unavailable, not
fabricated, regardless of synthetic vs real inputs: implied-vol term
structure (`volatility.raw.implied_vol`, no options feed) and `slippage`
(`realized_fills=None` here, since there is no realised broker-fill history
in this sandbox either) — see `state.py`'s own module docstring.

Run:  python3 -m incepta.export_state     (from engine/, with engine/ on PYTHONPATH)
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .state import build_state_export, compute_state_vector, write_state_export

# --- synthetic-demo panel parameters (deterministic, seeded) ----------------
N_DAYS = 900          # enough history for the 252d vol/trend window + margin
N_TICKERS = 25
SEED = 42
TARGET_CORR = 0.18    # average pairwise correlation the synthetic panel is built to hit

UNIVERSE_NOTE = (
    "SYNTHETIC DEMO DATA: this export was generated from a randomly-simulated "
    f"universe of {N_TICKERS} synthetic tickers (SYN00..SYN{N_TICKERS - 1:02d}), not real "
    "market data, so the website seam has something real to read before a live "
    "index/universe feed is wired in."
)


def _synthetic_market(
    n_days: int = N_DAYS,
    n_tickers: int = N_TICKERS,
    seed: int = SEED,
    target_corr: float = TARGET_CORR,
):
    """Deterministic, seeded synthetic index + constituent panel.

    Same construction as `engine/tests/test_state.py`'s `_synthetic_universe`
    fixture (one shared market factor plus idiosyncratic noise per name,
    mixed to hit `target_corr`) — proven to exercise every element of
    `compute_state_vector` (it is exactly what that test suite runs against).
    Returns `(index_closes, constituent_returns, constituent_closes,
    index_highs, index_lows, volume_series)`, all aligned per
    `compute_state_vector`'s documented input shapes.
    """
    rng = np.random.default_rng(seed)
    market = rng.normal(0.0003, 0.01, n_days)
    idio = rng.normal(0.0, 0.015, (n_days, n_tickers))
    beta = np.sqrt(target_corr)
    rets = beta * market[:, None] + np.sqrt(1 - target_corr) * idio

    tickers = [f"SYN{i:02d}" for i in range(n_tickers)]
    dates = pd.bdate_range(end=pd.Timestamp.now(tz="UTC").normalize(), periods=n_days)
    constituent_returns = pd.DataFrame(rets, index=dates, columns=tickers)
    constituent_closes = 100.0 * (1.0 + constituent_returns).cumprod()

    index_closes = np.concatenate([[100.0], 100.0 * np.cumprod(1.0 + market)])
    highs = index_closes * (1.0 + rng.uniform(0.001, 0.01, index_closes.size))
    lows = index_closes * (1.0 - rng.uniform(0.001, 0.01, index_closes.size))
    volume = rng.uniform(1e6, 2e6, index_closes.size)

    return index_closes, constituent_returns, constituent_closes, highs, lows, volume


def build_export():
    """Run the REAL `compute_state_vector` over the synthetic-demo panel and
    return `(payload_dict, as_of_date)`. `realized_fills` is left `None` —
    honest, not fabricated: this sandbox has no realised broker-fill history,
    so `slippage.available` comes back `False` exactly as it would on a real
    deployment that hasn't wired up execution data yet."""
    index_closes, constituent_returns, constituent_closes, highs, lows, volume = _synthetic_market()

    as_of = datetime.now(timezone.utc).date()
    vector = compute_state_vector(
        as_of=as_of,
        index_closes=index_closes,
        constituent_returns=constituent_returns,
        constituent_closes=constituent_closes,
        index_highs=highs,
        index_lows=lows,
        volume_series=volume,
        realized_fills=None,
    )
    payload = build_state_export(vector)
    # `universe_note` is the StateExport contract's documented optional field
    # for demo/synthetic exports (src/lib/models/state-export.ts) — present
    # here, absent once a live universe feed is wired in.
    payload["universe_note"] = UNIVERSE_NOTE
    return payload, as_of


def default_export_paths() -> list[Path]:
    engine_dir = Path(__file__).resolve().parents[1]  # engine/
    repo_root = engine_dir.parent
    return [
        repo_root / "public" / "data" / "state" / "latest.json",  # web-servable
        engine_dir / "exports" / "state_latest.json",              # engine-side copy
    ]


def main() -> int:
    payload, as_of = build_export()
    written = write_state_export(payload, default_export_paths())

    available = [name for name in payload["state_vector"]["element_order"]
                 if payload["state_vector"][name]["available"]]
    unavailable = [name for name in payload["state_vector"]["element_order"]
                   if not payload["state_vector"][name]["available"]]
    print(f"Exported WW-STATE vector (as of {as_of.isoformat()}, synthetic-demo).")
    print(f"  available:   {available}")
    print(f"  unavailable: {unavailable}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

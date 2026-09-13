"""Website handoff export — the one JSON the site reads.

Writes a contract-compliant JSON to:

  * <repo>/public/data/graph/latest.json   (web-servable)
  * <engine>/exports/latest.json            (engine-side copy)

Run:  python -m ge.export

Gated exactly like `src/app/api/whitewatch/predictions/route.js`'s
ANTHROPIC_API_KEY check: `build_export()` looks for `TIINGO_API_KEY` in
`os.environ` (see `ge/adapters/prices_tiingo.py`, same free key
intra-exitus-engine and Incepta already use).

  * KEY SET   -> `build_live_export()` fetches real daily closes for
    `ge.config.UNIVERSE` via Tiingo and runs them through the SAME, unmodified
    `run_history` -> `fit_ou` pipeline used below — no model math changes,
    only the data source — and the payload is labeled
    `"data_provenance": "live"`.
  * KEY UNSET -> exactly the prior behaviour: a deterministic synthetic
    universe/price history from `ge.synthetic`, labeled
    `"data_provenance": "synthetic-demo"`. This is the never-touched fallback
    demo path so the website seam has something to read even with no key
    configured.

The two provenances are never mixed within one export: each `build_export()`
call is fully one or the other.

Honesty, same as the other engines: a name with too little residual history to
fit a half-life gets `"confidence": "insufficient"` and `half_life_days: null`
— reversion never invents a number. A name with enough history but a
statistically insignificant fit gets `"confidence": "not_significant"` and
`half_life_days: null` too (per `reversion.fit_ou`'s Dickey-Fuller gate) —
`half_life_days` is populated ONLY when `half_life_significant` is true. This
gate is identical in the live and synthetic-demo paths — see
`_residuals_for_universe` below, the one place either path computes it.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from . import __version__ as ENGINE_VERSION
from .pipeline import PipelineConfig, run_history
from .reversion import fit_ou
from .synthetic import make_universe, returns_to_prices, simulate_returns

SCHEMA_VERSION = "1.0.0"
DISCLAIMER = (
    "WW-GRAPH is a graph-diffusion pairs research model: it spreads each "
    "name's signal across a correlation/sector graph of its peers, and treats "
    "the gap between the name's actual signal and its graph-implied "
    "neighbourhood value as a candidate mean-reverting residual. A half-life "
    "is reported ONLY when the residual's own history shows statistically "
    "significant reversion (Dickey-Fuller gate) — otherwise the model abstains "
    "rather than invent a number. Research/paper output only; not investment "
    "advice, not a validated alpha model."
)

MIN_HISTORY_FOR_OU = 20


def _confidence(n_obs: int, significant: bool) -> str:
    if n_obs < MIN_HISTORY_FOR_OU:
        return "insufficient"
    return "significant" if significant else "not_significant"


def _residuals_for_universe(hist: pd.DataFrame, tickers: list[str]) -> list[dict]:
    """The one place either provenance path turns a `run_history` panel into
    the export's per-name residual/half-life rows — same honesty gate
    (Dickey-Fuller-significant reversion only) applied identically whether
    `hist` came from `ge.synthetic` or real Tiingo prices."""
    as_of = hist["date"].max()
    latest = hist[hist["date"] == as_of].set_index("ticker")

    residuals = []
    for t in tickers:
        series = (
            hist.loc[hist["ticker"] == t]
            .sort_values("date")["residual_z_sector_neutral"]
            .to_numpy()
        )
        half_life_days = None
        significant = False
        n_obs = int(series.size)
        if n_obs >= MIN_HISTORY_FOR_OU:
            try:
                params = fit_ou(series, dt=1.0)
            except ValueError:
                params = None
            if params is not None:
                significant = bool(params.reverts)
                if significant:
                    half_life_days = round(float(params.half_life), 2)

        row = latest.loc[t] if t in latest.index else None
        residuals.append(
            {
                "ticker": t,
                "diffused_value": round(float(row["diffused"]), 6) if row is not None else None,
                "residual": round(float(row["residual"]), 6) if row is not None else None,
                "residual_z": round(float(row["residual_z_sector_neutral"]), 4) if row is not None else None,
                "half_life_days": half_life_days,
                "half_life_significant": significant,
                "confidence": _confidence(n_obs, significant),
            }
        )
    return residuals


def build_export(
    n_sectors: int = 6,
    per_sector: int = 10,
    n_days: int = 300,
    seed: int = 7,
    cfg: PipelineConfig | None = None,
) -> dict:
    """Single entry point, gated on `TIINGO_API_KEY` exactly as described in
    this module's docstring. `n_sectors`/`per_sector`/`n_days`/`seed` apply
    ONLY to the synthetic-demo fallback below — a live run always uses
    `ge.config.UNIVERSE`/`SECTOR_MAP` instead (see `build_live_export`)."""
    if os.environ.get("TIINGO_API_KEY", "").strip():
        return build_live_export(cfg)

    cfg = cfg or PipelineConfig()
    tickers, sector_of = make_universe(n_sectors, per_sector)
    rets = simulate_returns(tickers, sector_of, n_days, seed=seed)
    prices = returns_to_prices(rets)

    hist = run_history(prices, sector_of, cfg)
    residuals = _residuals_for_universe(hist, tickers)
    as_of = hist["date"].max()

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of.strftime("%Y-%m-%d"),
        "universe": tickers,
        "disclaimer": DISCLAIMER,
        "data_provenance": "synthetic-demo",
        "residuals": residuals,
    }


def build_live_export(cfg: PipelineConfig | None = None) -> dict:
    """The real-data path: fetch daily closes for `ge.config.UNIVERSE` from
    Tiingo, run them through the SAME `run_history` pipeline
    (`construct.py`/`diffusion.py`/`residual.py`/`reversion.py` are untouched
    by this function), and label the result `"data_provenance": "live"`.

    Raises `RuntimeError` if Tiingo returns unusable/insufficient history for
    any covered name — this never falls back to synthetic data or partially
    fills a live export with fabricated values; a broken live fetch is a
    loud failure, not a silent one, and the caller (e.g. `main()`) should let
    it propagate rather than write a corrupt or mixed-provenance export.
    """
    from .adapters.prices_tiingo import TiingoClient, fetch_close_panel
    from .config import UNIVERSE, SECTOR_MAP, LIVE_HISTORY_CALENDAR_DAYS

    cfg = cfg or PipelineConfig()
    start = date.today() - timedelta(days=LIVE_HISTORY_CALENDAR_DAYS)
    client = TiingoClient()
    prices = fetch_close_panel(UNIVERSE, start=start, client=client)

    missing = [t for t in UNIVERSE if t not in prices.columns]
    if missing:
        raise RuntimeError(
            "Tiingo returned no usable price history for: "
            f"{missing} — refusing to publish a partial/mixed-provenance live export."
        )

    hist = run_history(prices, SECTOR_MAP, cfg)
    residuals = _residuals_for_universe(hist, UNIVERSE)
    as_of = hist["date"].max()
    as_of_str = as_of.strftime("%Y-%m-%d") if hasattr(as_of, "strftime") else str(as_of)

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of_str,
        "universe": list(UNIVERSE),
        "disclaimer": DISCLAIMER,
        "data_provenance": "live",
        "residuals": residuals,
    }


def default_export_paths() -> list[Path]:
    engine_dir = Path(__file__).resolve().parent.parent
    repo_root = engine_dir.parent
    return [
        repo_root / "public" / "data" / "graph" / "latest.json",
        engine_dir / "exports" / "latest.json",
    ]


def write_export(payload: dict, paths: list[Path] | None = None) -> list[Path]:
    """Write `payload` to `paths` (default: the real website + engine-copy
    locations, see `default_export_paths`). Tests should pass their own
    `paths` (e.g. a temp directory) rather than relying on the default, so
    that running the test suite never overwrites the real handoff file."""
    paths = paths if paths is not None else default_export_paths()
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    return paths


def main() -> int:
    payload = build_export()
    written = write_export(payload)
    conf: dict[str, int] = {}
    for r in payload["residuals"]:
        conf[r["confidence"]] = conf.get(r["confidence"], 0) + 1
    print(f"Exported {len(payload['residuals'])} names (as of {payload['as_of']}, {payload['data_provenance']}).")
    print(f"  confidence: {conf}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

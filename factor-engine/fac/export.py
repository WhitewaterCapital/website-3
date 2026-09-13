"""Website handoff export — the one JSON the site reads.

Writes a contract-compliant JSON to:

  * <repo>/public/data/factor/latest.json   (web-servable)
  * <engine>/exports/latest.json             (engine-side copy)

Run:  python -m fac.export

Gated exactly like `graph-engine/ge/export.py` / `weekly-engine/wf/export.py`
(and, at the website layer, `src/app/api/whitewatch/predictions/route.js`'s
ANTHROPIC_API_KEY check): `build_export()` looks for `TIINGO_API_KEY` in
`os.environ` — the same free key every other engine in this repo already
uses (`fac/adapters/prices_tiingo.py`).

  * KEY SET   -> `build_live_export()` fetches real daily closes (Tiingo) for
    a small fixed demo universe (`fac.config.DEFAULT_LIVE_UNIVERSE`) and real
    daily factor returns (Kenneth French Data Library, no key needed —
    `fac/adapters/french_factors.py`), and runs them through the SAME,
    unmodified `regression.fit_factor_exposure` used below — no model math
    changes, only the data source — labeled `"data_provenance": "live"`.
  * KEY UNSET -> a deterministic synthetic universe/price/factor panel from
    `fac.synthetic`, labeled `"data_provenance": "synthetic-demo"`. This is
    the never-touched fallback demo path so the website seam has something
    to read even with no key configured.

The two provenances are never mixed within one export: each `build_export()`
call is fully one or the other.

WHY A FIXED SMALL UNIVERSE, NOT "ANY TICKER ON DEMAND": every model in this
repo reaches the website the same way — a Python process writes one static
JSON file, and a Next.js API route/lib function reads it (see
`src/lib/weekly.ts`, `src/lib/graph.ts`). There is no live invocation of this
engine from the Node process. A truly general "factor exposure for any
ticker the user types in" would need an on-demand compute path (a job queue,
or the API route shelling out to Python per request) that is architecturally
out of scope for this repo's existing export pattern — see
factor-engine/README.md's "Current status" for the honest limitation this
implies (the Ticker Hub panel can only show a beta for a name in
`fac.config.DEFAULT_LIVE_UNIVERSE`, exactly the same "not in the research
universe" honesty case `weekly-engine`'s WeeklyCard already handles for its
own fixed universe).

Honesty, same as the other engines: a ticker with too little overlapping
(price, factor) history to fit gets `"confidence": "insufficient_history"`
and `"betas": null` — the regression never invents a number. A ticker whose
regression is numerically degenerate over the window gets
`"confidence": "degenerate"` and `"betas": null` too. This gate is identical
in the live and synthetic-demo paths — see `_export_row`/`regression.py`'s
`fit_factor_exposure`, the one place either path applies it.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import __version__ as ENGINE_VERSION
from .config import (
    DEFAULT_LIVE_UNIVERSE,
    FACTOR_COLUMNS,
    FACTOR_EXPLAINERS,
    LIVE_HISTORY_CALENDAR_DAYS,
    MIN_OBS,
    RF_COLUMN,
    WINDOW_TRADING_DAYS,
)
from .regression import FactorFit, fit_factor_exposure
from .synthetic import DEFAULT_TICKERS, make_synthetic_universe

SCHEMA_VERSION = "1.0.0"
DISCLAIMER = (
    "WW-FACTOR is a Fama-French factor-exposure read: it regresses a ticker's "
    "trailing daily excess return on the Mkt-RF, SMB, HML, RMW, CMA, and Mom "
    "factors from the Kenneth French Data Library to estimate how much of "
    "its return pattern looks like broad market beta, a size tilt, a value "
    "tilt, a profitability tilt, an investment tilt, or a momentum tilt. "
    "Betas are reported ONLY when there is enough overlapping price/factor "
    "history and the regression is numerically well-posed — otherwise the "
    "model abstains rather than invent a number. This is DESCRIPTIVE RISK "
    "CONTEXT, not a directional buy/sell signal: a high market beta is "
    "neither bullish nor bearish on its own, and this model is deliberately "
    "NOT wired into the site's composite conviction score (see "
    "src/lib/models/conviction.ts's comment on why). Research/paper output "
    "only; not investment advice."
)


def _export_row(ticker: str, fit: FactorFit) -> dict:
    betas = None
    if fit.betas is not None:
        betas = [
            {
                "factor": b.factor,
                "beta": round(b.beta, 4),
                "se": round(b.se, 4),
                "t_stat": round(b.t_stat, 2),
                "significant": b.significant,
            }
            for b in fit.betas
        ]
    return {
        "ticker": ticker,
        "n_obs": fit.n_obs,
        "confidence": fit.confidence,
        "abstain_reason": fit.abstain_reason,
        "alpha_daily": round(fit.alpha, 6) if fit.alpha is not None else None,
        "alpha_annualized": round(fit.alpha_annualized, 4) if fit.alpha_annualized is not None else None,
        "r2": round(fit.r2, 4) if fit.r2 is not None else None,
        "condition_number": round(fit.condition_number, 1) if fit.condition_number is not None else None,
        "betas": betas,
    }


def _as_of_str(idx) -> str:
    m = idx.max()
    return m.strftime("%Y-%m-%d") if hasattr(m, "strftime") else str(m)


def build_export(
    tickers: list[str] | None = None,
    n_days_synthetic: int = 400,
    seed: int = 7,
) -> dict:
    """Single entry point, gated on `TIINGO_API_KEY` exactly as described in
    this module's docstring. `n_days_synthetic`/`seed` apply ONLY to the
    synthetic-demo fallback below — a live run always uses
    `fac.config.DEFAULT_LIVE_UNIVERSE` (or a caller-supplied `tickers`)
    instead (see `build_live_export`)."""
    if os.environ.get("TIINGO_API_KEY", "").strip():
        return build_live_export(tickers)
    return build_synthetic_export(tickers, n_days=n_days_synthetic, seed=seed)


def build_synthetic_export(tickers: list[str] | None = None, n_days: int = 400, seed: int = 7) -> dict:
    tickers = tickers if tickers is not None else DEFAULT_TICKERS
    panel, returns = make_synthetic_universe(n_days=n_days, seed=seed, tickers=tickers)

    exposures = []
    for t in tickers:
        fit = fit_factor_exposure(
            returns[t], panel, FACTOR_COLUMNS, RF_COLUMN, window=WINDOW_TRADING_DAYS
        )
        exposures.append(_export_row(t, fit))

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": _as_of_str(panel.index),
        "universe": list(tickers),
        "window_trading_days": WINDOW_TRADING_DAYS,
        "min_obs": MIN_OBS,
        "factors": FACTOR_COLUMNS,
        "factor_explainers": FACTOR_EXPLAINERS,
        "disclaimer": DISCLAIMER,
        "data_provenance": "synthetic-demo",
        "exposures": exposures,
    }


def build_live_export(tickers: list[str] | None = None) -> dict:
    """The real-data path: fetch real daily closes (Tiingo) for `tickers`
    (default `fac.config.DEFAULT_LIVE_UNIVERSE`) and the real daily Fama-
    French + momentum factor panel (Kenneth French Data Library, no key
    required), then run them through the SAME `regression.fit_factor_exposure`
    used by the synthetic path — no model-math changes, only the data source
    — and label the result `"data_provenance": "live"`.

    Raises `RuntimeError` if Tiingo returns unusable price history for any
    requested ticker, or if the French Data Library fetch/parse fails
    (`fac.adapters.french_factors.FrenchDataError`, itself a `RuntimeError`
    subclass) — this never falls back to synthetic data or partially fills a
    live export with fabricated values; a broken live fetch is a loud
    failure, not a silent one, matching graph-engine's/weekly-engine's
    build_live_export() behaviour exactly.
    """
    from .adapters.french_factors import fetch_factor_panel
    from .adapters.prices_tiingo import TiingoClient, fetch_daily_returns

    tickers = tickers if tickers is not None else DEFAULT_LIVE_UNIVERSE
    client = TiingoClient()
    start = date.today() - timedelta(days=LIVE_HISTORY_CALENDAR_DAYS)

    # Real factor panel from the Kenneth French Data Library. Let
    # FrenchDataError propagate as-is (it IS a RuntimeError) rather than
    # catching and re-wrapping — the caller sees exactly what failed.
    factor_panel = fetch_factor_panel()

    exposures = []
    missing: list[str] = []
    for t in tickers:
        returns = fetch_daily_returns(t, start=start, client=client)
        if returns.empty:
            missing.append(t)
            continue
        fit = fit_factor_exposure(
            returns, factor_panel, FACTOR_COLUMNS, RF_COLUMN, window=WINDOW_TRADING_DAYS
        )
        exposures.append(_export_row(t, fit))

    if missing:
        raise RuntimeError(
            "Tiingo returned no usable price history for: "
            f"{missing} — refusing to publish a partial/mixed-provenance live export."
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        # Reflects the last date covered by the French factor panel, which
        # can genuinely lag "today" by a few business days — Ken French's
        # library is updated roughly monthly, not intraday (see
        # french_factors.py's module docstring and FRENCH_CACHE_TTL_SECONDS).
        # This is real data lag, not a bug, and is exactly why it is
        # surfaced here rather than stamping `as_of` with today's date.
        "as_of": _as_of_str(factor_panel.index),
        "universe": list(tickers),
        "window_trading_days": WINDOW_TRADING_DAYS,
        "min_obs": MIN_OBS,
        "factors": FACTOR_COLUMNS,
        "factor_explainers": FACTOR_EXPLAINERS,
        "disclaimer": DISCLAIMER,
        "data_provenance": "live",
        "exposures": exposures,
    }


def default_export_paths() -> list[Path]:
    engine_dir = Path(__file__).resolve().parent.parent
    repo_root = engine_dir.parent
    return [
        repo_root / "public" / "data" / "factor" / "latest.json",
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
    for r in payload["exposures"]:
        conf[r["confidence"]] = conf.get(r["confidence"], 0) + 1
    print(f"Exported {len(payload['exposures'])} names (as of {payload['as_of']}, {payload['data_provenance']}).")
    print(f"  confidence: {conf}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

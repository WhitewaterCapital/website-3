"""Website handoff export — the one JSON the site reads.

Same pattern as intra-exitus-engine/ie/export.py: build_export() does the
work and returns a dict, write_export() writes it to both the web-servable
path and an engine-side copy, main() is the CLI entry point.

Gated exactly like `src/app/api/whitewatch/predictions/route.js`'s
ANTHROPIC_API_KEY check: `build_export()` looks for `TIINGO_API_KEY` in
`os.environ` (see `wf/adapters/prices_tiingo.py`, same free key
intra-exitus-engine and Incepta already use).

  * KEY SET   -> `_live_weekly_prices()` fetches real weekly-resampled OHLCV
    for `wf.config.UNIVERSE` (unchanged — 16 real tickers) from Tiingo. That
    feeds the SAME, unmodified feature/label/model/validation pipeline below
    — no model-math changes, only the data source — and the export's
    `provenance.kind` is `"live"`.
  * KEY UNSET -> exactly the prior behaviour: a plausible-but-fake weekly
    panel from `wf.synthetic` with a small embedded signal calibrated to the
    spec's own "genuinely good" 0.02-0.05 OOS rank IC band, `provenance.kind`
    `"synthetic-demo"`. This is the never-touched fallback demo path.

The two provenances are never mixed within one export: `build_export()`
picks exactly one `weekly_prices` source and runs the whole pipeline on it.

Run:  python3 -m wf.export        (from weekly-engine/, with weekly-engine on PYTHONPATH)
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__ as ENGINE_VERSION
from .config import (
    EMBARGO_WEEKS,
    LABEL_HORIZON_WEEKS,
    LIVE_HISTORY_START,
    SECTOR_MAP,
    UNIVERSE,
    exports_dir,
    repo_root,
)
from .features import build_feature_panel
from .features.panel import feature_manifest_hash
from .model.gbm import fit_gbm, predict_gbm
from .model.neutralize import decile_of, neutralize_predictions
from .model.quantile import fit_quantile_models, predict_quantiles, sort_quantiles
from .model.ridge import fit_ridge, predict_ridge, rank_transform_features
from .synthetic import generate_synthetic_weekly_prices
from .validation.harness import run_walk_forward

# A live weekly frame needs at least this many weeks for the pipeline to be
# meaningful: 52 (the longest lookback, `mom_52`/`dist_52w_high`) plus real
# room for several purged walk-forward folds after warmup. Far below this
# and a "live" export would be technically well-formed but not actually
# validated on anything — fail loudly instead (see `_live_weekly_prices`).
MIN_LIVE_WEEKS = 120

SCHEMA_VERSION = "1.0.0"
DISCLAIMER = (
    "WW-WEEKLY is a research-grade, low-predictability weekly cross-sectional rank signal, "
    "not a set of price targets and not investment advice. Weekly equity returns are close to "
    "unpredictable in level terms; a sustained out-of-sample rank information coefficient of "
    "0.02-0.05 is a genuinely good result for this model family. The ordering across names is "
    "the intended output, not the size of any single number. A result far above that range is "
    "a signal to suspect a data leak before it is trusted as an edge."
)

# Calibrated (see weekly-engine/README.md's "synthetic validation numbers")
# so the synthetic demo's OOS rank IC lands inside the spec's own "genuinely
# good" 0.02-0.05 band rather than near 0 or (a leak smell) suspiciously high.
DEMO_SIGNAL_STRENGTH = 0.30
DEMO_N_WEEKS = 320
DEMO_SEED = 13


def _synthetic_calendar_start(n_weeks: int) -> str:
    """The live export's synthetic panel used a fixed historical start date
    (synthetic.DEFAULT_START, 2015-01-02), so however many weeks it ran for
    landed wherever the arithmetic put it -- in practice this had drifted to
    "as of 2021-02-12" with zero relationship to when the export actually
    ran, which reads as stale data even though the run itself was fresh
    (generated_at was always today). This anchors the synthetic calendar's
    LAST week to the most recent Friday on/before today instead, so as_of
    always looks current -- the panel is exactly as fake as before, just
    dated sensibly. synthetic.py's own DEFAULT_START and its test fixtures
    are untouched; this only changes what the live export passes in.
    """
    today = date.today()
    last_friday = today - timedelta(days=(today.weekday() - 4) % 7)
    first_friday = last_friday - timedelta(weeks=n_weeks - 1)
    return first_friday.isoformat()


def _synthetic_provenance() -> dict:
    return {
        "kind": "synthetic-demo",
        "note": (
            "No real point-in-time weekly price/volume feed is wired into this sandbox. "
            "This export was generated from wf.synthetic (a fabricated, seeded panel with a "
            "deliberately small embedded signal) purely to exercise the full pipeline end to "
            "end and produce a well-formed export file. It is NOT a real forecast."
        ),
        "generator": "wf.synthetic.generate_synthetic_weekly_prices",
        "seed": DEMO_SEED,
        "signal_strength": DEMO_SIGNAL_STRENGTH,
        "n_weeks": DEMO_N_WEEKS,
    }


def _synthetic_weekly_prices() -> dict:
    return generate_synthetic_weekly_prices(
        UNIVERSE,
        n_weeks=DEMO_N_WEEKS,
        seed=DEMO_SEED,
        signal_strength=DEMO_SIGNAL_STRENGTH,
        start=_synthetic_calendar_start(DEMO_N_WEEKS),
    )


def _live_weekly_prices() -> dict:
    """Real weekly-resampled OHLCV for every name in `wf.config.UNIVERSE`,
    fetched from Tiingo. Raises `RuntimeError` (never falls back to
    synthetic data) if any covered ticker comes back with too little history
    to run the real pipeline on — a broken live fetch must be a loud
    failure, not a silently partial or mixed-provenance export."""
    from .adapters.prices_tiingo import TiingoClient, fetch_universe_weekly_prices

    client = TiingoClient()
    weekly_prices = fetch_universe_weekly_prices(
        UNIVERSE, start=date.fromisoformat(LIVE_HISTORY_START), client=client
    )
    too_short = {t: len(df) for t, df in weekly_prices.items() if len(df) < MIN_LIVE_WEEKS}
    if too_short:
        raise RuntimeError(
            "Tiingo returned too little weekly history to run the live pipeline "
            f"(need >= {MIN_LIVE_WEEKS} weeks): {too_short} — refusing to publish a "
            "partial/mixed-provenance live export."
        )
    return weekly_prices


def _live_provenance(n_weeks: int) -> dict:
    return {
        "kind": "live",
        "note": (
            "Real point-in-time daily OHLCV from Tiingo (free tier), resampled to weekly, "
            "feeding the unmodified real feature/label/model/validation pipeline below. "
            "`seed` and `signal_strength` are not meaningful for real market data (there is "
            "no fixture to seed or a controlled signal to strength) and are carried at 0 "
            "purely for schema compatibility with the synthetic-demo provenance shape above "
            "-- read `n_weeks` (the real weekly history actually used) instead."
        ),
        "generator": "wf.adapters.prices_tiingo.fetch_universe_weekly_prices",
        "seed": 0,
        "signal_strength": 0.0,
        "n_weeks": n_weeks,
    }


def build_export() -> dict:
    """Single entry point, gated on `TIINGO_API_KEY` exactly as described in
    this module's docstring."""
    # NOTE: named `use_live_data`, not `live` -- this function later reuses
    # the name `live` for the last-week forecast frame (unrelated, existing
    # code); a shared name here would shadow it and read as a mistake.
    use_live_data = bool(os.environ.get("TIINGO_API_KEY", "").strip())
    if use_live_data:
        weekly_prices = _live_weekly_prices()
        provenance = _live_provenance(n_weeks=min(len(df) for df in weekly_prices.values()))
    else:
        weekly_prices = _synthetic_weekly_prices()
        provenance = _synthetic_provenance()

    panel, feature_cols, manifest = build_feature_panel(weekly_prices, SECTOR_MAP)
    manifest_hash = feature_manifest_hash(manifest)

    report = run_walk_forward(
        panel,
        feature_cols,
        label_col="sector_relative_fwd_return",
        n_splits=6,
        horizon=LABEL_HORIZON_WEEKS,
        embargo=EMBARGO_WEEKS,
        min_train=100,
    )
    oos_rank_ic = report.gbm_mean_rank_ic if report.gbm_beats_baseline else report.ridge_mean_rank_ic
    model_version = "gbm-1.0" if report.gbm_beats_baseline else "ridge-1.0"

    # --- fit the PUBLISHED model on ALL available history (the walk-forward
    # above is validation only; the export's live forecast is the best use of
    # every observed week, same as a real deployment would do). ------------
    train_mask = panel["sector_relative_fwd_return"].notna()
    train = panel[train_mask]
    y_train = train["sector_relative_fwd_return"].to_numpy(dtype=float)
    last_week = panel[panel["week"] == panel["week"].max()]

    if report.gbm_beats_baseline:
        X_train = train[feature_cols].to_numpy(dtype=float)
        X_live = last_week[feature_cols].to_numpy(dtype=float)
        model = fit_gbm(X_train, y_train)
        point_pred = predict_gbm(model, X_live)
    else:
        ranked_all = rank_transform_features(panel, feature_cols)
        X_train = ranked_all.loc[train.index].to_numpy(dtype=float)
        X_live = ranked_all.loc[last_week.index].to_numpy(dtype=float)
        model = fit_ridge(X_train, y_train)
        point_pred = predict_ridge(model, X_live)

    q_models = fit_quantile_models(X_train, y_train)
    q_preds = sort_quantiles(predict_quantiles(q_models, X_live))

    # NOTE on units: `neutral_pred` (-> "expected_relative_return" below) is
    # sector-demeaned AND dispersion-SCALED (model/neutralize.py) — a
    # standardized "how far above/below sector-neutral" ranking score, not a
    # percentage return. `decile` is built from it. The quantile band below
    # is left in actual predicted-return units (unscaled) so a consumer can
    # still read off a real return magnitude, not just a rank.
    live = last_week.copy().reset_index(drop=True)
    live["raw_pred"] = point_pred
    live["neutral_pred"] = neutralize_predictions(live, "raw_pred")
    live["decile"] = decile_of(live["neutral_pred"], live["week"])
    live["quantile_p10"] = q_preds[0.1]
    live["quantile_p50"] = q_preds[0.5]
    live["quantile_p90"] = q_preds[0.9]

    as_of = live["week"].max()
    as_of_str = pd.Timestamp(as_of).date().isoformat()

    forecasts = []
    for _, row in live.sort_values("neutral_pred", ascending=False).iterrows():
        forecasts.append(
            {
                "ticker": row["ticker"],
                "expected_relative_return": None if pd.isna(row["neutral_pred"]) else round(float(row["neutral_pred"]), 6),
                "quantile_p10": None if pd.isna(row["quantile_p10"]) else round(float(row["quantile_p10"]), 6),
                "quantile_p50": None if pd.isna(row["quantile_p50"]) else round(float(row["quantile_p50"]), 6),
                "quantile_p90": None if pd.isna(row["quantile_p90"]) else round(float(row["quantile_p90"]), 6),
                "decile": None if pd.isna(row["decile"]) else int(row["decile"]),
                "model_version": model_version,
                "feature_manifest_hash": manifest_hash,
                "confidence": "research-grade",
                "rank_ic_oos": None if (oos_rank_ic is None or np.isnan(oos_rank_ic)) else round(float(oos_rank_ic), 4),
                "provisional": True,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of_str,
        "universe": list(UNIVERSE),
        "disclaimer": DISCLAIMER,
        "forecasts": forecasts,
        "provenance": provenance,
        "validation": {
            "n_folds": report.n_folds,
            "ridge_mean_rank_ic": _safe_round(report.ridge_mean_rank_ic),
            "gbm_mean_rank_ic": _safe_round(report.gbm_mean_rank_ic),
            "ridge_mean_hit_rate": _safe_round(report.ridge_mean_hit_rate),
            "gbm_mean_hit_rate": _safe_round(report.gbm_mean_hit_rate),
            "ridge_mean_decile_spread": _safe_round(report.ridge_mean_decile_spread),
            "gbm_mean_decile_spread": _safe_round(report.gbm_mean_decile_spread),
            "ridge_turnover": _safe_round(report.ridge_turnover),
            "gbm_turnover": _safe_round(report.gbm_turnover),
            "ridge_deflated_sharpe": _safe_round(report.ridge_deflated_sharpe),
            "gbm_deflated_sharpe": _safe_round(report.gbm_deflated_sharpe),
            "gbm_beats_baseline": report.gbm_beats_baseline,
            "gbm_beats_baseline_reason": report.gbm_beats_baseline_reason,
            "model_version_published": model_version,
        },
    }


def _safe_round(x, n=4):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return round(float(x), n)


def write_export(payload: dict) -> list[Path]:
    engine_dir = Path(__file__).resolve().parent.parent
    root = repo_root()
    paths = [
        root / "public" / "data" / "weekly" / "latest.json",
        exports_dir() / "latest.json",
    ]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2, default=str))
    return paths


def main() -> int:
    payload = build_export()
    written = write_export(payload)
    v = payload["validation"]
    print(f"Exported {len(payload['forecasts'])} forecasts (as of {payload['as_of']}).")
    print(f"  n_folds={v['n_folds']}  ridge_rank_ic={v['ridge_mean_rank_ic']}  gbm_rank_ic={v['gbm_mean_rank_ic']}")
    print(f"  gbm_beats_baseline={v['gbm_beats_baseline']} ({v['gbm_beats_baseline_reason']})")
    print(f"  published model: {v['model_version_published']}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

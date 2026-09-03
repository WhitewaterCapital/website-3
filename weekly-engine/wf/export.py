"""Website handoff export — the one JSON the site reads.

Same pattern as intra-exitus-engine/ie/export.py: build_export() does the
work and returns a dict, write_export() writes it to both the web-servable
path and an engine-side copy, main() is the CLI entry point.

NO REAL DATA SOURCE IN THIS SANDBOX: there is no live point-in-time weekly
price/volume feed wired up here (see README.md, "What a real run needs"), so
this always runs in synthetic/demo mode, generating a plausible-but-fake
weekly panel (wf/synthetic.py) with a small embedded signal calibrated to the
spec's own "genuinely good" 0.02-0.05 OOS rank IC band. The export's
`provenance` field says so explicitly — this must never be mistaken for a
real forecast.

Run:  python3 -m wf.export        (from weekly-engine/, with weekly-engine on PYTHONPATH)
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__ as ENGINE_VERSION
from .config import EMBARGO_WEEKS, LABEL_HORIZON_WEEKS, SECTOR_MAP, UNIVERSE, exports_dir, repo_root
from .features import build_feature_panel
from .features.panel import feature_manifest_hash
from .model.gbm import fit_gbm, predict_gbm
from .model.neutralize import decile_of, neutralize_predictions
from .model.quantile import fit_quantile_models, predict_quantiles, sort_quantiles
from .model.ridge import fit_ridge, predict_ridge, rank_transform_features
from .synthetic import generate_synthetic_weekly_prices
from .validation.harness import run_walk_forward

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


def build_export() -> dict:
    weekly_prices = generate_synthetic_weekly_prices(
        UNIVERSE, n_weeks=DEMO_N_WEEKS, seed=DEMO_SEED, signal_strength=DEMO_SIGNAL_STRENGTH
    )
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
        "provenance": _synthetic_provenance(),
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

"""Website handoff export for WW-KALMAN — the one JSON the site reads.

Writes a contract-compliant JSON to:

  * <repo>/public/data/kalman/latest.json   (web-servable)
  * <kalman-engine>/exports/latest.json      (engine-side copy)

Run:  python -m kf.export

## Live-data gate

Gated exactly like chaos-engine/cascade-data-engine: build_export() looks
for BOTH ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY.

  * BOTH KEYS SET   -> real daily closes for kf.config.UNIVERSE from
    Alpaca's IEX feed (kf/adapters/alpaca_bars.py). A live fetch that fails
    outright (bad credentials, network refused) RAISES rather than falling
    back to synthetic data under a live label. A ticker that comes back
    with too little history is individually excluded from every pair that
    needs it (recorded in `warnings`), rather than failing the whole
    export for one thin name -- provenance is "live" as long as the fetch
    itself succeeded.
  * EITHER KEY UNSET -> kf.synthetic's deterministic synthetic-demo panel,
    provenance "synthetic-demo". This is the default in every sandbox this
    repo has been built in.

Either way, EVERY pair in kf.config.CANDIDATE_PAIRS is run through the
SAME real pipeline: kf.cointegration.engle_granger_test, then (only if
cointegrated) kf.filter.run_adaptive_kalman_filter. A pair that tests as
NOT cointegrated is reported with is_cointegrated=false and a stated
reason -- never silently dropped, and never forced into a spread signal.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from . import __version__ as ENGINE_VERSION
from .adapters.alpaca_bars import LiveFetchFailedError, fetch_universe_daily_closes
from .cointegration import engle_granger_test
from .config import (
    ADF_MAX_LAG_CEILING,
    ALPACA_API_KEY_ID_VAR,
    ALPACA_API_SECRET_KEY_VAR,
    CANDIDATE_PAIRS,
    COINTEGRATION_SIGNIFICANCE,
    LOOKBACK_CALENDAR_DAYS,
    MIN_OBSERVATIONS,
    UNIVERSE,
    Z_ENTRY_THRESHOLD,
    Z_EXIT_THRESHOLD,
    Z_TO_SCORE_SCALE,
    AdaptiveFilterConfig,
    env,
    exports_dir,
    repo_root,
)
from .filter import run_adaptive_kalman_filter
from .synthetic import synthetic_log_price_panel

SCHEMA_VERSION = "1.0.0"

MIN_LIVE_OBSERVATIONS_PER_TICKER = MIN_OBSERVATIONS

DISCLAIMER = (
    "WW-KALMAN is a research model, not investment advice or an order. It "
    "tests each candidate pair in a fixed 6-name universe for real "
    "cointegration (Engle-Granger two-step: OLS hedge ratio + an "
    "augmented Dickey-Fuller stationarity test on the residual, implemented "
    "from scratch -- statsmodels is not available in this environment). A "
    "pair that is NOT found cointegrated over the available history is "
    "honestly excluded, never forced into a signal. For a cointegrated "
    "pair, a Kalman filter tracks the time-varying intercept and hedge "
    "ratio between the two names' LOG prices, and -- the specific thing "
    "this build was asked to do -- the filter's own process- and "
    "observation-noise covariances (Q, R) are re-estimated ONLINE from its "
    "own innovation sequence as each new observation arrives (an "
    "innovation-based / covariance-matching adaptive method following "
    "Mehra 1970 and Akhlaghi, Zhou & Huang 2017, arXiv:1702.00884 -- see "
    "kf/filter.py for the exact update equations and citations), not fixed "
    "by a hand-picked hyperparameter. This is real, standard quantitative "
    "finance theory (Engle & Granger 1987; Vidyamurthy 2004), built in the "
    "SPIRIT of Susquehanna's publicly described philosophy (probabilistic, "
    "Bayesian-updating, continuously self-revising decision-making) -- it "
    "is NOT a claim to replicate any real SIG system; nothing about SIG's "
    "actual proprietary models is public. See README.md for the full "
    "grounding and citations, including what this engine deliberately does "
    "NOT implement (EM-based noise-covariance learning -- a real, "
    "different, complementary method from the same literature)."
)


def _live_data_configured() -> bool:
    return bool(env(ALPACA_API_KEY_ID_VAR)) and bool(env(ALPACA_API_SECRET_KEY_VAR))


def _live_log_price_panel(universe: list[str]) -> tuple[pd.DataFrame, list[str]]:
    """Real daily closes -> aligned log-price panel. Raises
    LiveFetchFailedError if the HTTP call itself fails. A ticker with fewer
    than MIN_LIVE_OBSERVATIONS_PER_TICKER real closes is DROPPED from the
    panel (not from the whole export) -- every pair involving it is then
    individually reported as unavailable by kf.config's own MIN_OBSERVATIONS
    gate in build_export's main loop, with the reason stated. Returns
    (panel, warnings)."""
    raw = fetch_universe_daily_closes(universe, lookback_days=LOOKBACK_CALENDAR_DAYS)
    warnings: list[str] = []
    usable: dict[str, pd.Series] = {}
    for ticker in universe:
        by_date = raw.get(ticker) or {}
        if len(by_date) < MIN_LIVE_OBSERVATIONS_PER_TICKER:
            warnings.append(
                f"{ticker}: only {len(by_date)} live daily closes returned "
                f"(need >= {MIN_LIVE_OBSERVATIONS_PER_TICKER}) -- every pair "
                f"involving {ticker} is excluded this run, not forced through "
                f"on thin data."
            )
            continue
        s = pd.Series(by_date, dtype=float).sort_index()
        s.index = pd.to_datetime(s.index)
        usable[ticker] = np.log(s)
    if not usable:
        raise LiveFetchFailedError(
            "Alpaca returned usable history for zero universe tickers -- refusing "
            "to publish a 'live' export with nothing real in it."
        )
    panel = pd.DataFrame(usable)
    return panel, warnings


def _pair_reading(
    t1: str, t2: str, panel: pd.DataFrame, filter_cfg: AdaptiveFilterConfig
) -> dict:
    """Full per-pair pipeline: align -> cointegration test -> (if
    cointegrated) adaptive Kalman filter -> signal. Returns one dict for the
    export's `pairs` array. Always returns a dict -- abstention is
    represented by `available`/`cointegrated` fields and a stated `note`,
    never by omitting the pair."""
    pair_label = f"{t1}/{t2}"
    if t1 not in panel.columns or t2 not in panel.columns:
        return {
            "pair": pair_label, "ticker1": t1, "ticker2": t2,
            "available": False, "cointegrated": False,
            "n_obs": 0, "note": f"{t1 if t1 not in panel.columns else t2} excluded this run (see warnings).",
        }

    aligned = panel[[t1, t2]].dropna()
    n = len(aligned)
    if n < MIN_OBSERVATIONS:
        return {
            "pair": pair_label, "ticker1": t1, "ticker2": t2,
            "available": False, "cointegrated": False, "n_obs": n,
            "note": (
                f"Only {n} overlapping trading days for {t1}/{t2} "
                f"(need >= {MIN_OBSERVATIONS}) -- too few to fit a reliable "
                f"OLS hedge ratio or run the ADF cointegration pretest; "
                f"abstaining rather than testing on a statistically thin window."
            ),
        }

    y1 = aligned[t1].to_numpy()
    y2 = aligned[t2].to_numpy()
    eg = engle_granger_test(
        t1, t2, y1, y2,
        significance=COINTEGRATION_SIGNIFICANCE, max_lag=ADF_MAX_LAG_CEILING,
    )

    base = {
        "pair": pair_label, "ticker1": t1, "ticker2": t2,
        "available": True, "cointegrated": bool(eg.is_cointegrated),
        "n_obs": int(eg.n_obs),
        "cointegration": {
            "adf_t_stat": round(eg.adf_t_stat, 4) if np.isfinite(eg.adf_t_stat) else None,
            "adf_lag_used": eg.adf_lag_used,
            "critical_value_5pct": eg.critical_values.get(5),
            "critical_values": {str(k): v for k, v in eg.critical_values.items()},
            "significance": eg.significance,
            "ols_hedge_ratio": round(eg.hedge_ratio, 6),
            "ols_intercept": round(eg.intercept, 6),
            "ols_r_squared": round(eg.r_squared, 4) if np.isfinite(eg.r_squared) else None,
        },
    }

    if not eg.is_cointegrated:
        base["note"] = eg.reason
        base["score"] = None
        base["signal"] = "abstain-not-cointegrated"
        return base

    result = run_adaptive_kalman_filter(
        y1, y2, filter_cfg,
        initial_intercept=eg.intercept, initial_hedge_ratio=eg.hedge_ratio,
    )
    final_mu, final_gamma = result.final_state()
    final_z = float(result.z_score[-1])
    final_q_trace = float(result.q_trace[-1])
    final_r = float(result.r_trace[-1])

    if abs(final_z) >= Z_ENTRY_THRESHOLD:
        signal = f"long {t1} / short {t2}" if final_z < 0 else f"short {t1} / long {t2}"
    elif abs(final_z) <= Z_EXIT_THRESHOLD:
        signal = "flat / near fair value"
    else:
        signal = "watch (weak signal)"

    score = float(np.clip(-final_z * Z_TO_SCORE_SCALE, -100.0, 100.0))

    q_drift_pct = (
        100.0 * (final_q_trace - result.initial_q_trace) / result.initial_q_trace
        if result.initial_q_trace > 0 else None
    )
    r_drift_pct = (
        100.0 * (final_r - result.initial_r) / result.initial_r
        if result.initial_r > 0 else None
    )

    base.update({
        "kalman": {
            "mu": round(final_mu, 6),
            "gamma": round(final_gamma, 6),
            "z_score": round(final_z, 4),
            "innovation_var": round(float(result.innovation_var[-1]), 8),
            "adaptive_noise": {
                "initial_q_trace": result.initial_q_trace,
                "final_q_trace": final_q_trace,
                "q_drift_pct": round(q_drift_pct, 1) if q_drift_pct is not None else None,
                "initial_r": result.initial_r,
                "final_r": final_r,
                "r_drift_pct": round(r_drift_pct, 1) if r_drift_pct is not None else None,
            },
        },
        "score": round(score, 1),
        "signal": signal,
        "note": (
            f"Cointegrated (ADF t={eg.adf_t_stat:.3f} vs. 5% crit "
            f"{eg.critical_values.get(5):.3f}, n={eg.n_obs}). Adaptive Kalman filter: "
            f"hedge ratio (gamma) {final_gamma:+.4f}, standardized spread z={final_z:+.2f} "
            f"-> {signal}. Filter's own noise estimate moved online from its initial "
            f"guess: Q trace {result.initial_q_trace:.2e} -> {final_q_trace:.2e}, "
            f"R {result.initial_r:.2e} -> {final_r:.2e} -- re-estimated from this run's "
            f"own innovations (Mehra/Akhlaghi covariance matching), not a frozen "
            f"hand-set hyperparameter. Research read, not a standalone trade order."
        ),
    })
    return base


def build_export(today: str | None = None) -> dict:
    universe = list(UNIVERSE)
    warnings: list[str] = []
    if _live_data_configured():
        panel, live_warnings = _live_log_price_panel(universe)
        provenance = "live"
        warnings.extend(live_warnings)
    else:
        panel = synthetic_log_price_panel()
        provenance = "synthetic-demo"

    filter_cfg = AdaptiveFilterConfig()
    pairs = [_pair_reading(t1, t2, panel, filter_cfg) for (t1, t2) in CANDIDATE_PAIRS]

    n_cointegrated = sum(1 for p in pairs if p.get("cointegrated"))
    n_available = sum(1 for p in pairs if p.get("available"))

    as_of = today if today is not None else panel.index.max().date().isoformat()

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "universe": universe,
        "provenance": provenance,
        "disclaimer": DISCLAIMER,
        "pairs_tested": len(pairs),
        "pairs_available": n_available,
        "pairs_cointegrated": n_cointegrated,
        "warnings": warnings,
        "pairs": pairs,
    }


def default_export_paths() -> list[Path]:
    return [
        repo_root() / "public" / "data" / "kalman" / "latest.json",
        exports_dir() / "latest.json",
    ]


def write_export(payload: dict, paths: list[Path] | None = None) -> list[Path]:
    paths = paths if paths is not None else default_export_paths()
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    return paths


def main() -> int:
    payload = build_export()
    written = write_export(payload)
    print(
        f"Exported {payload['pairs_tested']} pairs ({payload['pairs_cointegrated']} "
        f"cointegrated) as of {payload['as_of']}, provenance={payload['provenance']}."
    )
    if payload["warnings"]:
        print(f"  warnings: {payload['warnings']}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

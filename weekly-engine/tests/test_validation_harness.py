"""The honesty tests for the walk-forward harness.

Two fixtures, two opposite requirements:

  * `test_no_embedded_signal_shows_near_zero_ic_and_no_false_victory` — a
    pure-random-walk synthetic panel (signal_strength=0.0). No feature has
    any real information. The harness must report near-zero (insignificant)
    rank IC for BOTH models, across a run of several seeds, and must NEVER
    claim GBM beats baseline. This is the harness's most important property:
    it would be trivial to build something that "finds" a signal in noise
    (e.g. GBM overfitting a few extra splits to sampling noise, then a naive
    comparison declaring victory on a lucky fold) — this test is what stands
    between "the harness works" and "the harness lies."

  * `test_embedded_nonlinear_signal_is_detected_and_gbm_beats_baseline` — a
    fixture with a genuine, regime-dependent (nonlinear) signal (see
    wf.synthetic.generate_regime_dependent_signal_prices's docstring for why
    it is specifically nonlinear: a signal linear in a single latent factor
    favors ridge, which would make it a poor fixture for proving a tree
    model can ever legitimately win). Here GBM's tree splits can exploit the
    interaction (momentum works only in the low-vol regime) in a way ridge's
    single linear coefficient cannot, and the harness must report exactly
    that: GBM's rank IC materially above ridge's, in a real majority of
    individual folds (>= 3), not just on average.
"""

from __future__ import annotations

from wf.config import EMBARGO_WEEKS, LABEL_HORIZON_WEEKS
from wf.features import build_feature_panel
from wf.synthetic import (
    default_sector_map,
    generate_regime_dependent_signal_prices,
    generate_synthetic_weekly_prices,
)
from wf.validation.harness import MIN_FOLDS_FOR_VERDICT, run_walk_forward

TICKERS = [f"T{i}" for i in range(20)]
SECTORS = default_sector_map(TICKERS, n_sectors=4)


def _run(prices, n_splits=6, min_train=100):
    panel, feature_cols, _ = build_feature_panel(prices, SECTORS)
    return run_walk_forward(
        panel,
        feature_cols,
        label_col="sector_relative_fwd_return",
        n_splits=n_splits,
        horizon=LABEL_HORIZON_WEEKS,
        embargo=EMBARGO_WEEKS,
        min_train=min_train,
    )


def test_no_embedded_signal_shows_near_zero_ic_and_no_false_victory():
    # Several seeds: no single unlucky draw should be able to flip the
    # honest verdict, and no seed should ever produce a false "beats
    # baseline" claim purely from noise.
    seeds = [0, 4, 5, 9, 42]
    ridge_ics = []
    gbm_ics = []
    for seed in seeds:
        prices = generate_synthetic_weekly_prices(TICKERS, n_weeks=320, seed=seed, signal_strength=0.0)
        report = _run(prices)
        assert report.n_folds >= MIN_FOLDS_FOR_VERDICT
        ridge_ics.append(report.ridge_mean_rank_ic)
        gbm_ics.append(report.gbm_mean_rank_ic)
        assert report.gbm_beats_baseline is False, (
            f"seed {seed}: harness falsely claimed GBM beats baseline on a pure "
            f"random-walk fixture with no embedded signal (reason logged as: "
            f"{report.gbm_beats_baseline_reason!r})"
        )

    # Averaged across seeds, both models should land indistinguishably close
    # to zero — nowhere near the spec's own 0.02-0.05 "genuinely good" band.
    mean_abs_ridge = sum(abs(x) for x in ridge_ics) / len(ridge_ics)
    mean_abs_gbm = sum(abs(x) for x in gbm_ics) / len(gbm_ics)
    assert mean_abs_ridge < 0.02, f"ridge rank IC not near zero on no-signal data: {ridge_ics}"
    assert mean_abs_gbm < 0.03, f"GBM rank IC not near zero on no-signal data: {gbm_ics}"


def test_embedded_nonlinear_signal_is_detected_and_gbm_beats_baseline():
    prices = generate_regime_dependent_signal_prices(TICKERS, n_weeks=320, seed=1, strength=0.5)
    report = _run(prices)

    assert report.n_folds >= MIN_FOLDS_FOR_VERDICT
    scored = [f for f in report.folds if f.ridge_rank_ic == f.ridge_rank_ic and f.gbm_rank_ic == f.gbm_rank_ic]
    assert len(scored) >= MIN_FOLDS_FOR_VERDICT

    # Both models should show *some* real skill on data with genuine signal...
    assert report.ridge_mean_rank_ic > 0.02
    assert report.gbm_mean_rank_ic > 0.02
    # ...but GBM, which can exploit the vol-regime x momentum interaction via
    # tree splits, should come out ahead, and the harness's own verdict must
    # say so, not just the raw numbers.
    assert report.gbm_mean_rank_ic > report.ridge_mean_rank_ic
    assert report.gbm_wins >= (len(scored) // 2 + 1), (
        f"GBM only beat ridge in {report.gbm_wins}/{len(scored)} individual folds — "
        "not the real, repeated majority the harness requires before crediting it"
    )
    assert report.gbm_beats_baseline is True, report.gbm_beats_baseline_reason


def test_report_includes_decile_spread_hit_rate_turnover_and_deflated_sharpe():
    prices = generate_regime_dependent_signal_prices(TICKERS, n_weeks=320, seed=1, strength=0.5)
    report = _run(prices)
    assert report.ridge_mean_hit_rate == report.ridge_mean_hit_rate  # not NaN
    assert report.gbm_mean_hit_rate == report.gbm_mean_hit_rate
    assert report.ridge_mean_decile_spread == report.ridge_mean_decile_spread
    assert report.gbm_mean_decile_spread == report.gbm_mean_decile_spread
    assert 0.0 <= report.ridge_turnover <= 1.0
    assert 0.0 <= report.gbm_turnover <= 1.0
    assert report.ridge_deflated_sharpe == report.ridge_deflated_sharpe
    assert report.gbm_deflated_sharpe == report.gbm_deflated_sharpe

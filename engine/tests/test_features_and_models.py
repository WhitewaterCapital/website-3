"""Known-answer tests for the math: returns, volatility, factor regression,
valuation, quality, scoring."""

import numpy as np
import pandas as pd

from incepta.features import returns as R
from incepta.models.volatility import ewma_vol
from incepta.models.factor import factor_exposures, blume_adjust_beta
from incepta.models.valuation import compute_valuation
from incepta.models.quality import piotroski_f_score, altman_z
from incepta.models.scoring import composite_score, robust_z


def test_returns_known_answers():
    closes = np.array([100.0, 110.0, 99.0])
    r = R.daily_returns(closes)
    assert np.allclose(r, [0.10, -0.10])
    assert abs(R.cumulative_return(closes, 2) - (-0.01)) < 1e-9  # 99/100 - 1
    assert R.high_52w_ratio(closes) == 99.0 / 110.0
    assert R.max_drawdown(closes) < 0


def test_momentum_skips_recent_month():
    # rising then flat; 12-1 momentum should be positive and finite
    closes = np.linspace(50, 100, 300)
    m = R.momentum_12_1(closes)
    assert np.isfinite(m) and m > 0


def test_ewma_vol_recovers_scale():
    rng = np.random.default_rng(0)
    daily = 0.02
    r = rng.normal(0, daily, 2000)
    v = ewma_vol(r, annualize=False)
    assert abs(v - daily) < 0.004  # within ~20% of the true daily vol


def test_factor_regression_recovers_betas():
    rng = np.random.default_rng(1)
    n = 800
    dates = pd.bdate_range("2020-01-01", periods=n)
    F = pd.DataFrame(
        {
            "mkt_rf": rng.normal(0, 0.01, n),
            "smb": rng.normal(0, 0.008, n),
            "hml": rng.normal(0, 0.008, n),
            "rmw": rng.normal(0, 0.006, n),
            "cma": rng.normal(0, 0.006, n),
            "mom": rng.normal(0, 0.009, n),
            "rf": np.full(n, 0.0001),
        },
        index=dates,
    )
    true_beta = {"mkt_rf": 1.2, "smb": -0.3, "hml": 0.5, "rmw": 0.0, "cma": 0.0, "mom": 0.4}
    excess = sum(F[k] * b for k, b in true_beta.items()) + rng.normal(0, 0.001, n)
    stock_ret = excess + F["rf"]
    fit = factor_exposures(pd.Series(stock_ret.values, index=dates), F, window=n)
    assert abs(fit.betas["mkt_rf"] - 1.2) < 0.05
    assert abs(fit.betas["hml"] - 0.5) < 0.05
    assert abs(fit.betas["mom"] - 0.4) < 0.05
    assert fit.r2 > 0.95


def test_valuation_flags_negative_earnings():
    v = compute_valuation(
        price=10.0, shares_outstanding=1_000, net_income=-50,
        stockholders_equity=2_000, revenue=5_000,
    )
    assert v.market_cap == 10_000
    assert v.pe is None and any("earnings" in f for f in v.flags)
    assert abs(v.pb - 5.0) < 1e-9  # 10000/2000
    assert abs(v.ps - 2.0) < 1e-9


def test_piotroski_and_altman():
    prev = {"assets": 100, "net_income": 5, "long_term_debt": 40, "current_assets": 30,
            "current_liabilities": 20, "shares_outstanding": 100, "gross_profit": 30,
            "revenue": 80, "operating_cash_flow": 6}
    curr = {"assets": 110, "net_income": 12, "long_term_debt": 30, "current_assets": 40,
            "current_liabilities": 20, "shares_outstanding": 100, "gross_profit": 45,
            "revenue": 100, "operating_cash_flow": 15}
    p = piotroski_f_score(curr, prev)
    assert p.max_possible == 9          # all inputs present
    assert p.score >= 7                 # a clearly-improving firm scores high

    z = altman_z({"assets": 110, "current_assets": 40, "current_liabilities": 20,
                  "retained_earnings": 50, "operating_income": 20, "liabilities": 50,
                  "revenue": 100}, market_cap=300)
    assert z.z is not None and z.zone in {"safe", "grey", "distress"}


def test_composite_score_direction_and_ranking():
    # 'good' has high quality (high weight +) and low valuation (negative weight)
    df = pd.DataFrame({
        "quality": [3.0, 0.0, -3.0],
        "cheapness": [1.0, 5.0, 9.0],   # lower is better → negative weight
    }, index=["good", "mid", "bad"])
    out = composite_score(df, {"quality": 1.0, "cheapness": -1.0})
    assert out.index[0] == "good" and out.index[-1] == "bad"
    assert out.loc["good", "rank"] > out.loc["bad", "rank"]


def test_robust_z_centered():
    z = robust_z(pd.Series([1, 2, 3, 4, 5]))
    assert abs(z.median()) < 1e-9


def test_downside_vol_is_target_semideviation():
    # returns = [+0.10, -0.10]; downside = [0, -0.10]; mean(sq)=0.005 over N=2
    closes = np.array([100.0, 110.0, 99.0])
    v = R.downside_vol(closes, lookback=63, annualize=False)
    assert abs(v - np.sqrt(0.005)) < 1e-12   # NOT sqrt(0.01) (negatives-only)


def test_blume_shrinks_beta_toward_one():
    assert abs(blume_adjust_beta(1.6) - 1.4) < 1e-12   # 2/3*1.6 + 1/3
    assert abs(blume_adjust_beta(1.0) - 1.0) < 1e-12
    assert abs(blume_adjust_beta(0.4) - 0.6) < 1e-12

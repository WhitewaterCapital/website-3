"""Honest out-of-sample evaluation of the regime classifier on the live universe.

Fetches daily prices for the covered universe, builds the pooled dataset, and runs
purged + embargoed walk-forward CV — reporting Cohen's kappa (overall and per
fold), balanced accuracy, and the pooled out-of-sample confusion matrix.

Run:  python -m scripts.eval_regime         (needs TIINGO_API_KEY)
"""

from __future__ import annotations

from datetime import date

import pandas as pd

from ie.adapters.prices_tiingo import TiingoClient
from ie.config import UNIVERSE
from ie.pit import bars_to_frame
from ie.regime.classifier import RegimeModel, build_dataset, walk_forward_report
from ie.regime.labels import LabelConfig, REGIMES
from ie.validation.splits import PurgedWalkForwardCV

pd.set_option("display.width", 120)


def main() -> None:
    client = TiingoClient()
    prices = {}
    for tk in UNIVERSE:
        prices[tk] = bars_to_frame(client.fetch_prices(tk, start=date(2010, 1, 1)))
    print(f"universe: {', '.join(f'{k}({len(v)})' for k, v in prices.items())}")

    label_cfg = LabelConfig()
    X, y, times, groups, cols = build_dataset(prices, label_cfg=label_cfg)
    print(f"pooled samples: {len(X):,}  |  features: {len(cols)}")
    print("class balance:", y.value_counts(normalize=True).round(3).to_dict())

    # Fix #4: the CV purge distance MUST equal the label horizon, or a training
    # label's forward window can reach the test block. Derive it, don't hardcode.
    cv = PurgedWalkForwardCV(n_splits=6, horizon=label_cfg.horizon, embargo=5, min_train=504)
    print("\nfolds (purged+embargoed walk-forward):")
    for f in cv.fold_date_ranges(times):
        print(f"  train {f['train_start']}→{f['train_end']} ({f['n_train']:>5}) "
              f"| test {f['test_start']}→{f['test_end']} ({f['n_test']:>5})")

    rep = walk_forward_report(X, y, times, cv, RegimeModel())

    print(f"\nOUT-OF-SAMPLE  kappa = {rep['kappa']:.3f}   "
          f"balanced_acc = {rep['balanced_accuracy']:.3f}   n = {rep['n_oos']:,}")
    print("per-fold kappa:", [round(k, 3) for k in rep["fold_kappa"]])
    print("per-class recall:", {k: round(v, 3) for k, v in rep["recall"].items()})
    print("\nconfusion (rows = truth, cols = prediction):")
    print(rep["confusion"].to_string())

    print(f"\ncalibration: multiclass Brier = {rep['brier']:.4f}  (lower is better)")
    print("reliability (high-vol gate) — mean_pred should track obs_rate:")
    for row in rep["reliability_high_vol"]:
        print(f"  p{row['bin']}: pred {row['mean_pred']:.2f}  obs {row['obs_rate']:.2f}  (n={row['n']})")

    # The abstain gate: collapse to high-vol vs tradeable and re-score OOS. This
    # is the binary decision the level engine actually depends on.
    import numpy as np
    from sklearn.metrics import balanced_accuracy_score, cohen_kappa_score

    yb = pd.Series(y).reset_index(drop=True)
    Xr = X.reset_index(drop=True)
    ot, op = [], []
    for tr, te in cv.split(times):
        yy = yb.map(lambda v: "high-vol" if v == "high-vol" else "tradeable")
        m = RegimeModel().fit(Xr.iloc[tr], yy.iloc[tr])
        op.extend(m.predict(Xr.iloc[te]).tolist())
        ot.extend(yy.iloc[te].tolist())
    print(f"\nABSTAIN GATE (high-vol vs tradeable):  kappa = {cohen_kappa_score(ot, op):.3f}   "
          f"balanced_acc = {balanced_accuracy_score(ot, op):.3f}")

    print("\nreference: a majority-class guesser scores kappa = 0.000 by construction.")


if __name__ == "__main__":
    main()

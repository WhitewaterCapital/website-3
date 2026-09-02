"""End-to-end demo: a real Intra / Exitus plan for each name in the universe.

Trains the regime classifier on the pooled history, then produces an as-of-latest
plan per ticker through the full pipeline. (Training here uses all history for a
readable demo; the honest out-of-sample skill was measured in eval_regime.py.)

Run:  python -m scripts.plan_demo        (needs TIINGO_API_KEY)
"""

from __future__ import annotations

from datetime import date

from ie.adapters.prices_tiingo import TiingoClient
from ie.config import UNIVERSE
from ie.pit import bars_to_frame
from ie.pipeline import PipelineConfig, plan_for_ticker
from ie.regime.classifier import RegimeModel, build_dataset


def main() -> None:
    client = TiingoClient()
    prices = {t: bars_to_frame(client.fetch_prices(t, start=date(2012, 1, 1)))
              for t in UNIVERSE}

    X, y, times, groups, cols = build_dataset(prices)
    model = RegimeModel().fit(X, y)
    cfg = PipelineConfig()

    for t in UNIVERSE:
        plan = plan_for_ticker(t, prices[t], model, cols, cfg)
        d = plan.as_dict()
        px = float(prices[t]["close"].iloc[-1])
        print(f"\n=== {t}  (last close {px:.2f}) ===")
        print(f"  regime={d['regime']:<11} bias={d['bias']:<5} "
              f"confidence={d['confidence']}")
        if d["entryZone"]:
            print(f"  entry {d['entryZone']}  stop {d['stop']}  "
                  f"targets {d['targets']}")
            print(f"  expectedR={d['expectedR']}  sizing={d['sizingPct']}%  "
                  f"time-stop: {d['timeStop']}")
        print(f"  rationale: {d['rationale']}")


if __name__ == "__main__":
    main()

"""Website handoff export — the one JSON the site reads.

Trains the regime classifier on pooled history, produces an as-of-latest plan per
covered ticker through the full pipeline, and writes a contract-compliant JSON to:

  * <repo>/public/data/intra-exitus/latest.json   (web-servable)
  * <engine>/exports/latest.json                   (engine-side copy)

Run:  python -m ie.export         (needs TIINGO_API_KEY in .env)

Honesty: the last (in-progress) trading day is dropped so levels anchor on the
last SETTLED close, never an unsettled intraday bar. A ticker with no clean setup
comes back as an abstain plan (confidence "insufficient") — never a fabricated level.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from ie import __version__ as ENGINE_VERSION  # type: ignore
from ie.adapters.prices_tiingo import TiingoClient
from ie.config import HISTORY_START, UNIVERSE
from ie.pipeline import PipelineConfig, plan_for_ticker
from ie.pit import bars_to_frame
from ie.regime.classifier import RegimeModel, build_dataset

SCHEMA_VERSION = "1.0.0"
DISCLAIMER = (
    "Intra / Exitus is a point-in-time entry/exit research model (regime-conditional "
    "OU / trend templates with cost-aware sizing). Levels are decision-support, not "
    "advice or an order. It abstains when there is no clean, tradeable setup."
)


def _drop_unsettled(df):
    """Drop today's in-progress bar so we anchor on the last settled close."""
    if len(df) and df.index[-1].date() >= date.today():
        return df.iloc[:-1]
    return df


def build_export() -> dict:
    client = TiingoClient()
    start = date.fromisoformat(HISTORY_START)
    prices = {
        t: _drop_unsettled(bars_to_frame(client.fetch_prices(t, start=start)))
        for t in UNIVERSE
    }

    X, y, times, groups, cols = build_dataset(prices)
    model = RegimeModel().fit(X, y)
    cfg = PipelineConfig()

    plans = []
    as_of = None
    for t in UNIVERSE:
        df = prices[t]
        plan = plan_for_ticker(t, df, model, cols, cfg)
        last_date = df.index[-1].date().isoformat()
        as_of = max(as_of, last_date) if as_of else last_date
        plans.append({
            **plan.as_dict(),
            "ticker": t,
            "lastClose": round(float(df["close"].iloc[-1]), 4),
            "asOf": last_date,
        })

    return {
        "schema_version": SCHEMA_VERSION,
        "engine_version": ENGINE_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "universe": list(UNIVERSE),
        "disclaimer": DISCLAIMER,
        "plans": plans,
    }


def write_export(payload: dict) -> list[Path]:
    engine_dir = Path(__file__).resolve().parent.parent
    repo_root = engine_dir.parent
    paths = [
        repo_root / "public" / "data" / "intra-exitus" / "latest.json",
        engine_dir / "exports" / "latest.json",
    ]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, indent=2))
    return paths


def main() -> int:
    payload = build_export()
    written = write_export(payload)
    conf: dict[str, int] = {}
    for pl in payload["plans"]:
        conf[pl["confidence"]] = conf.get(pl["confidence"], 0) + 1
    print(f"Exported {len(payload['plans'])} plans (as of {payload['as_of']}).")
    print(f"  confidence: {conf}")
    for w in written:
        print(f"  written to: {w}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

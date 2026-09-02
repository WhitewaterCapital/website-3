# Intra / Exitus — engine

A **sealed, point-in-time entry/exit planner**. Given a covered ticker on a given
date, it decides where to enter, where you're wrong (stop), where to scale out
(targets), how big (sizing), and when to quit on time — or it **abstains** when
there is no clean plan.

This engine is its own world. It shares **no code and no state** with the Incepta
equity engine (`../engine/`) or any other model. The only way it ever touches the
website is the same way Incepta does: it writes one JSON document to
`public/data/intra-exitus/latest.json`, and a single TypeScript bridge reads it.
Nothing else in the app knows this engine exists.

## Design (v1)

Single-name only. Pairs / Kalman / RL / execution-microstructure are **out of v1**.

Four sealed layers:

1. **Features** (`ie/features/`) — PIT price features: returns, multi-horizon
   momentum, ATR, Garman-Klass volatility, realized/EWMA vol, distance from
   SMA/EMA, RSI, Bollinger width & z-score, swing structure, 52-week position.
   Every feature at row *t* uses only bars dated `<= t`. Verified by an
   anti-look-ahead test.
2. **Regime** (`ie/regime/`) — a gradient-boosted classifier labels each day
   `trend-up | trend-down | mean-revert | high-vol`. Built under Applied
   Predictive Modeling discipline (purged + embargoed CV, kappa, class-imbalance
   remedies). The regime decides which level template fires.
3. **Levels** (`ie/levels/`) — regime-conditional. Mean-revert → an
   **Ornstein-Uhlenbeck** fit (entry band = mean ± kσ, half-life → time-stop,
   expected reversion → expectedR). Trend → pullback-to-structure with an
   ATR-buffered stop and R-multiple targets. High-vol → **abstain**.
4. **Sizing** (`ie/sizing/`) — volatility targeting, fractional-Kelly cap, minus a
   transaction-cost haircut.

Validated by a **walk-forward backtest with realistic costs** before anything is
trusted.

## Data

Daily, split- and dividend-adjusted OHLCV from **Tiingo** (free tier, keyed).
Stooq is dead (bot-gated as of 2026-08). Point-in-time, no look-ahead, free-data
integrity caveats apply — see the adapter docstring.

> **Not investment advice.** Research/paper output only, built on free data with
> known survivorship and point-in-time limitations. Not a validated alpha model.

## Layout

```
intra-exitus-engine/
  ie/
    config.py          # constants, env, universe, data dirs
    pit.py             # PriceBar + bars→DataFrame
    adapters/          # price providers behind a Protocol (Tiingo)
    features/          # PIT feature layer            ← built
    regime/            # regime classifier            (later)
    levels/            # OU + templates               (later)
    sizing/            # vol-target sizing            (later)
    backtest/          # walk-forward validation      (later)
    pipeline.py        # orchestration               (later)
    export.py          # write the handoff JSON      (later)
    cli.py             # command line               (later)
  contracts/           # TypeScript mirror of the export schema (later)
  data/                # local caches (gitignored)
  exports/             # engine copy of the export (gitignored)
  tests/               # pytest — feature layer is covered
```

## Quickstart

```bash
cd intra-exitus-engine
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your Tiingo key
pytest -q                   # feature layer tests (no network needed)
```

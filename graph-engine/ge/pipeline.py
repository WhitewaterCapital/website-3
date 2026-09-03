"""Orchestration: prices -> signal -> graph -> diffusion -> residual, across
time.

Two entry points:

  * `run_as_of`  — one cross-section (one date): build the graph from the
    trailing correlation window ending at that date, diffuse that date's
    signal across it, return the residual frame. This is what a live/daily
    run would call.

  * `run_history` — repeat `run_as_of` across a date range to build a tidy
    per-(date, ticker) panel of residuals. The graph is expensive to
    re-estimate (Ledoit-Wolf on a rolling window) and changes slowly compared
    to the daily signal, so it is refreshed every `refresh_every` bars rather
    than rebuilt from scratch every single day — the same "estimate
    infrequently, apply daily" idiom used elsewhere in this codebase for
    slow-moving structure (e.g. sector/factor loadings). This panel is what
    `reversion.py` (per-name half-life) and `backtest.py` (as a standalone
    signal) are validated against.

Nothing here looks into the future: at date t, `run_as_of` only uses prices
dated <= t (the correlation window and the signal window both end at t).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import DiffusionConfig, GraphConfig, SIGNAL_WINDOW
from .features.signal import corr_window_returns, cross_sectional_zscore, rolling_return
from .graph.construct import GraphSources, build_graph
from .residual import ResidualFrame, compute_residuals


@dataclass(frozen=True)
class PipelineConfig:
    graph: GraphConfig = GraphConfig()
    diffusion: DiffusionConfig = DiffusionConfig()
    signal_window: int = SIGNAL_WINDOW
    refresh_every: int = 5  # bars between graph re-estimation in run_history


def run_as_of(
    prices: pd.DataFrame,
    sector_of: dict[str, str],
    cfg: PipelineConfig = PipelineConfig(),
) -> tuple[ResidualFrame, GraphSources]:
    """`prices` — close prices, rows = trailing history up to and including
    the as-of date (index[-1]), columns = tickers. Needs at least
    `cfg.graph.corr_window + 1` rows for the correlation window and
    `cfg.signal_window + 1` rows for the signal."""
    if len(prices) < cfg.signal_window + 1:
        raise ValueError("not enough history for the signal window")

    corr_rets = corr_window_returns(prices, cfg.graph.corr_window).dropna(how="any")
    if len(corr_rets) < 5:
        raise ValueError("not enough return history to estimate the graph")

    graph = build_graph(corr_rets, sector_of, cfg.graph)

    raw_signal = rolling_return(prices, cfg.signal_window).iloc[-1]
    signal = cross_sectional_zscore(raw_signal).reindex(graph.tickers)
    if signal.isna().any():
        raise ValueError("signal has NaNs for names present in the graph")

    residuals = compute_residuals(signal, graph.sparse_weights, sector_of, cfg.diffusion)
    return residuals, graph


def run_history(
    prices: pd.DataFrame,
    sector_of: dict[str, str],
    cfg: PipelineConfig = PipelineConfig(),
) -> pd.DataFrame:
    """Tidy long panel: one row per (date, ticker) with the residual fields,
    for every date that has enough trailing history. Returns columns
    [date, ticker, signal, diffused, residual, residual_z,
    residual_z_sector_neutral]."""
    min_start = max(cfg.graph.corr_window, cfg.signal_window) + 5
    if len(prices) <= min_start:
        raise ValueError("not enough history to build any cross-section")

    rows: list[pd.DataFrame] = []
    graph: GraphSources | None = None
    for i in range(min_start, len(prices)):
        as_of = prices.index[i]
        window = prices.iloc[: i + 1]
        needs_refresh = graph is None or (i - min_start) % cfg.refresh_every == 0
        if needs_refresh:
            corr_rets = corr_window_returns(window, cfg.graph.corr_window).dropna(how="any")
            graph = build_graph(corr_rets, sector_of, cfg.graph)

        raw_signal = rolling_return(window, cfg.signal_window).iloc[-1]
        signal = cross_sectional_zscore(raw_signal).reindex(graph.tickers)
        if signal.isna().any():
            continue

        rf = compute_residuals(signal, graph.sparse_weights, sector_of, cfg.diffusion)
        df = rf.as_frame()
        df.insert(0, "date", as_of)
        rows.append(df)

    if not rows:
        raise ValueError("no valid cross-sections produced across the given history")
    return pd.concat(rows, ignore_index=True)

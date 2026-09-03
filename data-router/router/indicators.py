"""Technical indicators, computed locally from bars — never from a vendor.

The spec is explicit: "Compute all technical indicators locally from bars."
(and `router/adapters/alpha_vantage.py`'s docstring repeats the rule for
whoever wires up a real vendor later: never consume a vendor's own SMA/RSI/
MACD/etc. endpoint, only its raw OHLCV bars.) This module is the one place
that computation happens, so every model gets the same indicator math
regardless of which vendor served the underlying bars.

Every function here is pure: `list[Bar]` (or a plain list of closes) in,
plain floats out. No vendor call, no provenance stamping, no I/O — those are
the router's and the adapters' job, not this module's. Indicators derived
from bars deliberately do NOT carry their own provenance record: they are a
computation over already-provenanced inputs, not a new observation, so
tracing "where did this come from" means tracing the input bars instead.

Bars are expected sorted ascending by `observation_date`; callers that pull
from `router.schema.Bar` records (already date-ordered by the adapters in
this repo) get that for free. Each function is defensive about too-few-bars
inputs (returns `[]`/`None` rather than raising) since "not enough history
yet" is a normal, non-exceptional condition for a young position or a
newly-listed name.
"""

from __future__ import annotations

from typing import Optional, Sequence

from .schema import Bar


def _closes(bars: Sequence[Bar]) -> list[float]:
    return [b.close for b in bars]


def sma(closes: Sequence[float], window: int) -> list[Optional[float]]:
    """Simple moving average. Returns one value per input close, `None`
    wherever fewer than `window` observations are available yet (so the
    output list is always the same length as the input — easy to zip with
    the source bars for a chart or a feature column)."""
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[Optional[float]] = []
    running_sum = 0.0
    for i, c in enumerate(closes):
        running_sum += c
        if i >= window:
            running_sum -= closes[i - window]
        if i >= window - 1:
            out.append(running_sum / window)
        else:
            out.append(None)
    return out


def ema(closes: Sequence[float], window: int) -> list[Optional[float]]:
    """Exponential moving average, seeded with the SMA of the first `window`
    observations (a standard, deterministic seeding choice) and smoothed with
    the conventional `alpha = 2 / (window + 1)` thereafter."""
    if window <= 0:
        raise ValueError("window must be positive")
    out: list[Optional[float]] = [None] * len(closes)
    if len(closes) < window:
        return out
    alpha = 2.0 / (window + 1)
    seed = sum(closes[:window]) / window
    out[window - 1] = seed
    prev = seed
    for i in range(window, len(closes)):
        prev = alpha * closes[i] + (1 - alpha) * prev
        out[i] = prev
    return out


def rsi(closes: Sequence[float], window: int = 14) -> list[Optional[float]]:
    """Relative Strength Index (Wilder's smoothing), 0-100. `None` for every
    index before `window` price changes are available (i.e. the first
    `window` entries, since RSI needs a *change* between consecutive
    closes)."""
    if window <= 0:
        raise ValueError("window must be positive")
    n = len(closes)
    out: list[Optional[float]] = [None] * n
    if n <= window:
        return out

    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    out[window] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(window, len(deltas)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        out[i + 1] = _rsi_from_averages(avg_gain, avg_loss)

    return out


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def macd(
    closes: Sequence[float],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """MACD line (`fast`-EMA minus `slow`-EMA), its `signal`-EMA, and the
    histogram (macd - signal). Each is a `list[Optional[float]]` the same
    length as `closes`; `None` wherever an upstream EMA isn't ready yet."""
    if fast <= 0 or slow <= 0 or signal <= 0:
        raise ValueError("fast, slow and signal windows must all be positive")
    fast_ema = ema(closes, fast)
    slow_ema = ema(closes, slow)
    macd_line: list[Optional[float]] = [
        (f - s) if (f is not None and s is not None) else None
        for f, s in zip(fast_ema, slow_ema)
    ]
    # The signal line is an EMA of the MACD line itself, computed only over
    # the contiguous non-None tail (macd_line is None until `slow` bars in).
    first_valid = next((i for i, v in enumerate(macd_line) if v is not None), None)
    signal_line: list[Optional[float]] = [None] * len(closes)
    if first_valid is not None:
        tail_ema = ema([v for v in macd_line[first_valid:]], signal)  # type: ignore[arg-type]
        for offset, value in enumerate(tail_ema):
            signal_line[first_valid + offset] = value
    histogram: list[Optional[float]] = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line, signal_line)
    ]
    return {"macd": macd_line, "signal": signal_line, "histogram": histogram}


def sma_from_bars(bars: Sequence[Bar], window: int) -> list[Optional[float]]:
    """Convenience wrapper: SMA computed directly from `Bar` records (sorted
    ascending by `observation_date`) rather than a bare list of closes."""
    return sma(_closes(bars), window)


def rsi_from_bars(bars: Sequence[Bar], window: int = 14) -> list[Optional[float]]:
    return rsi(_closes(bars), window)


def ema_from_bars(bars: Sequence[Bar], window: int) -> list[Optional[float]]:
    return ema(_closes(bars), window)


def macd_from_bars(bars: Sequence[Bar], fast: int = 12, slow: int = 26, signal: int = 9) -> dict:
    return macd(_closes(bars), fast=fast, slow=slow, signal=signal)

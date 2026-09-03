"""
Shared result types.

The one rule that matters here: **a price is never returned without a
standard error**. `MonteCarloResult` is the only object the engine hands
back for a simulated price, and every pricing function in `pe.engine` and
`pe.payoffs` returns one (or a `dict[str, MonteCarloResult]` for
multi-quantity payoffs like touch probability + expected time-to-touch).
A bare float price is a bug, not a convenience.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class MonteCarloResult:
    """A Monte Carlo estimate with its standard error, never without it.

    Attributes:
        price: the sample-mean estimate (already discounted, i.e. this is
            a price / probability / time in the instrument's natural units).
        std_error: the standard error of `price` (ddof=1 sample std / sqrt(n),
            with the "n" adjusted for antithetic pairing or control-variate
            reduction where those are used — see `pe.engine.mc`). NaN only
            when n_paths <= 1, which every constructor call rejects unless
            explicitly allowed.
        n_paths: raw number of simulated paths behind the estimate (before
            any antithetic pairing — i.e. the number of random draws spent,
            which is what you'd compare against a compute budget).
        meta: free-form diagnostic payload (e.g. {'antithetic': True,
            'control_variate': 'geometric_asian', 'beta': 0.94}). Never
            required for correctness, purely for audit trails.
    """

    price: float
    std_error: float
    n_paths: int
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.n_paths <= 0:
            raise ValueError("MonteCarloResult requires n_paths > 0")
        if self.std_error < 0 and not (self.std_error != self.std_error):  # allow NaN, reject negative
            raise ValueError(f"std_error cannot be negative, got {self.std_error}")

    def ci95(self) -> tuple[float, float]:
        """Approximate 95% confidence interval (normal approximation)."""
        half = 1.959963984540054 * self.std_error
        return (self.price - half, self.price + half)

    def within(self, reference: float, n_sigma: float = 3.0) -> bool:
        """True if `reference` sits within n_sigma standard errors of price.

        The standard tool for "did this MC estimate reproduce a known
        closed-form value" — used throughout pe/validation and the tests.
        """
        if self.std_error != self.std_error:  # NaN
            raise ValueError("cannot test 'within' against a NaN std_error")
        return abs(self.price - reference) <= n_sigma * self.std_error

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"MonteCarloResult(price={self.price:.6g}, std_error={self.std_error:.3g}, n_paths={self.n_paths})"

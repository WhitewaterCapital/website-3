"""First-passage (barrier-hit) probability for a double-barrier trade.

P(reach the target before the stop) for a process that, locally, looks like a
Brownian motion with drift. Start at the entry (0), target barrier at +a
(distance a > 0), stop barrier at -b (distance b > 0), drift `nu` per bar toward
the target, per-bar variance sigma^2:

    theta = 2*nu / sigma^2
    P(target before stop) = (1 - e^{theta*b}) / (e^{-theta*a} - e^{theta*b})

Driftless limit (nu -> 0): P = b / (a + b)  (the gambler's-ruin result — note it
does NOT depend on vol when there's no drift).

This is a LOCAL, single-regime approximation: real drift and vol drift over the
life of a trade. But it turns `expected_r` from a hardcoded target multiple into a
number that honestly moves with drift, vol, and the target/stop geometry. When
drift or vol can't be estimated, `barrier_hit_prob` returns None and callers must
abstain rather than fabricate an edge.
"""

from __future__ import annotations

import numpy as np


def barrier_hit_prob(a: float, b: float, drift: float, vol: float) -> float | None:
    """P(hit +a before -b). `a`/`b` are positive distances to target/stop, `drift`
    is signed per-bar drift toward the target (positive helps), `vol` is the per-bar
    standard deviation. Units of a, b, drift, vol must match. Returns None when the
    inputs don't admit an estimate."""
    if not (a > 0 and b > 0 and np.isfinite(drift) and np.isfinite(vol) and vol > 0):
        return None
    var = vol * vol
    theta = 2.0 * drift / var
    if abs(theta) < 1e-12:
        return float(b / (a + b))  # driftless gambler's ruin
    # Clamp exponents so a strong drift can't overflow.
    ea = float(np.exp(np.clip(-theta * a, -50.0, 50.0)))
    eb = float(np.exp(np.clip(theta * b, -50.0, 50.0)))
    den = ea - eb
    if den == 0.0:
        return float(b / (a + b))
    p = (1.0 - eb) / den
    return float(min(1.0, max(0.0, p)))


def expectancy(a: float, b: float, drift: float, vol: float) -> float | None:
    """Expected R of the trade: p*R - (1-p)*1, with R = a/b (reward:risk) and
    p = P(target before stop). None if p can't be estimated."""
    p = barrier_hit_prob(a, b, drift, vol)
    if p is None or b <= 0:
        return None
    R = a / b
    return float(p * R - (1.0 - p))

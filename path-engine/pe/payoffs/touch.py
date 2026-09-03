"""
First-passage / touch payoffs (PATH-03), treated as their own payoff family
rather than a side effect of barrier pricing — per the build spec, this is
"the part that pays for the build even if we never trade an exotic": a
touch/no-touch probability or an expected time-to-touch is a genuinely
useful risk-neutral quantity on its own (e.g. as a sanity check against a
options-market-implied touch probability, or as an input to a digital/
one-touch payoff), decoupled from pricing any specific barrier option.

**These are risk-neutral quantities under whatever model generated
`paths`** (GBM / local vol / Heston in this package) — the same boundary
warning as everywhere else in `pe/engine` applies: a risk-neutral touch
probability answers "what would a one-touch digital paying $1 on touch be
worth, discounted", not "what is the real-world chance this happens." See
`path-engine/README.md`.
"""
from __future__ import annotations

from typing import Literal, Optional

import numpy as np

from ..types import MonteCarloResult
from ..engine.mc import mc_stats
from .barrier import survival_probability_with_bridge

Direction = Literal["up", "down"]


def _touch_mask_and_first_index(paths: np.ndarray, level: float, direction: Literal["up", "down"]) -> tuple[np.ndarray, np.ndarray]:
    if direction == "up":
        hit = paths >= level
    else:
        hit = paths <= level
    touched = np.any(hit, axis=1)
    # argmax on a boolean array returns the index of the first True (ties
    # broken by "first occurrence"); on an all-False row it returns 0,
    # which is meaningless and must be masked out by `touched` at the call site.
    first_idx = np.argmax(hit, axis=1)
    return touched, first_idx


def touch_probability(
    paths: np.ndarray,
    level: float,
    direction: Direction,
    times: Optional[np.ndarray] = None,
    sigma_path: Optional[float | np.ndarray] = None,
) -> MonteCarloResult:
    """P(path touches `level` at any point) — a plain Bernoulli Monte Carlo
    estimate on the *discretely monitored* path by default (the indicator
    IS the discounted-at-r=0 "payoff" of a hypothetical unit one-touch paid
    at first touch with no time value; multiply by exp(-r*T) at the call
    site for the actual discounted digital value, since `T` and `r` are not
    this function's business).

    Like discretely-monitored barriers (see `pe.payoffs.barrier`), discrete
    monitoring *understates* touch probability relative to a continuously
    monitored underlying — a touch strictly between two monitored dates is
    invisible to a plain endpoint scan. Passing `times` and `sigma_path`
    applies the identical Brownian-bridge conditional-crossing correction
    used there (`survival_probability_with_bridge`): a touch level is just
    a one-sided barrier, so `1 - P(survive)` is exactly the corrected touch
    probability, reusing that function rather than re-deriving it.
    """
    if times is not None and sigma_path is not None:
        survive = survival_probability_with_bridge(paths, times, level, direction, sigma_path)
        return mc_stats(1.0 - survive, meta={"level": level, "direction": direction, "bridge_corrected": True})
    touched, _ = _touch_mask_and_first_index(paths, level, direction)
    return mc_stats(touched.astype(float), meta={"level": level, "direction": direction, "bridge_corrected": False})


def expected_time_to_touch(paths: np.ndarray, times: np.ndarray, level: float, direction: Direction) -> MonteCarloResult:
    """E[first touch time | touched within the simulated horizon].

    Necessarily **conditional** on touching: for paths that never touch the
    level within `times[-1]`, "time to touch" is not a finite number to
    average in — including them (e.g. as `times[-1]` or `inf`) would silently
    change the question being answered. `meta['touch_probability']` and
    `meta['n_touched']` are reported alongside so the caller can see how
    much of the sample this conditional estimate is actually based on (a
    conditional mean over 3 touching paths out of 100,000 is not a
    trustworthy number, and this makes that visible rather than hiding it
    behind a single float).
    """
    touched, first_idx = _touch_mask_and_first_index(paths, level, direction)
    n_touched = int(np.sum(touched))
    if n_touched == 0:
        raise ValueError("no simulated path touched the level within the horizon; cannot estimate a conditional mean")
    touch_times = times[first_idx[touched]]
    result = mc_stats(touch_times, meta={"level": level, "direction": direction})
    result.meta["touch_probability"] = n_touched / paths.shape[0]
    result.meta["n_touched"] = n_touched
    return result


def touch_then_recover_probability(
    paths: np.ndarray,
    touch_level: float,
    touch_direction: Direction,
    recover_level: float,
) -> MonteCarloResult:
    """P(path touches `touch_level` and, strictly afterward, reaches
    `recover_level` on the opposite side) within the simulated horizon.

    "Recover" means crossing back through `recover_level` in the direction
    opposite the touch: after a DOWN-touch, recovery is reaching *up* to
    `recover_level` (so `recover_level` should sit above `touch_level`,
    e.g. back near or above the starting spot); after an UP-touch, recovery
    is falling back down to `recover_level` (which should sit below
    `touch_level`). This function does not enforce that ordering — a
    nonsensical combination (e.g. a "recovery" level on the same side as
    the touch) just yields a probability, typically close to 1, that isn't
    a meaningful "recovery" in the usual sense; getting the levels right is
    the caller's responsibility.
    """
    touched, first_idx = _touch_mask_and_first_index(paths, touch_level, touch_direction)
    recover_direction: Literal["up", "down"] = "up" if touch_direction == "down" else "down"

    n_paths, n_cols = paths.shape
    recovered = np.zeros(n_paths, dtype=bool)
    touched_positions = np.where(touched)[0]
    for p in touched_positions:
        after = paths[p, first_idx[p] + 1 :]
        if after.size == 0:
            continue
        if recover_direction == "up":
            recovered[p] = np.any(after >= recover_level)
        else:
            recovered[p] = np.any(after <= recover_level)

    outcome = (touched & recovered).astype(float)
    return mc_stats(
        outcome,
        meta={
            "touch_level": touch_level,
            "touch_direction": touch_direction,
            "recover_level": recover_level,
            "touch_probability": float(np.mean(touched)),
        },
    )

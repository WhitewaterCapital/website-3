"""WW-DECISION — the v1.0 fixed-weight fallback path (IMP-19).

The doc: "Keep the v1.0 reliability weighting with shrinkage as the
fallback path. If the allocator fails to solve or goes unstable we drop
back to fixed weights and raise an alarm."

This module implements *only* the fixed-weight scheme itself — a plain,
allocator-independent function of each strategy's reliability score. It
has no dependency on `alloc/solve.py`, no notion of "the allocator failed",
and no alarm logic; the switch/fallback decision (and the alarm) lives in
`boundary.py`, which calls this module when it needs to.

**The scheme:** each strategy's reliability score is shrunk toward the
equal-weight mean of all reliability scores by `shrinkage` (a fraction in
`[0, 1]`), then the shrunk scores are normalised to sum to 1:

    mean_reliability = mean(reliabilities)
    shrunk_i = (1 - shrinkage) * reliability_i + shrinkage * mean_reliability
    weight_i = shrunk_i / sum(shrunk)

Boundary behaviour, both intentional and tested:
  - `shrinkage=0.0`: no shrinkage at all — weights are exactly the raw
    reliability scores, renormalised to sum to 1 (i.e. proportional to raw
    reliability).
  - `shrinkage=1.0`: every score is fully shrunk to the same mean value,
    so every strategy ends up with an equal weight `1/n` regardless of its
    raw reliability — "fixed, allocator-independent equal weighting" in
    the most literal sense.
"""

from __future__ import annotations

DEFAULT_SHRINKAGE = 0.5  # documented default; callers should pass an explicit value in production


def fixed_weight_fallback(
    strategy_reliabilities: dict[str, float], shrinkage: float = DEFAULT_SHRINKAGE
) -> dict[str, float]:
    """Compute shrunk, normalised fixed weights from reliability scores.

    Raises `ValueError` if:
      - `strategy_reliabilities` is empty (no strategies to weight),
      - any reliability score is negative or non-finite (a reliability
        score is not a signed quantity here — it is meant to be
        weight-like, so a negative or NaN/inf value is a caller bug
        upstream, not something this function should silently clamp),
      - `shrinkage` is outside `[0, 1]` or non-finite,
      - the shrunk scores sum to (numerically) zero, which happens only
        when every reliability score is exactly 0 and `0 <= shrinkage < 1`
        (nothing to normalise against) — this function refuses to
        fabricate a uniform weighting in that case; a caller that wants
        "all strategies are equally unreliable -> equal weight anyway"
        should pass `shrinkage=1.0` explicitly. `shrinkage=1.0` is handled
        as a direct special case that returns `1/n` for every strategy
        regardless of the raw scores (full shrinkage means the raw scores
        are fully discarded by definition), so it never hits this
        all-zero-mean degeneracy in the first place.
    """
    if not strategy_reliabilities:
        raise ValueError("strategy_reliabilities must not be empty")

    if shrinkage != shrinkage or shrinkage in (float("inf"), float("-inf")):
        raise ValueError(f"shrinkage must be a finite number, got {shrinkage!r}")
    if not (0.0 <= shrinkage <= 1.0):
        raise ValueError(f"shrinkage must be in [0, 1], got {shrinkage!r}")

    names = list(strategy_reliabilities.keys())
    values = []
    for name in names:
        v = strategy_reliabilities[name]
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError(f"reliability for {name!r} must be finite, got {v!r}")
        if v < 0:
            raise ValueError(f"reliability for {name!r} must be non-negative, got {v!r}")
        values.append(float(v))

    n = len(values)

    if shrinkage == 1.0:
        # Full shrinkage discards the raw reliability scores entirely, by
        # definition -> every strategy gets exactly 1/n. Handled as a direct
        # special case (rather than falling through to the mean/normalise
        # arithmetic below) specifically so an all-zero reliability input
        # still yields a well-defined equal weighting instead of a spurious
        # 0/0 degeneracy -- shrinkage=1.0 means "ignore the raw scores," so
        # what those raw scores happened to be cannot matter here.
        return {name: 1.0 / n for name in names}

    mean_reliability = sum(values) / n

    shrunk = [(1.0 - shrinkage) * v + shrinkage * mean_reliability for v in values]
    total = sum(shrunk)
    if total == 0.0:
        raise ValueError(
            "all reliability scores are zero and shrinkage < 1.0, so shrunk weights "
            "cannot be normalised — pass shrinkage=1.0 for an explicit equal weighting"
        )

    return {name: s / total for name, s in zip(names, shrunk)}

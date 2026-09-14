"""Standardized Unexpected Earnings (SUE) — pure computation, no I/O.

SUE = (actual EPS − consensus EPS estimate) / stdev(trailing EPS surprises)

This is the Foster–Olsen–Shevlin (1984) formulation cited in this repo's own
research/equity-model-research-dossier.md ("Earnings/revenue surprise (SUE)"
row, `Foster-Olsen-Shevlin (1984)`, confidence High, "Drives PEAD") — using
the *consensus-estimate* variant of the expectation model (actual − analyst
consensus) rather than the seasonal-random-walk variant (actual − same
quarter last year), because a consensus estimate is what
adapters/alpha_vantage_estimates.py can actually source for free (see that
module's docstring for the verified-vs-inferred provenance of that claim).

Deliberately kept dependency-free and separate from export.py/adapters so it
can be unit-tested without touching the network-gated adapter at all — same
reason config.py's env() helper and synthetic.py's generator are isolated
pure functions in every other engine in this repo.

HONEST ABSTENTION: `compute_sue()` returns (None, reason) — never a
fabricated number — whenever any required input is missing or the
denominator would be numerically degenerate (zero or near-zero stdev, which
would blow a small numerator up into a meaningless enormous SUE rather than
a real signal). The dossier's own row for this target says the target
itself, sign(actual−estimate), needs "estimate timing" handled carefully —
this module does not attempt that; it only computes the standardized
magnitude once both an actual and a usable estimate/stdev exist. Whether the
*sign* is used downstream is a caller concern (see earnings-move.ts).
"""

from __future__ import annotations

import statistics

# Below this many trailing quarters of (actual − estimate) surprise history,
# a sample stdev is too noisy to trust as a SUE denominator — one or two
# data points can make the stdev arbitrarily small (or, with n=1, undefined:
# statistics.stdev requires n>=2), which would let a tiny numerator produce
# an absurd SUE. 4 quarters (a full year) is the minimum this engine
# accepts; Foster-Olsen-Shevlin's own original study used ~8 quarters of
# history, so even 4 is already a deliberately conservative floor, not a
# generous one.
MIN_SURPRISE_QUARTERS_FOR_STDEV = 4

# A stdev below this (in EPS dollars) is treated as numerically degenerate
# rather than "the company has remarkably consistent surprises" — floating
# point noise and near-zero-EPS companies can produce a stdev near zero,
# and dividing by it would manufacture a huge, meaningless SUE out of a
# tiny, immaterial numerator. This is a numerical-stability floor, not a
# statistical claim about what counts as "low dispersion."
MIN_USABLE_STDEV = 0.005


def estimate_stdev_from_surprises(surprises: list[float]) -> tuple[float | None, str | None]:
    """Sample stdev of trailing (actual − estimate) EPS surprises, or
    (None, reason) when there isn't enough history to trust one. Never
    silently drops to a smaller-than-intended window — the caller passes
    exactly the trailing window it wants a stdev over."""
    n = len(surprises)
    if n < MIN_SURPRISE_QUARTERS_FOR_STDEV:
        return None, (
            f"only {n} trailing quarter(s) of surprise history available "
            f"(need >= {MIN_SURPRISE_QUARTERS_FOR_STDEV} for a trustworthy stdev)"
        )
    sd = statistics.stdev(surprises)
    if sd < MIN_USABLE_STDEV:
        return None, (
            f"trailing surprise stdev ({sd:.4f}) is below the numerical-stability "
            f"floor ({MIN_USABLE_STDEV}) — dividing by it would manufacture an "
            f"outsized SUE from a tiny, immaterial numerator"
        )
    return sd, None


def compute_sue(
    eps_actual: float | None,
    eps_estimate: float | None,
    eps_estimate_stdev: float | None,
) -> tuple[float | None, str | None]:
    """Returns (sue, abstain_reason) — exactly one of the two is non-None.

    By construction, every event WW-EARNINGS exports is a PRE-print event
    (report_date is always in the future — see config.LOOKAHEAD_DAYS and
    synthetic.py/tests asserting report_date > today). That means
    `eps_actual` is essentially always None in this engine's own exports:
    SUE cannot exist before the number it's built from exists. This
    function still lives here, fully real and fully tested, so that (a) the
    honest reason surfaced to the website says exactly why SUE is absent
    rather than a generic null, and (b) a future retrospective/eval script
    (the dossier's own "AUC, Brier" evaluation of this target) can call the
    exact same tested logic once actuals are available, instead of a second
    ad hoc reimplementation.
    """
    if eps_actual is None:
        return None, "actual EPS not yet reported — this is a pre-print calendar event; SUE only exists after the print"
    if eps_estimate is None:
        return None, "no consensus EPS estimate available for this ticker/print"
    if eps_estimate_stdev is None:
        return None, "no usable trailing-surprise stdev available for this ticker (see eps_estimate_stdev / estimate_unavailable_reason)"
    return (eps_actual - eps_estimate) / eps_estimate_stdev, None

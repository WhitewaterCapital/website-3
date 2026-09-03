"""IMP-07 — source-aware refresh guard.

The acceptance test named directly in the spec: "a monthly CPI series
shows the same source observed date across 60 consecutive hourly refreshes
while its derived z score only updates when a genuinely new input
vintage arrives."

This is a distinct concern from both `scheduler.py`'s freshness/staleness
machinery and `market_hours.py`'s open/closed gate — neither of those asks
"did the underlying monthly/quarterly print actually change, or did we
just refetch the same vintage again". A CPI print is published once a
month; an hourly refresh job that recomputes it will call the same
upstream API 60 times before a new print exists, and each of those 60
calls will hand back a payload carrying the SAME observed (release) date.
The bug this guards against: naively taking whatever the latest fetch
says and stamping "as of <now>" on it, which silently manufactures 60
distinct "new" observation dates for one real print — restating the
observation date on every refresh, not just recomputing off it.

`SourceAwareRefresh` enforces the doc's "source aware rule" directly:
    - the STORED observed-date only ever advances to a fetched
      observed-date that is strictly newer than what's already stored;
      a same-or-older-dated fetch is fetched, looked at, and discarded
      for the purposes of "what vintage do we have" — it never restates
      or regresses the stored date.
    - the DERIVED value (e.g. a z-score against a rolling window) is
      recomputed on every single refresh call regardless, because the
      window/context data it recomputes against can and does move even
      when the underlying source vintage hasn't (more recent context
      observations shift a rolling mean/std even if the CPI print itself
      is unchanged).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Sequence


@dataclass(frozen=True)
class SourceObservation:
    """One fetched reading of a source series: its value, and the date the
    SOURCE itself claims this value was observed/released (e.g. the BLS's
    stated release date for a CPI print) — not the time we happened to
    fetch it."""

    observed_date: date
    value: float


def zscore(value: float, window: Sequence[float]) -> float:
    """Default derived-value function: a plain population z-score of
    `value` against `window`. `window` is expected to be the rolling
    context data (e.g. trailing months of the same series, or a broader
    reference basket) — NOT required to include `value` itself."""
    n = len(window)
    if n == 0:
        raise ValueError("rolling window must not be empty")
    mean = sum(window) / n
    variance = sum((x - mean) ** 2 for x in window) / n
    std = variance ** 0.5
    if std == 0:
        return 0.0
    return (value - mean) / std


@dataclass
class RefreshResult:
    stored: SourceObservation
    derived_value: float
    observed_date_advanced: bool  # True only on the call where the stored date actually moved


@dataclass
class SourceAwareRefresh:
    """Stateful guard around one monthly/quarterly source series.

    `series_name` is a label only. `initial` seeds the starting known
    observation. `derive_fn(value, window) -> float` computes the derived
    value each call; defaults to `zscore`.

    Call `refresh(fetched, context_window)` once per scheduled refresh
    (e.g. once per hourly equity-clock tick). It:
      1. Advances the stored observation to `fetched` ONLY if
         `fetched.observed_date > stored.observed_date` (a genuinely newer
         vintage). A same-dated or older-dated fetch never changes the
         stored value or date — this is the "never restates the
         observation date" rule.
      2. Recomputes the derived value from whichever observation ends up
         stored (freshly advanced or not) against `context_window`, on
         every call, unconditionally.
    """

    series_name: str
    initial: SourceObservation
    derive_fn: Callable[[float, Sequence[float]], float] = zscore
    _stored: SourceObservation = field(init=False)
    observed_date_history: list[date] = field(init=False, default_factory=list)
    derived_history: list[float] = field(init=False, default_factory=list)

    def __post_init__(self) -> None:
        self._stored = self.initial

    @property
    def stored(self) -> SourceObservation:
        return self._stored

    def refresh(self, fetched: SourceObservation, context_window: Sequence[float]) -> RefreshResult:
        advanced = fetched.observed_date > self._stored.observed_date
        if advanced:
            self._stored = fetched
        # else: same-dated (or, defensively, an out-of-order older-dated)
        # fetch is discarded for state purposes — the stored observation
        # and its date are left exactly as they were. This is deliberate
        # even when `fetched.value` differs from the stored value on the
        # same observed_date (e.g. vendor noise/rounding on a re-fetch of
        # the same vintage): the rule is about the OBSERVATION DATE never
        # being restated, so a same-dated re-fetch cannot move it, and we
        # keep the value that came with the date we're standing behind.

        derived = self.derive_fn(self._stored.value, context_window)
        self.observed_date_history.append(self._stored.observed_date)
        self.derived_history.append(derived)
        return RefreshResult(stored=self._stored, derived_value=derived, observed_date_advanced=advanced)

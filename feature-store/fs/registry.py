"""Feature registry -- FEAT-01.

Spec: "A registry of named feature definitions ... Define each feature
once as a pure function of point in time inputs, with name, version,
owner, lookback and a written economic rationale. No rationale, no
registration."

`FeatureDef` is the one place a feature's math, ownership, lookback,
economic rationale, and missing-data policy get declared. Everything else
in this package -- the batch panel builder (panel.py) and the live serving
path (live.py) -- calls `FeatureDef.compute` itself; neither ever holds an
independent re-derivation of a feature's math. That is the mechanism that
makes "batch and live produce identical values for the same timestamp"
(the FEAT-01 acceptance test) true by construction rather than by
convention.

`compute` is expected to be a PURE, non-anticipative function of its input:
    per_security:      compute(history: pd.DataFrame) -> pd.Series
                        aligned to history.index, using only backward-
                        looking pandas ops (rolling, ewm, diff, pct_change,
                        shift(+k)) -- never a centered window or shift(-k).
                        Appending future rows to `history` must never
                        change an already-computed row's value. This
                        invariant is exactly what
                        tests/test_batch_live_parity.py checks.
    cross_sectional:    compute(cross_section: pd.DataFrame) -> pd.Series
                        indexed by security, for a SINGLE date's snapshot
                        (one row per security). See cross_sectional.py.
"""
from __future__ import annotations

import dataclasses
from typing import Callable, Literal, Optional, Tuple

import pandas as pd

MissingDataPolicy = Literal["forward_fill_max_age", "treat_as_missing", "fail"]
FeatureKind = Literal["per_security", "cross_sectional"]

_VALID_POLICIES = {"forward_fill_max_age", "treat_as_missing", "fail"}
_VALID_KINDS = {"per_security", "cross_sectional"}


@dataclasses.dataclass(frozen=True)
class FeatureDef:
    """A single registered feature definition.

    Fields map directly onto the spec's list: name, version, owner,
    lookback, rationale, plus the missing-data policy and the pure
    `compute` function itself.

    `kind` and `base_feature` are engineering additions beyond the spec's
    literal field list, needed to support "cross sectional transforms are
    separate registered features": a cross-sectional FeatureDef's
    `compute` has a different signature (operates on a single date's
    cross-section of securities, not one security's time series), and
    `base_feature` records which (name, version) it was built on top of,
    purely for documentation / manifest readability.
    """

    name: str
    version: str
    owner: str
    lookback: int  # periods of history compute() needs before it can produce a real value
    rationale: str
    missing_data_policy: MissingDataPolicy
    compute: Callable[[pd.DataFrame], pd.Series]
    max_age_periods: Optional[int] = None  # required iff missing_data_policy == "forward_fill_max_age"
    kind: FeatureKind = "per_security"
    base_feature: Optional[Tuple[str, str]] = None  # (name, version) of the base feature, for cross_sectional kind

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("FeatureDef.name must be a non-empty string")
        if not self.version or not self.version.strip():
            raise ValueError(f"FeatureDef({self.name!r}): version must be a non-empty string")
        if not self.owner or not self.owner.strip():
            raise ValueError(f"FeatureDef({self.name!r}): owner must be a non-empty string")
        if not self.rationale or not self.rationale.strip():
            # Spec, verbatim: "No rationale, no registration."
            raise ValueError(
                f"FeatureDef({self.name!r}): a written economic rationale is required "
                "to register a feature (FEAT-01: 'No rationale, no registration.')"
            )
        if self.lookback < 0:
            raise ValueError(f"FeatureDef({self.name!r}): lookback must be >= 0 periods")
        if self.missing_data_policy not in _VALID_POLICIES:
            raise ValueError(
                f"FeatureDef({self.name!r}): missing_data_policy must be one of "
                f"{sorted(_VALID_POLICIES)}, got {self.missing_data_policy!r}"
            )
        if self.missing_data_policy == "forward_fill_max_age":
            if self.max_age_periods is None or self.max_age_periods <= 0:
                raise ValueError(
                    f"FeatureDef({self.name!r}): missing_data_policy='forward_fill_max_age' "
                    "requires a positive integer max_age_periods"
                )
        elif self.max_age_periods is not None:
            raise ValueError(
                f"FeatureDef({self.name!r}): max_age_periods is only meaningful for "
                "missing_data_policy='forward_fill_max_age'"
            )
        if self.kind not in _VALID_KINDS:
            raise ValueError(f"FeatureDef({self.name!r}): kind must be one of {sorted(_VALID_KINDS)}")
        if self.kind == "cross_sectional" and self.missing_data_policy == "forward_fill_max_age":
            # "Maximum age" is a statement about time (periods), and a
            # cross-sectional feature's compute() operates on a single
            # date's snapshot indexed by security, not on a time series --
            # forward-filling "across securities" would be a meaningless
            # (and dangerous) operation, not a time-based fill at all.
            raise ValueError(
                f"FeatureDef({self.name!r}): cross_sectional features cannot use "
                "missing_data_policy='forward_fill_max_age' (there is no time axis to "
                "age against within a single date's cross-section); use "
                "'treat_as_missing' or 'fail'"
            )
        if not callable(self.compute):
            raise ValueError(f"FeatureDef({self.name!r}): compute must be callable")


class FeatureRegistry:
    """Registers and looks up `FeatureDef`s.

    Registration integrity: a duplicate (name, version) pair is refused --
    a feature that "exists in two places" (the spec's fear) starts with
    exactly this: two different registrations claiming the same identity.
    A missing rationale is refused earlier, inside `FeatureDef.__post_init__`,
    before it ever reaches `.register()`.
    """

    def __init__(self) -> None:
        self._by_key: dict[Tuple[str, str], FeatureDef] = {}
        self._by_name: dict[str, list[FeatureDef]] = {}

    def register(self, feature_def: FeatureDef) -> FeatureDef:
        key = (feature_def.name, feature_def.version)
        if key in self._by_key:
            raise ValueError(
                f"feature already registered: {feature_def.name!r} v{feature_def.version!r}"
            )
        self._by_key[key] = feature_def
        self._by_name.setdefault(feature_def.name, []).append(feature_def)
        return feature_def

    def get(self, name: str, version: Optional[str] = None) -> FeatureDef:
        if version is not None:
            try:
                return self._by_key[(name, version)]
            except KeyError:
                raise KeyError(f"no such feature registered: {name!r} v{version!r}") from None
        versions = self._by_name.get(name)
        if not versions:
            raise KeyError(f"no such feature registered: {name!r}")
        # Unversioned lookup resolves to the most-recently-registered version.
        return versions[-1]

    def list(self) -> list[FeatureDef]:
        """Every registered FeatureDef, sorted by (name, version) for
        deterministic iteration order."""
        return sorted(self._by_key.values(), key=lambda f: (f.name, f.version))

    def __contains__(self, name: str) -> bool:
        return name in self._by_name

    def __len__(self) -> int:
        return len(self._by_key)

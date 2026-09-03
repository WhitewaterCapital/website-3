"""Feature registry.

Spec: "Register each feature as a small documented pure function (name,
version, lookback, one-line economic rationale in a docstring)." This module
is the mechanism for that: `@feature(...)` wraps a pure per-ticker function
(weekly base frame -> aligned Series) and records it in FEATURE_REGISTRY.

`manifest()` / `manifest_hash()` turn the registered (name, version) pairs —
plus the cross-sectional derived columns panel.py adds on top — into the
`feature_manifest_hash` published in export.py. It exists so a consumer of
the export can tell, cheaply, whether the feature set under a forecast
changed between two runs, without diffing this whole package.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Callable

import pandas as pd


@dataclass(frozen=True)
class FeatureSpec:
    name: str
    version: str
    lookback_weeks: int
    rationale: str
    fn: Callable[[pd.DataFrame], pd.Series]


FEATURE_REGISTRY: list[FeatureSpec] = []
_NAMES: set[str] = set()


def feature(name: str, version: str, lookback_weeks: int, rationale: str):
    """Decorator: register `fn(base_df) -> Series` as a named, versioned,
    documented feature. Raises on a duplicate name (registry integrity)."""

    def deco(fn: Callable[[pd.DataFrame], pd.Series]):
        if name in _NAMES:
            raise ValueError(f"duplicate feature name registered: {name!r}")
        _NAMES.add(name)
        fn.__doc__ = (fn.__doc__ or "") + f"\n\nRationale: {rationale}"
        fn.feature_name = name
        fn.feature_version = version
        fn.feature_lookback_weeks = lookback_weeks
        FEATURE_REGISTRY.append(FeatureSpec(name, version, lookback_weeks, rationale, fn))
        return fn

    return deco


def base_manifest() -> list[dict]:
    """The (name, version, lookback) triples for every @feature-registered
    per-ticker function, sorted by name for a stable hash."""
    return [
        {"name": s.name, "version": s.version, "lookback_weeks": s.lookback_weeks}
        for s in sorted(FEATURE_REGISTRY, key=lambda s: s.name)
    ]


def manifest_hash(entries: list[dict]) -> str:
    """A short, stable hash of a manifest (name+version pairs). Not
    cryptographic — just a cheap fingerprint for "did the feature set change".
    """
    blob = json.dumps(
        [{"name": e["name"], "version": e["version"]} for e in sorted(entries, key=lambda e: e["name"])],
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]

"""Feature manifest hashing -- FEAT-01.

Spec: "Store a feature manifest hash with every training run. If the hash
changes the model retrains before it serves again." ... "Done when [...]
every model artifact records the manifest hash it trained against."

A manifest is the set of (name, version) pairs a model actually trained
against -- not necessarily every feature ever registered in a process's
`FeatureRegistry` (a given model may only consume a subset).
`manifest_hash` is a stable sha256 over a canonical, sorted JSON
representation of that set: two runs using the identical feature set
always agree, and any change -- a new feature added, one dropped, or an
existing one's version bumped -- changes the hash. Owner, rationale,
lookback and the compute function's identity are deliberately excluded:
changing a docstring or reassigning ownership should not force a retrain,
only a change to what a feature computes (which is what a version bump is
supposed to signal) should.
"""
from __future__ import annotations

import hashlib
import json
from typing import Iterable

from .registry import FeatureDef


def build_manifest(feature_defs: Iterable[FeatureDef]) -> list[dict]:
    """The (name, version) pairs used by a model, sorted for a stable,
    order-independent hash."""
    entries = [{"name": fd.name, "version": fd.version} for fd in feature_defs]
    return sorted(entries, key=lambda e: (e["name"], e["version"]))


def manifest_hash(feature_defs: Iterable[FeatureDef]) -> str:
    """Full sha256 hex digest of the canonical manifest built from
    `feature_defs`. Stable across process restarts, dict ordering, and set
    iteration order; changes if and only if the (name, version) set
    changes."""
    manifest = build_manifest(feature_defs)
    blob = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def manifest_changed(old_hash: str, new_hash: str) -> bool:
    """True iff a model artifact trained against `old_hash` must retrain
    before it is allowed to serve again under `new_hash`.

    A falsy `old_hash` (empty string, None -- no prior training run
    recorded) counts as changed: there is nothing to compare against, so
    the safe default is "retrain before first serving", not "assume it's
    fine".
    """
    if not old_hash:
        return True
    return old_hash != new_hash

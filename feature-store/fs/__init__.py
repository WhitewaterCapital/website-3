"""
fs -- the feature store (FEAT-01).

Spec (verbatim from the project's requirements doc):

    "A registry of named feature definitions, a batch job computing them
    into a dated panel, and a serving path returning the same computation
    live. Define each feature once as a pure function of point in time
    inputs, with name, version, owner, lookback and a written economic
    rationale. No rationale, no registration. Compute the panel as a dated
    table indexed by security and date. Never compute features inside a
    training script. A feature that exists in two places will diverge.
    Serve live inference from the same function called with as of now,
    plus a test comparing batch and live on the same timestamp that fails
    on any mismatch. Cross sectional transforms are separate registered
    features. [...] Every feature declares a missing data policy. [...]
    Never fill with zero, because zero is a real value for a return. Store
    a feature manifest hash with every training run. If the hash changes
    the model retrains before it serves again. Done when batch and live
    produce identical values for the same timestamp and every model
    artifact records the manifest hash it trained against."

This package is a standalone, sealed root (no other engine imports it in
this pass). Module map:

  registry.py         FeatureDef, FeatureRegistry -- the one place a
                       feature's math, owner, lookback, rationale and
                       missing-data policy are declared.
  missing_data.py      apply_missing_data_policy() -- the one place a
                       policy (forward_fill_max_age / treat_as_missing /
                       fail) is enforced against a raw computed series.
                       Batch and live both call this, never their own copy.
  panel.py             build_panel() -- the batch job: dated
                       (security, date) table, one column per feature.
  live.py              compute_live_feature() / compute_live_cross_sectional()
                       -- the serving path. Calls the exact same
                       FeatureDef.compute object build_panel() calls.
  cross_sectional.py   rank / z-score-within-universe / z-score-within-
                       sector, each its OWN registered FeatureDef.
  manifest.py          build_manifest() / manifest_hash() / manifest_changed()
                       -- what a model artifact records about the feature
                       set it trained against.
  sample_features.py   A small SAMPLE/DEMO feature set (lagged returns,
                       RSI, realized vol) proving the mechanics end to end.
                       Not a production feature set -- see README.md.
  synthetic.py         Deterministic SAMPLE OHLCV generator used only by
                       this package's own tests. Not real market data.

See feature-store/README.md for the full design writeup.
"""
from __future__ import annotations

from .manifest import build_manifest, manifest_changed, manifest_hash
from .missing_data import MissingDataFailure, apply_missing_data_policy
from .registry import FeatureDef, FeatureRegistry

__all__ = [
    "FeatureDef",
    "FeatureRegistry",
    "apply_missing_data_policy",
    "MissingDataFailure",
    "build_manifest",
    "manifest_hash",
    "manifest_changed",
]

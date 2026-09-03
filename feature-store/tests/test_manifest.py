"""Feature manifest hash tests -- FEAT-01 (f).

Spec: "Store a feature manifest hash with every training run. If the hash
changes the model retrains before it serves again."
"""
from __future__ import annotations

from fs.manifest import build_manifest, manifest_changed, manifest_hash
from fs.registry import FeatureDef, FeatureRegistry


def _feature(name, version, compute=None):
    return FeatureDef(
        name=name,
        version=version,
        owner="quant-team",
        lookback=1,
        rationale="Test fixture feature for manifest hashing.",
        missing_data_policy="treat_as_missing",
        compute=compute or (lambda h: h["close"].astype(float)),
    )


def test_manifest_hash_is_stable_for_the_identical_feature_set():
    registry_a = FeatureRegistry()
    registry_a.register(_feature("feat_x", "1.0.0"))
    registry_a.register(_feature("feat_y", "2.0.0"))

    registry_b = FeatureRegistry()
    registry_b.register(_feature("feat_y", "2.0.0"))  # registered in a different order
    registry_b.register(_feature("feat_x", "1.0.0"))

    hash_a = manifest_hash(registry_a.list())
    hash_b = manifest_hash(registry_b.list())
    assert hash_a == hash_b


def test_manifest_hash_is_stable_across_repeated_calls():
    registry = FeatureRegistry()
    registry.register(_feature("feat_x", "1.0.0"))
    h1 = manifest_hash(registry.list())
    h2 = manifest_hash(registry.list())
    assert h1 == h2


def test_manifest_hash_changes_when_a_feature_version_changes():
    registry_v1 = FeatureRegistry()
    registry_v1.register(_feature("feat_x", "1.0.0"))
    hash_v1 = manifest_hash(registry_v1.list())

    registry_v2 = FeatureRegistry()
    registry_v2.register(_feature("feat_x", "1.1.0"))  # same name, bumped version
    hash_v2 = manifest_hash(registry_v2.list())

    assert hash_v1 != hash_v2


def test_manifest_hash_changes_when_a_feature_is_added_or_removed():
    registry = FeatureRegistry()
    registry.register(_feature("feat_x", "1.0.0"))
    hash_before = manifest_hash(registry.list())

    registry.register(_feature("feat_y", "1.0.0"))
    hash_after_add = manifest_hash(registry.list())
    assert hash_after_add != hash_before

    hash_subset = manifest_hash([registry.get("feat_x")])
    assert hash_subset == hash_before


def test_manifest_hash_unaffected_by_owner_or_rationale_changes():
    """Changing who owns a feature or how its rationale is worded should
    not force a retrain -- only what it computes (signaled by a version
    bump) should."""
    fd_a = _feature("feat_x", "1.0.0")
    fd_b = FeatureDef(
        name="feat_x",
        version="1.0.0",
        owner="a-completely-different-owner",
        lookback=1,
        rationale="A totally different rationale, differently worded.",
        missing_data_policy="fail",  # even the policy differs
        compute=lambda h: h["close"].astype(float) * 2,  # even the math differs
    )
    assert manifest_hash([fd_a]) == manifest_hash([fd_b])


def test_build_manifest_shape():
    registry = FeatureRegistry()
    registry.register(_feature("feat_b", "1.0.0"))
    registry.register(_feature("feat_a", "2.0.0"))
    manifest = build_manifest(registry.list())
    assert manifest == [
        {"name": "feat_a", "version": "2.0.0"},
        {"name": "feat_b", "version": "1.0.0"},
    ]


def test_manifest_changed_true_when_hashes_differ():
    assert manifest_changed("abc123", "def456") is True


def test_manifest_changed_false_when_hashes_match():
    assert manifest_changed("abc123", "abc123") is False


def test_manifest_changed_true_when_no_prior_hash_recorded():
    assert manifest_changed("", "abc123") is True
    assert manifest_changed(None, "abc123") is True

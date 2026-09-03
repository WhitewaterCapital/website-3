"""Cross-sectional transform tests -- FEAT-01 (g).

Spec: "Cross sectional transforms are separate registered features. Rank,
z score within universe and z score within sector are three different
features and get named as such."
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from fs.cross_sectional import add_cross_sectional_column, register_cross_sectional_transforms
from fs.manifest import manifest_hash
from fs.registry import FeatureDef, FeatureRegistry
from fs.sample_features import register_sample_features


def test_cross_sectional_transforms_are_registered_as_distinct_named_features():
    registry = FeatureRegistry()
    sample = register_sample_features(registry, owner="test-owner")
    base = sample["ret_lag_1"]

    rank_fd, zu_fd, zs_fd = register_cross_sectional_transforms(registry, base, owner="test-owner")

    names = {fd.name for fd in registry.list()}
    assert "ret_lag_1" in names
    assert "ret_lag_1_rank" in names
    assert "ret_lag_1_zscore_universe" in names
    assert "ret_lag_1_zscore_sector" in names
    # three genuinely distinct names, not the same feature registered thrice
    assert len({rank_fd.name, zu_fd.name, zs_fd.name}) == 3
    assert rank_fd.name != base.name
    assert zu_fd.name != base.name
    assert zs_fd.name != base.name

    for fd in (rank_fd, zu_fd, zs_fd):
        assert fd.kind == "cross_sectional"
        assert fd.base_feature == (base.name, base.version)
        assert fd.rationale  # each carries its own written rationale, not the base's


def test_cross_sectional_features_contribute_their_own_manifest_entries():
    """A model that trains on a base feature AND its cross-sectional
    transforms must see all four (name, version) pairs in its manifest --
    they are separate features for FEAT-01's manifest-hash purposes too."""
    registry = FeatureRegistry()
    sample = register_sample_features(registry, owner="test-owner")
    base = sample["ret_lag_1"]
    rank_fd, zu_fd, zs_fd = register_cross_sectional_transforms(registry, base, owner="test-owner")

    manifest_with_xs = manifest_hash([base, rank_fd, zu_fd, zs_fd])
    manifest_base_only = manifest_hash([base])
    assert manifest_with_xs != manifest_base_only


def test_rank_is_percentile_rank_within_the_snapshot():
    base_col = "raw"
    cross_section = pd.DataFrame({base_col: [10.0, 30.0, 20.0, 40.0]}, index=["A", "B", "C", "D"])
    fd = FeatureDef(
        name="raw_rank",
        version="1.0.0",
        owner="test-owner",
        lookback=0,
        rationale="Test rationale for percentile rank.",
        missing_data_policy="treat_as_missing",
        kind="cross_sectional",
        compute=lambda cs: cs[base_col].rank(pct=True),
    )
    result = fd.compute(cross_section)
    assert result.loc["A"] == 0.25
    assert result.loc["D"] == 1.0


def test_zscore_universe_known_values():
    registry = FeatureRegistry()
    base = registry.register(
        FeatureDef(
            name="base_feat",
            version="1.0.0",
            owner="test-owner",
            lookback=0,
            rationale="Base feature for a known-answer zscore test.",
            missing_data_policy="treat_as_missing",
            compute=lambda h: h["close"].astype(float),
        )
    )
    _, zu_fd, _ = register_cross_sectional_transforms(registry, base, owner="test-owner")

    cross_section = pd.DataFrame({"base_feat": [1.0, 2.0, 3.0, 4.0, 5.0]}, index=list("ABCDE"))
    result = zu_fd.compute(cross_section)
    # mean=3, population std = sqrt(2) ~= 1.4142
    expected_std = np.std([1.0, 2.0, 3.0, 4.0, 5.0], ddof=0)
    assert result.loc["A"] == pytest.approx((1.0 - 3.0) / expected_std)
    assert result.loc["C"] == pytest.approx(0.0)
    assert result.loc["E"] == pytest.approx((5.0 - 3.0) / expected_std)


def test_zscore_sector_isolates_within_sector_only():
    registry = FeatureRegistry()
    base = registry.register(
        FeatureDef(
            name="base_feat2",
            version="1.0.0",
            owner="test-owner",
            lookback=0,
            rationale="Base feature for a known-answer sector zscore test.",
            missing_data_policy="treat_as_missing",
            compute=lambda h: h["close"].astype(float),
        )
    )
    _, _, zs_fd = register_cross_sectional_transforms(registry, base, owner="test-owner")

    cross_section = pd.DataFrame(
        {
            "base_feat2": [1.0, 3.0, 100.0, 300.0],
            "sector": ["S1", "S1", "S2", "S2"],
        },
        index=["A", "B", "C", "D"],
    )
    result = zs_fd.compute(cross_section)
    # within S1: mean=2, std=1 -> A=-1, B=+1; within S2: mean=200, std=100 -> C=-1, D=+1
    assert result.loc["A"] == pytest.approx(-1.0)
    assert result.loc["B"] == pytest.approx(1.0)
    assert result.loc["C"] == pytest.approx(-1.0)
    assert result.loc["D"] == pytest.approx(1.0)


def test_zscore_sector_yields_nan_for_a_sector_with_a_single_member():
    registry = FeatureRegistry()
    base = registry.register(
        FeatureDef(
            name="base_feat3",
            version="1.0.0",
            owner="test-owner",
            lookback=0,
            rationale="Base feature for a lone-sector-member edge case.",
            missing_data_policy="treat_as_missing",
            compute=lambda h: h["close"].astype(float),
        )
    )
    _, _, zs_fd = register_cross_sectional_transforms(registry, base, owner="test-owner")

    cross_section = pd.DataFrame(
        {"base_feat3": [1.0, 3.0, 100.0], "sector": ["S1", "S1", "S2"]},
        index=["A", "B", "C"],
    )
    result = zs_fd.compute(cross_section)
    assert not pd.isna(result.loc["A"])
    assert pd.isna(result.loc["C"])  # sector S2 has only one member -- genuinely undefined, not 0


def test_zscore_sector_requires_a_sector_column():
    registry = FeatureRegistry()
    base = registry.register(
        FeatureDef(
            name="base_feat4",
            version="1.0.0",
            owner="test-owner",
            lookback=0,
            rationale="Base feature to test the missing sector-column guard.",
            missing_data_policy="treat_as_missing",
            compute=lambda h: h["close"].astype(float),
        )
    )
    _, _, zs_fd = register_cross_sectional_transforms(registry, base, owner="test-owner")
    cross_section = pd.DataFrame({"base_feat4": [1.0, 2.0]}, index=["A", "B"])
    with pytest.raises(ValueError, match="sector"):
        zs_fd.compute(cross_section)


def test_register_cross_sectional_transforms_rejects_a_cross_sectional_base():
    registry = FeatureRegistry()
    xs_base = registry.register(
        FeatureDef(
            name="already_cross_sectional",
            version="1.0.0",
            owner="test-owner",
            lookback=0,
            rationale="A feature that is itself already cross-sectional.",
            missing_data_policy="treat_as_missing",
            kind="cross_sectional",
            compute=lambda cs: cs.iloc[:, 0],
        )
    )
    with pytest.raises(ValueError, match="per_security"):
        register_cross_sectional_transforms(registry, xs_base, owner="test-owner")

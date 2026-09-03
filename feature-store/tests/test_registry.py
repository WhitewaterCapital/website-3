"""Registry integrity tests -- FEAT-01 (a).

Spec: "Define each feature once as a pure function of point in time
inputs, with name, version, owner, lookback and a written economic
rationale. No rationale, no registration."
"""
from __future__ import annotations

import pandas as pd
import pytest

from fs.registry import FeatureDef, FeatureRegistry


def _dummy_compute(history: pd.DataFrame) -> pd.Series:
    return history["close"].astype(float)


def test_registration_refuses_missing_rationale():
    with pytest.raises(ValueError, match="rationale"):
        FeatureDef(
            name="no_rationale_feature",
            version="1.0.0",
            owner="quant-team",
            lookback=1,
            rationale="",
            missing_data_policy="treat_as_missing",
            compute=_dummy_compute,
        )


def test_registration_refuses_whitespace_only_rationale():
    with pytest.raises(ValueError, match="rationale"):
        FeatureDef(
            name="whitespace_rationale_feature",
            version="1.0.0",
            owner="quant-team",
            lookback=1,
            rationale="   \n\t  ",
            missing_data_policy="treat_as_missing",
            compute=_dummy_compute,
        )


def test_registration_refuses_missing_owner():
    with pytest.raises(ValueError, match="owner"):
        FeatureDef(
            name="no_owner_feature",
            version="1.0.0",
            owner="",
            lookback=1,
            rationale="some rationale that is non-empty",
            missing_data_policy="treat_as_missing",
            compute=_dummy_compute,
        )


def test_registration_refuses_missing_version():
    with pytest.raises(ValueError, match="version"):
        FeatureDef(
            name="no_version_feature",
            version="",
            owner="quant-team",
            lookback=1,
            rationale="some rationale that is non-empty",
            missing_data_policy="treat_as_missing",
            compute=_dummy_compute,
        )


def test_forward_fill_max_age_requires_positive_max_age():
    with pytest.raises(ValueError, match="max_age_periods"):
        FeatureDef(
            name="bad_ffill_feature",
            version="1.0.0",
            owner="quant-team",
            lookback=1,
            rationale="some rationale that is non-empty",
            missing_data_policy="forward_fill_max_age",
            max_age_periods=None,
            compute=_dummy_compute,
        )
    with pytest.raises(ValueError, match="max_age_periods"):
        FeatureDef(
            name="bad_ffill_feature_2",
            version="1.0.0",
            owner="quant-team",
            lookback=1,
            rationale="some rationale that is non-empty",
            missing_data_policy="forward_fill_max_age",
            max_age_periods=0,
            compute=_dummy_compute,
        )


def test_max_age_periods_rejected_for_other_policies():
    with pytest.raises(ValueError, match="max_age_periods"):
        FeatureDef(
            name="stray_max_age_feature",
            version="1.0.0",
            owner="quant-team",
            lookback=1,
            rationale="some rationale that is non-empty",
            missing_data_policy="treat_as_missing",
            max_age_periods=5,
            compute=_dummy_compute,
        )


def test_invalid_missing_data_policy_rejected():
    with pytest.raises(ValueError, match="missing_data_policy"):
        FeatureDef(
            name="bad_policy_feature",
            version="1.0.0",
            owner="quant-team",
            lookback=1,
            rationale="some rationale that is non-empty",
            missing_data_policy="fill_with_zero",  # not a real policy
            compute=_dummy_compute,
        )


def test_cross_sectional_kind_rejects_forward_fill_max_age():
    with pytest.raises(ValueError, match="cross_sectional"):
        FeatureDef(
            name="bad_xs_feature",
            version="1.0.0",
            owner="quant-team",
            lookback=0,
            rationale="some rationale that is non-empty",
            missing_data_policy="forward_fill_max_age",
            max_age_periods=3,
            compute=_dummy_compute,
            kind="cross_sectional",
        )


def test_a_valid_feature_registers_successfully():
    registry = FeatureRegistry()
    fd = registry.register(
        FeatureDef(
            name="valid_feature",
            version="1.0.0",
            owner="quant-team",
            lookback=5,
            rationale="A perfectly reasonable economic rationale for this feature.",
            missing_data_policy="treat_as_missing",
            compute=_dummy_compute,
        )
    )
    assert fd is registry.get("valid_feature")
    assert fd is registry.get("valid_feature", version="1.0.0")
    assert "valid_feature" in registry
    assert len(registry) == 1
    assert registry.list() == [fd]


def test_duplicate_name_and_version_refused():
    registry = FeatureRegistry()
    make = lambda: FeatureDef(
        name="dup_feature",
        version="1.0.0",
        owner="quant-team",
        lookback=1,
        rationale="A perfectly reasonable economic rationale for this feature.",
        missing_data_policy="treat_as_missing",
        compute=_dummy_compute,
    )
    registry.register(make())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(make())


def test_same_name_different_version_is_allowed_and_latest_wins_unversioned():
    registry = FeatureRegistry()
    v1 = registry.register(
        FeatureDef(
            name="evolving_feature",
            version="1.0.0",
            owner="quant-team",
            lookback=1,
            rationale="A perfectly reasonable economic rationale for this feature.",
            missing_data_policy="treat_as_missing",
            compute=_dummy_compute,
        )
    )
    v2 = registry.register(
        FeatureDef(
            name="evolving_feature",
            version="2.0.0",
            owner="quant-team",
            lookback=1,
            rationale="A perfectly reasonable economic rationale for this feature, updated.",
            missing_data_policy="treat_as_missing",
            compute=_dummy_compute,
        )
    )
    assert registry.get("evolving_feature") is v2
    assert registry.get("evolving_feature", version="1.0.0") is v1
    assert registry.get("evolving_feature", version="2.0.0") is v2


def test_get_unknown_feature_raises_keyerror():
    registry = FeatureRegistry()
    with pytest.raises(KeyError):
        registry.get("does_not_exist")

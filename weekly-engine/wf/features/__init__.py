"""Feature layer. Importing this package registers every per-ticker feature
function (returns.py, technical.py) into registry.FEATURE_REGISTRY, and
exposes build_feature_panel as the one entry point everything else uses."""

from . import returns, technical  # noqa: F401 (populates FEATURE_REGISTRY)
from .panel import build_feature_panel, prepare_base  # noqa: F401
from .registry import FEATURE_REGISTRY, base_manifest, manifest_hash  # noqa: F401

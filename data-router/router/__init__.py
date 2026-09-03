"""Data Router — the one internal service every model calls for data.

No model in this codebase should ever import a vendor SDK, hold a vendor API
key, or branch on a vendor's name. Everything vendor-specific is isolated
behind `router.adapters.base.Adapter`; everything a model sees is one of the
schemas in `router.schema`, which carry full point-in-time provenance by
construction.

See ``data-router/README.md`` for the architecture, what is and is not
exercised in this sandbox (no network, no real vendor calls — ever), and the
extension point for wiring up a real vendor later.
"""

from __future__ import annotations

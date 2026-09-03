"""Tiingo adapter STUB — same shape as `alpha_vantage.py`, see that module's
docstring for the full extension-point explanation. No network call is made
anywhere in this file. `engine/incepta/adapters/prices_tiingo.py` is this
codebase's existing real Tiingo integration for the (separate) Incepta
engine — this stub exists only to prove the router's adapter interface is
vendor-agnostic and would accept a second bars vendor for the fallback chain
without any router or model code changing."""

from __future__ import annotations

from datetime import date

from ..config import env
from ..schema import Bar
from .base import Adapter, DataClass, VendorNotConfiguredError

REQUIRED_ENV_VAR = "TIINGO_API_KEY"


class TiingoAdapter(Adapter):
    name = "tiingo"
    capabilities = frozenset({DataClass.BARS})

    def __init__(self) -> None:
        self._api_key = env(REQUIRED_ENV_VAR)

    def _require_key(self) -> str:
        if not self._api_key:
            raise VendorNotConfiguredError(
                f"{self.name} is not configured: environment variable "
                f"{REQUIRED_ENV_VAR} is not set. No network call has been "
                f"attempted."
            )
        return self._api_key

    def get_bars(self, ticker: str, start: date, end: date) -> list[Bar]:
        self._require_key()
        raise NotImplementedError(
            "Real Tiingo HTTP call not implemented in this sandbox (no "
            "network access). See router/adapters/alpha_vantage.py's "
            "docstring for the extension-point pattern to follow."
        )

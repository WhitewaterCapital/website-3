"""OpenBB adapter STUB — same shape as `alpha_vantage.py`, see that module's
docstring for the full extension-point explanation. No network call is made
anywhere in this file."""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..config import env
from ..schema import Bar, FundamentalFact, NewsItem
from .base import Adapter, DataClass, VendorNotConfiguredError

REQUIRED_ENV_VAR = "OPENBB_API_KEY"


class OpenBBAdapter(Adapter):
    name = "openbb"
    capabilities = frozenset({DataClass.BARS, DataClass.FUNDAMENTALS, DataClass.NEWS})

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
        raise NotImplementedError("see router/adapters/alpha_vantage.py")

    def get_fundamentals(self, ticker: str) -> list[FundamentalFact]:
        self._require_key()
        raise NotImplementedError("see router/adapters/alpha_vantage.py")

    def get_news(self, ticker: Optional[str] = None, since: Optional[date] = None) -> list[NewsItem]:
        self._require_key()
        raise NotImplementedError("see router/adapters/alpha_vantage.py")

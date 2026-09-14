"""Vendor adapters for WW-CHAOS's live-data gate.

Currently one adapter: `alpaca_bars.py` (Alpaca Market Data API, free
"Basic" plan — see that module's docstring for the full research trail on
why Alpaca was chosen over Twelve Data, Finnhub, Polygon/Massive, and
unofficial Yahoo Finance endpoints). This package exists so `export.py`'s
import (`from .adapters.alpaca_bars import ...`) has somewhere to live —
mirrors `earnings-engine/ee/adapters/`, `data-router/router/adapters/`, and
`cascade-data-engine/cde/adapters/`'s identical layout. This engine is
sealed (see `chaos/__init__.py`); nothing here is imported by, or imports
from, any other engine's adapters package.
"""

from __future__ import annotations

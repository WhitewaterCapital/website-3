"""WW-FACTOR — a sealed Fama-French factor-exposure engine.

Shares no code or state with any other model in this repo (Incepta, WW-GRAPH,
WW-WEEKLY, Intra/Exitus, Aurora, ...). Reaches the website through a single
JSON export, exactly as the other engines do: `python -m fac.export` writes
`<repo>/public/data/factor/latest.json`.
"""

from __future__ import annotations

__version__ = "0.1.0"

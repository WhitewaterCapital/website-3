"""WW-GRAPH — a sealed graph-diffusion pairs engine.

Shares no code or state with any other model in this repo (Incepta, Intra/Exitus,
Aurora, ...). Reaches the website through a single JSON export, exactly as the
other engines do: `python -m ge.export` writes
`<repo>/public/data/graph/latest.json`.
"""

from __future__ import annotations

__version__ = "0.1.0"

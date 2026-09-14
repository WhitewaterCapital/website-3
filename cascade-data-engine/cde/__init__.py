"""WW-CASCADE-DATA — real ETF-holdings ingestion for quant-infra/cascade.

Fetches per-fund holdings (product, constituent, weight, as_at_date) and
fund-level shares-outstanding snapshots for a small starter universe of
liquid iShares funds, in the exact shape `quant-infra/cascade/pressure.py`'s
`compute_pressure` expects, and writes the resulting (honestly partial —
see DISCLAIMER in config.py) pressure export the website reads.

This is the data-plumbing half of WW-CASCADE. The math (pressure, its
permanent/temporary decomposition, its transmission into realised return)
already exists and is already tested in `quant-infra/cascade/` — this
engine's only job is to give it real inputs instead of none. See README.md
for the full research trail on why iShares' public CSV export was chosen
and exactly what is/isn't confirmed live.
"""

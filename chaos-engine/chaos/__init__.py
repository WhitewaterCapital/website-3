"""WW-CHAOS — a sealed intraday dislocation-detection and -trading engine.

WHAT THIS IS: a research model that (1) detects when a market has stopped
behaving normally on an intraday basis, (2) classifies the dislocation with a
hysteresis state machine, (3) forecasts the short-horizon directional path with
a calibrated, abstention-aware classifier, and (4) reports gross- and net-of-cost
performance side by side, at execution assumptions that do not flatter the
model.

WHAT THIS IS NOT: this is not high-frequency trading. There is no colocated
infrastructure, no microsecond order-book access, and nothing here claims
latency edge. What is reachable, and all that is claimed, is **intraday
dislocation capture on a 1 to 15 minute horizon**, using bar data a normal
retail/prosumer data feed can provide.

This engine is sealed: it shares no code or state with the equity engine
(`../engine/`), the intra/exitus planner (`../intra-exitus-engine/`), or any
other model in this repository. The only way it touches the website is a
single JSON export (`chaos/export.py`) read by `src/lib/chaos.ts`. Nothing
else in the app knows this engine exists.

See chaos-engine/README.md for the full "what this is and is not" framing,
and the "Known simplifications" section for what is stubbed out for lack of a
local deep-learning framework, live quote/spread data, or a news feed.
"""

from __future__ import annotations

__version__ = "0.1.0"

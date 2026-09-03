"""WW-LABEL — the label engine (FEAT-02).

Sealed engine: shares no code and no state with any other component in this
repo (../engine, ../weekly-engine, ../graph-engine, ../feature-store, etc).
It exposes only a plain function API — callers pass in price series /
signal series / DataFrames and get labels, weights, or an assertion result
back. No shared state, no imports from and no imports into any other engine.

Why this exists as its own package rather than living inside each model
(straight from the FEAT-02 spec): "Labels are where look ahead gets in, so
they get their own component and their own tests rather than living inside
each model." Concretely, this package supplies four independent primitives:

  * `forward_return`     — fixed-horizon forward-return labels, each one
                            carrying an explicit `knowable_from` timestamp.
  * `triple_barrier`      — López de Prado triple-barrier labels for
                            short-horizon models, volatility-scaled and
                            point-in-time safe.
  * `uniqueness`          — average-uniqueness sample weights for overlapping
                            label windows, so training does not silently
                            treat one market move as N independent samples.
  * `meta_label`          — the secondary "should I act on the primary
                            signal" target, trained only on rows where the
                            primary model actually fired.

And one non-negotiable guardrail:

  * `lookahead_assert.assert_no_lookahead` — raises (never warns) if any
    feature's as-of timestamp is not strictly before its paired label's
    knowable-from timestamp. There is no parameter anywhere in this module
    to disable, weaken, or bypass that check.

See ../README.md for the full design writeup, the labeling conventions this
package commits to, and what integrating this into feature-store/weekly-engine
would take (deliberately not done in this pass).
"""

from __future__ import annotations

from .forward_return import ForwardReturnLabel, forward_return_labels
from .lookahead_assert import LookAheadError, assert_no_lookahead
from .meta_label import build_meta_labels
from .triple_barrier import TripleBarrierLabel, triple_barrier_label
from .uniqueness import LabelWindow, average_uniqueness_weights

__version__ = "0.1.0"

__all__ = [
    "ForwardReturnLabel",
    "forward_return_labels",
    "TripleBarrierLabel",
    "triple_barrier_label",
    "LabelWindow",
    "average_uniqueness_weights",
    "build_meta_labels",
    "LookAheadError",
    "assert_no_lookahead",
]

"""
Three-model spread (PATH-06): the same instrument, priced under local
volatility, Heston, and a historical bootstrap, published side by side as a
standing diagnostic rather than a single number anyone should trade off.

**READ THIS BEFORE USING ANY NUMBER THIS MODULE RETURNS.**

Local vol and Heston are both risk-neutral (Q-measure) models: they are
calibrated (or, for Heston in this build, parameterized) so that their
simulated dynamics are consistent with no-arbitrage pricing, and the prices
they produce are genuine no-arbitrage values of the instrument *given that
model's dynamics*. The historical bootstrap is **not** a risk-neutral
model — it resamples a real-world (here, synthetic-stand-in) return series
and carries whatever real-world drift that series happens to have. Running
the identical payoff through it and calling the result a "price" is a
category error unless the bootstrap's drift happens to equal the
risk-free rate, which there is no reason to expect.

So what is this module actually for? Two things, both diagnostic:

1. **Local-vol vs Heston spread** is a legitimate, standard model-risk
   question: two different Q-measure dynamics consistent with (parts of)
   the same market can price a path-dependent exotic differently even when
   they agree on vanilla option prices, because they disagree on the joint
   distribution of the path, not just the terminal marginal. This spread
   is real, tradeable-relevant information: it is the size of the pricing
   uncertainty that comes from *model choice alone*, holding the market's
   vanilla quotes fixed.
2. **Historical-bootstrap vs either Q-measure price** answers a different
   question entirely: "if the future actually looks like this historical
   return series, how would the realized payoff compare to what the market
   charges for it under no-arbitrage." That is a real-world backtest-style
   comparison — useful for understanding whether a structure is cheap or
   rich *relative to a real-world return assumption*, which is exactly the
   kind of judgment call a discretionary or systematic strategy might make
   deliberately, with eyes open. It is never itself a risk-neutral price,
   and — per this whole engine's one hard rule (see `path-engine/README.md`)
   — it must never be fed back into a forecasting model, a Sharpe-ratio
   calculation, or anything else that treats it as if it carries no-arbitrage
   meaning.

`three_model_spread` labels every number it returns with which of these two
categories it belongs to (`meta['measure'] = 'Q'` or `'P'`) precisely so a
caller cannot lose track of that distinction by accident.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..engine.bootstrap import historical_bootstrap_paths, synthetic_historical_returns
from ..engine.heston import HestonParams, simulate_heston_qe_paths
from ..engine.localvol import LocalVolParams, simulate_local_vol_paths
from ..engine.pricer import price_from_paths
from ..surface.surface import VolSurface
from ..types import MonteCarloResult


@dataclass(frozen=True)
class ThreeModelSpread:
    local_vol: MonteCarloResult
    heston: MonteCarloResult
    historical_bootstrap: MonteCarloResult
    q_measure_spread: float  # |local_vol.price - heston.price|, the model-risk number
    meta: dict = field(default_factory=dict)

    def summary(self) -> str:
        lv, he, hb = self.local_vol, self.heston, self.historical_bootstrap
        return (
            f"local-vol (Q):  {lv.price:.6f} +/- {lv.std_error:.6f}\n"
            f"heston (Q):     {he.price:.6f} +/- {he.std_error:.6f}\n"
            f"Q-measure spread |local_vol - heston| = {self.q_measure_spread:.6f}\n"
            f"historical bootstrap (P, NOT a price): {hb.price:.6f} +/- {hb.std_error:.6f}\n"
            "  (diagnostic only -- never feed this into a forecasting model as a risk-neutral value)"
        )


def three_model_spread(
    payoff_fn: Callable[[np.ndarray], np.ndarray],
    S0: float,
    r: float,
    q: float,
    T: float,
    surface: VolSurface,
    heston_params: HestonParams,
    n_paths: int,
    n_steps: int,
    seed: int,
    block_size: int = 5,
    n_historical_days: int = 5000,
) -> ThreeModelSpread:
    """Price `payoff_fn` (a pure function of a path array, per this
    package's payoff convention) under all three path sources and publish
    the spread.

    Common random numbers: the same `seed` drives local vol and Heston's
    variance/price draws, and `seed`-derived draws for the bootstrap's block
    starts — see `pe.engine.random_streams` module docstring on CRN. This
    does not make the three models' terminal distributions identical (they
    aren't), but it does mean any spread you see isn't an artifact of one
    model getting luckier draws than another.
    """
    lv_params = LocalVolParams(surface=surface, S0=S0, r=r, q=q)
    _, lv_paths, _ = simulate_local_vol_paths(lv_params, T, n_steps, n_paths, seed, antithetic=True)
    lv_result = price_from_paths(lv_paths, payoff_fn, r, T, antithetic=True, meta={"measure": "Q", "model": "local_vol"})

    _, heston_paths, _, _ = simulate_heston_qe_paths(S0, r, q, heston_params, T, n_steps, n_paths, seed, antithetic=True)
    heston_result = price_from_paths(
        heston_paths, payoff_fn, r, T, antithetic=True, meta={"measure": "Q", "model": "heston_qe"}
    )

    hist_returns = synthetic_historical_returns(n_historical_days, seed=seed)
    _, boot_paths, boot_info = historical_bootstrap_paths(hist_returns, S0, n_steps, n_paths, seed, block_size=block_size)
    # Bootstrap paths are undiscounted real-world trajectories; there is no
    # risk-neutral discount rate to apply to a P-measure quantity, so the
    # "price" reported here is deliberately just the undiscounted expected
    # payoff -- a real-world expected payout, not a value. Discounting it at
    # `r` would dress a P-measure number up as if it were a Q-measure price,
    # which is exactly the category error this module's docstring warns
    # against.
    boot_payoff = payoff_fn(boot_paths)
    from ..engine.mc import mc_stats

    boot_result = mc_stats(
        boot_payoff,
        meta={
            "measure": "P",
            "model": "historical_bootstrap",
            "warning": "NOT a risk-neutral price; undiscounted real-world expected payoff only",
            "empirical_mean_daily": boot_info.empirical_mean_daily,
            "empirical_vol_daily": boot_info.empirical_vol_daily,
            "block_size": boot_info.block_size,
        },
    )

    spread = abs(lv_result.price - heston_result.price)
    return ThreeModelSpread(
        local_vol=lv_result,
        heston=heston_result,
        historical_bootstrap=boot_result,
        q_measure_spread=spread,
        meta={"n_paths": n_paths, "n_steps": n_steps, "T": T},
    )
